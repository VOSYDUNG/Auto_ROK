from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import shutil

import cv2
import numpy as np
import pytest

from harness.template_anchors import TemplateAnchorError, calibrate_template, resolve_template


NOW = datetime(2026, 9, 14, 7, 0, tzinfo=timezone.utc)
SPEC = {"id": "WORLD_MAP_BUTTON", "label": "World map button (Space)",
        "algorithm": "opencv.TM_CCOEFF_NORMED", "match_threshold": 0.9,
        "representation": "grayscale_laplacian_abs_v1",
        "minimum_runner_up_margin": 0.12}
CONFIG_HASH = "c" * 64


def write_png(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(path), image)


def capture(path: Path, frame_id: str, *, age_seconds: float = 0.0,
            width: int = 180, height: int = 120, dpi: float = 1.0) -> dict:
    return {"status": "captured", "target": {"title": "Rise of Kingdoms", "exe": "MASS.exe"},
            "frame": {"id": frame_id, "captured_at": (NOW - timedelta(seconds=age_seconds)).isoformat(),
                      "width": width, "height": height, "dpi_scale": dpi,
                      "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}


@pytest.fixture
def anchor_case(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    artifact_dir = root / "workspace" / "runs" / ".pytest-g006-anchors"
    shutil.rmtree(artifact_dir, ignore_errors=True)
    reference = np.zeros((120, 180, 3), dtype=np.uint8)
    cv2.circle(reference, (35, 35), 20, (240, 180, 20), 4)
    cv2.line(reference, (24, 42), (47, 20), (255, 255, 255), 3)
    cv2.putText(reference, "MAP", (17, 63), cv2.FONT_HERSHEY_SIMPLEX, .35, (255, 255, 255), 1)
    reference_path = tmp_path / "reference.png"
    write_png(reference_path, reference)
    reference_capture = capture(reference_path, "reference")
    calibration = calibrate_template(reference_path, reference_capture, SPEC, (10, 10, 52, 60),
                                     artifact_dir / "template.png", CONFIG_HASH)
    template = cv2.imread(str(artifact_dir / "template.png"))
    yield tmp_path, artifact_dir, calibration, template, reference_path, reference_capture
    shutil.rmtree(artifact_dir, ignore_errors=True)


def current_image(tmp_path: Path, template: np.ndarray, locations: list[tuple[int, int]],
                  name: str = "current.png") -> tuple[Path, dict]:
    image = np.zeros((120, 180, 3), dtype=np.uint8)
    height, width = template.shape[:2]
    for x, y in locations:
        image[y:y + height, x:x + width] = template
    path = tmp_path / name
    write_png(path, image)
    return path, capture(path, name)


def test_resolves_distinct_frame_at_current_pixels(anchor_case) -> None:
    tmp_path, _, calibration, template, _, _ = anchor_case
    path, evidence = current_image(tmp_path, template, [(105, 45)])
    status, target, details = resolve_template(path, evidence, calibration, SPEC, CONFIG_HASH, now=NOW)
    assert status == "RESOLVED"
    assert [target.bbox.x1, target.bbox.y1, target.bbox.x2, target.bbox.y2] == [105, 45, 157, 105]
    assert target.frame_id == "current.png"
    assert target.confidence == 0.0
    assert target.metadata["score_is_probability"] is False
    assert details["match_score"] >= 0.9


def test_missing_and_ambiguous_matches_fail_closed(anchor_case) -> None:
    tmp_path, _, calibration, template, _, _ = anchor_case
    noise = np.random.default_rng(5).integers(0, 256, (120, 180, 3), dtype=np.uint8)
    missing_path = tmp_path / "missing.png"
    write_png(missing_path, noise)
    status, target, details = resolve_template(missing_path, capture(missing_path, "missing"), calibration,
                                               SPEC, CONFIG_HASH, now=NOW)
    assert (status, target, details["reason"]) == ("NEEDS_DECISION", None, "match_below_threshold")
    ambiguous_path, ambiguous_capture = current_image(tmp_path, template, [(5, 5), (120, 55)], "ambiguous.png")
    status, target, details = resolve_template(ambiguous_path, ambiguous_capture, calibration,
                                               SPEC, CONFIG_HASH, now=NOW)
    assert (status, target, details["reason"]) == ("NEEDS_DECISION", None, "ambiguous_runner_up")


def test_laplacian_representation_resolves_luminance_shift(anchor_case) -> None:
    tmp_path, _, calibration, template, _, _ = anchor_case
    image = np.zeros((120, 180, 3), dtype=np.uint8)
    # This is a controlled synthetic exposure shift, not a probability calibration.
    shifted = np.clip(template.astype(np.float32) * 0.48 + 20, 0, 255).astype(np.uint8)
    height, width = shifted.shape[:2]
    image[45:45 + height, 105:105 + width] = shifted
    path = tmp_path / "night-like.png"
    write_png(path, image)
    status, target, details = resolve_template(path, capture(path, "night-like"), calibration,
                                               SPEC, CONFIG_HASH, now=NOW)
    assert status == "RESOLVED"
    assert target is not None
    assert details["representation"] == "grayscale_laplacian_abs_v1"


def test_stale_layout_and_reference_replay_are_rejected(anchor_case) -> None:
    tmp_path, _, calibration, template, reference_path, reference_capture = anchor_case
    path, evidence = current_image(tmp_path, template, [(105, 45)])
    stale = capture(path, "stale", age_seconds=31)
    with pytest.raises(TemplateAnchorError, match="stale"):
        resolve_template(path, stale, calibration, SPEC, CONFIG_HASH, now=NOW, max_age_seconds=30)
    layout = capture(path, "layout", width=181)
    with pytest.raises(TemplateAnchorError, match="layout or DPI"):
        resolve_template(path, layout, calibration, SPEC, CONFIG_HASH, now=NOW)
    with pytest.raises(TemplateAnchorError, match="calibration replay"):
        resolve_template(reference_path, reference_capture, calibration, SPEC, CONFIG_HASH, now=NOW)


def test_tampered_policy_and_external_template_path_are_rejected(anchor_case) -> None:
    tmp_path, _, calibration, template, _, _ = anchor_case
    path, evidence = current_image(tmp_path, template, [(105, 45)])
    lowered = dict(calibration, match_threshold=0.0)
    with pytest.raises(TemplateAnchorError, match="policy"):
        resolve_template(path, evidence, lowered, SPEC, CONFIG_HASH, now=NOW)
    external = tmp_path / "external.png"
    write_png(external, template)
    escaped = dict(calibration, template_path=str(external), template_sha256=hashlib.sha256(external.read_bytes()).hexdigest())
    with pytest.raises(TemplateAnchorError, match="workspace/runs"):
        resolve_template(path, evidence, escaped, SPEC, CONFIG_HASH, now=NOW)
    changed_representation = dict(calibration, representation="raw_color_v1")
    with pytest.raises(TemplateAnchorError, match="policy"):
        resolve_template(path, evidence, changed_representation, SPEC, CONFIG_HASH, now=NOW)
