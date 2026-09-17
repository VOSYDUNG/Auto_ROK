"""Frame-bound template landmarks for current visible ROK pixels."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from harness.contracts import BoundingBox
from harness.scene_graph import VisualTarget


class TemplateAnchorError(ValueError):
    pass


def _read_image(path: Path):
    import cv2
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise TemplateAnchorError(f"cannot decode image: {path}")
    return image


def _representation(image, representation: str):
    """Return the single, policy-locked image representation used for matching."""
    import cv2
    if representation != "grayscale_laplacian_abs_v1":
        raise TemplateAnchorError("unsupported template representation")
    grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.convertScaleAbs(cv2.Laplacian(grayscale, cv2.CV_32F, ksize=3))


def _hash(path: Path) -> str:
    if not path.is_file():
        raise TemplateAnchorError(f"image is missing: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _template_artifact_path(value: Any) -> Path:
    path = Path(str(value)).resolve()
    root = (Path(__file__).resolve().parents[1] / "workspace" / "runs").resolve()
    if path == root or not path.is_relative_to(root):
        raise TemplateAnchorError("template path must be a file below workspace/runs")
    return path


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise TemplateAnchorError("frame time must include a timezone")
    return parsed.astimezone(timezone.utc)


def _validate_frame(capture: Mapping[str, Any], image_path: Path, now: datetime, max_age_seconds: float) -> None:
    if capture.get("status") != "captured" or capture.get("target", {}).get("title") != "Rise of Kingdoms" \
            or capture.get("target", {}).get("exe") != "MASS.exe":
        raise TemplateAnchorError("capture is not current ROK target evidence")
    frame = capture.get("frame", {})
    if _hash(image_path) != frame.get("image_sha256"):
        raise TemplateAnchorError("current image hash does not match capture frame")
    captured_at = _time(frame.get("captured_at", ""))
    age = (now.astimezone(timezone.utc) - captured_at).total_seconds()
    if age < -1.0 or age > max_age_seconds:
        raise TemplateAnchorError("current frame is future-dated or stale")


def load_anchor_spec(config: Mapping[str, Any], anchor_id: str) -> dict[str, Any]:
    if config.get("schema_version") != 1 or not isinstance(config.get("anchors"), list):
        raise TemplateAnchorError("invalid anchor config")
    matches = [item for item in config["anchors"] if item.get("id") == anchor_id]
    if len(matches) != 1:
        raise TemplateAnchorError(f"expected one anchor spec {anchor_id!r}, found {len(matches)}")
    spec = dict(matches[0])
    if spec.get("algorithm") != "opencv.TM_CCOEFF_NORMED":
        raise TemplateAnchorError("unsupported template algorithm")
    if spec.get("representation") != "grayscale_laplacian_abs_v1":
        raise TemplateAnchorError("unsupported template representation")
    threshold, margin = spec.get("match_threshold"), spec.get("minimum_runner_up_margin")
    if type(threshold) not in (int, float) or type(margin) not in (int, float) \
            or not 0.0 <= threshold <= 1.0 or not 0.0 <= margin <= 2.0:
        raise TemplateAnchorError("invalid template threshold or margin")
    return spec


def calibrate_template(
    reference_image: Path,
    reference_capture: Mapping[str, Any],
    spec: Mapping[str, Any],
    bbox: tuple[int, int, int, int],
    template_path: Path,
    config_sha256: str,
) -> dict[str, Any]:
    """Create an auditable local crop; its source bbox is never used for resolution."""
    frame = reference_capture["frame"]
    _validate_frame(reference_capture, reference_image, _time(frame["captured_at"]), 1.0)
    image = _read_image(reference_image)
    x, y, width, height = bbox
    if x < 0 or y < 0 or width < 8 or height < 8 or x + width > image.shape[1] or y + height > image.shape[0]:
        raise TemplateAnchorError("calibration bbox is outside the reference image")
    crop = image[y:y + height, x:x + width].copy()
    if float(crop.std()) < 2.0:
        raise TemplateAnchorError("calibration crop is low-information")
    import cv2
    ok, encoded = cv2.imencode(".png", crop)
    if not ok:
        raise TemplateAnchorError("cannot encode template crop")
    template_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = template_path.with_name(template_path.name + ".tmp")
    temporary.write_bytes(encoded.tobytes())
    temporary.replace(template_path)
    template_hash = _hash(template_path)
    calibration_id = f"{spec['id'].lower()}-{template_hash[:12]}"
    return {
        "schema_version": 1,
        "calibration_id": calibration_id,
        "anchor_id": spec["id"],
        "label": spec["label"],
        "algorithm": spec["algorithm"],
        "representation": spec["representation"],
        "match_threshold": spec["match_threshold"],
        "minimum_runner_up_margin": spec["minimum_runner_up_margin"],
        "config_sha256": config_sha256,
        "template_path": str(template_path),
        "template_sha256": template_hash,
        "template_size": [width, height],
        "source_frame_id": frame["id"],
        "source_frame_sha256": frame["image_sha256"],
        "source_bbox_for_audit_only": list(bbox),
        "layout_profile": {"width": frame["width"], "height": frame["height"],
                           "dpi_scale": frame["dpi_scale"]},
        "score_semantics": "TM_CCOEFF_NORMED normalized correlation; not a calibrated probability",
    }


def resolve_template(
    current_image: Path,
    current_capture: Mapping[str, Any],
    calibration: Mapping[str, Any],
    spec: Mapping[str, Any],
    config_sha256: str,
    *,
    now: datetime | None = None,
    max_age_seconds: float = 30.0,
) -> tuple[str, VisualTarget | None, dict[str, Any]]:
    current_time = now or datetime.now(timezone.utc)
    _validate_frame(current_capture, current_image, current_time, max_age_seconds)
    policy_fields = ("anchor_id", "label", "algorithm", "representation", "match_threshold", "minimum_runner_up_margin")
    expected_policy = {"anchor_id": spec["id"], "label": spec["label"], "algorithm": spec["algorithm"],
                       "representation": spec["representation"],
                       "match_threshold": spec["match_threshold"],
                       "minimum_runner_up_margin": spec["minimum_runner_up_margin"]}
    if calibration.get("config_sha256") != config_sha256 \
            or any(calibration.get(key) != expected_policy[key] for key in policy_fields):
        raise TemplateAnchorError("calibration policy does not match current anchor config")
    frame = current_capture["frame"]
    layout = calibration.get("layout_profile", {})
    if [frame.get("width"), frame.get("height"), frame.get("dpi_scale")] != \
            [layout.get("width"), layout.get("height"), layout.get("dpi_scale")]:
        raise TemplateAnchorError("current frame layout or DPI does not match calibration")
    if frame.get("image_sha256") == calibration.get("source_frame_sha256"):
        raise TemplateAnchorError("resolution requires a distinct current frame, not calibration replay")
    template_path = _template_artifact_path(calibration.get("template_path", ""))
    if _hash(template_path) != calibration.get("template_sha256"):
        raise TemplateAnchorError("template bytes do not match calibration hash")
    image = _representation(_read_image(current_image), calibration["representation"])
    template = _representation(_read_image(template_path), calibration["representation"])
    if template.shape[0] >= image.shape[0] or template.shape[1] >= image.shape[1]:
        raise TemplateAnchorError("template does not fit current frame")

    import cv2
    result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
    _, best_score, _, best_location = cv2.minMaxLoc(result)
    if not math.isfinite(best_score):
        raise TemplateAnchorError("template matcher returned a non-finite score")
    suppressed = result.copy()
    x, y = best_location
    template_height, template_width = template.shape[:2]
    x1, x2 = max(0, x - template_width), min(suppressed.shape[1], x + template_width + 1)
    y1, y2 = max(0, y - template_height), min(suppressed.shape[0], y + template_height + 1)
    suppressed[y1:y2, x1:x2] = -1.0
    runner_up_score = float(cv2.minMaxLoc(suppressed)[1])
    margin = float(best_score) - runner_up_score
    details = {
        "status": "RESOLVED",
        "anchor_id": calibration["anchor_id"],
        "algorithm": calibration["algorithm"],
        "representation": calibration["representation"],
        "match_score": float(best_score),
        "runner_up_score": runner_up_score,
        "runner_up_margin": margin,
        "match_threshold": calibration["match_threshold"],
        "minimum_runner_up_margin": calibration["minimum_runner_up_margin"],
        "score_semantics": calibration["score_semantics"],
        "config_sha256": config_sha256,
    }
    if best_score < calibration["match_threshold"]:
        details.update(status="NEEDS_DECISION", reason="match_below_threshold")
        return "NEEDS_DECISION", None, details
    if margin < calibration["minimum_runner_up_margin"]:
        details.update(status="NEEDS_DECISION", reason="ambiguous_runner_up")
        return "NEEDS_DECISION", None, details
    bbox = BoundingBox(x, y, x + template_width, y + template_height)
    target = VisualTarget(
        target_id=calibration["anchor_id"], frame_id=frame["id"], label=calibration["label"],
        bbox=bbox, confidence=0.0, source="template_match",
        metadata={"frame_id": frame["id"], "image_sha256": frame["image_sha256"],
                  "captured_at": frame["captured_at"], "template_sha256": calibration["template_sha256"],
                  "calibration_id": calibration["calibration_id"], "algorithm": calibration["algorithm"],
                  "representation": calibration["representation"],
                  "config_sha256": config_sha256,
                  "match_score": float(best_score), "runner_up_score": runner_up_score,
                  "runner_up_margin": margin, "score_is_probability": False,
                  "calibrated_probability": None},
    )
    details["bbox"] = [bbox.x1, bbox.y1, template_width, template_height]
    return "RESOLVED", target, details


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)
