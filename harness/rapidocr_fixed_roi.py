"""Optional CPU-only RapidOCR recognizer for fixed resource-label ROIs.

The production Windows OCR bridge remains authoritative by default.  This
module is a bounded adapter for the fixed coordinate path: it never performs
full-screen detection, never returns action coordinates, and fails closed if
the source frame hash does not match the supplied capture evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
import copy
import hashlib
from pathlib import Path
import re
import time
from typing import Any, Iterable, Mapping

import cv2

from harness.cpu_roi import CpuRoiProfile, ResolvedRoi, load_default_cpu_roi_profile


@dataclass(frozen=True)
class RapidOcrLabelSpec:
    label: str
    roi_id: str


DEFAULT_LABELS: tuple[RapidOcrLabelSpec, ...] = (
    RapidOcrLabelSpec("Barbarians", "resource_category_barbarians"),
    RapidOcrLabelSpec("Cropland", "resource_category_cropland"),
    RapidOcrLabelSpec("Logging Camp", "resource_category_logging_camp"),
    RapidOcrLabelSpec("Stone Deposit", "resource_category_stone_deposit"),
    RapidOcrLabelSpec("Gold Deposit", "resource_category_gold_deposit"),
)


class RapidOcrFixedRoiError(RuntimeError):
    """The optional OCR dependency or the fixed-frame contract is invalid."""


def normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def image_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def overlay_ocr_payload(original: Mapping[str, Any], report: Mapping[str, Any]) -> dict[str, Any]:
    """Merge fixed-ROI labels into an OCR payload without desktop input.

    Only the declared bottom category row is replaced.  All other OCR words,
    frame/hash bindings and coordinate metadata remain from the acquisition
    adapter.  The result is suitable for the existing observation bridge but
    is explicitly marked as an optional experiment backend.
    """
    def is_category_row(item: Mapping[str, Any]) -> bool:
        bbox = item.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            return False
        try:
            x, y, _width, _height = (int(value) for value in bbox)
        except (TypeError, ValueError):
            return False
        return 320 <= x <= 1040 and 720 <= y <= 768

    elements = [
        copy.deepcopy(item)
        for item in original.get("elements", [])
        if isinstance(item, Mapping) and not is_category_row(item)
    ]
    next_index = len(elements)
    for word_index, item in enumerate(report.get("results", [])):
        if not isinstance(item, Mapping):
            continue
        rect = item.get("rect")
        text = item.get("text")
        if not isinstance(rect, list) or len(rect) != 4 or not isinstance(text, str):
            continue
        elements.append({
            "bbox": rect,
            "word_index": word_index,
            "confidence": item.get("score"),
            "confidence_known": item.get("confidence_known") is True,
            "text": text,
            "line_index": 4,
            "ocr_element_index": next_index,
            "acquisition": "rapidocr_fixed_roi",
            "grounding_authority": "ocr_backend",
            "frame_id": item.get("frame_id"),
            "image_sha256": item.get("image_sha256"),
        })
        next_index += 1
    overlay = copy.deepcopy(dict(original))
    overlay["elements"] = elements
    overlay["text"] = " ".join(str(item.get("text", "")) for item in elements).strip()
    overlay["backend"] = {
        "name": "Windows.Media.Ocr+RapidOCR.fixed_roi",
        "version": "windows-media-ocr+rapidocr_onnxruntime-1.4.4",
        "mode": "experiment_only_overlay",
        "device": "cpu",
        "providers": ["CPUExecutionProvider"],
        "detector": "disabled_fixed_roi",
    }
    overlay["input_emitted"] = False
    overlay["rapidocr_overlay"] = {
        "status": "experiment_only",
        "source_image": report.get("image"),
        "image_sha256": report.get("image_sha256"),
        "frame_id": report.get("frame_id"),
        "roi_profile_id": report.get("roi_profile_id"),
        "capture_binding_verified": report.get("capture_binding_verified") is True,
    }
    return overlay


def create_cpu_engine() -> Any:
    """Create RapidOCR with detection/classification/GPU paths disabled."""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise RapidOcrFixedRoiError(
            "rapidocr_onnxruntime is required for the optional CPU OCR backend"
        ) from exc
    try:
        engine = RapidOCR(use_cuda=False, use_dml=False, use_det=False, use_cls=False)
        providers = set(engine.text_rec.session.session.get_providers())
    except Exception as exc:  # pragma: no cover - model/runtime-dependent
        raise RapidOcrFixedRoiError(f"could not initialize RapidOCR CPU engine: {exc}") from exc
    if providers != {"CPUExecutionProvider"}:
        raise RapidOcrFixedRoiError(
            f"RapidOCR provider contract requires CPUExecutionProvider only; got {sorted(providers)}"
        )
    if hasattr(cv2, "ocl"):
        cv2.ocl.setUseOpenCL(False)
    return engine


def recognize_crop(engine: Any, crop: Any, *, scale: int = 12) -> tuple[str, float | None]:
    """Recognize one known single-line crop without running text detection."""
    if scale < 1:
        raise RapidOcrFixedRoiError("scale must be positive")
    scaled = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    result, _timing = engine(scaled)
    if not result:
        return "", None
    item = result[0]
    if not isinstance(item, (list, tuple)) or len(item) < 2:
        return "", None
    try:
        return str(item[0]).strip(), float(item[1])
    except (TypeError, ValueError):
        return str(item[0]).strip(), None


class RapidOcrFixedRoiBackend:
    """Produce provenance-bound candidate labels from a persisted frame."""

    def __init__(
        self,
        *,
        profile: CpuRoiProfile | None = None,
        labels: Iterable[RapidOcrLabelSpec] = DEFAULT_LABELS,
        scale: int = 12,
    ) -> None:
        self.profile = profile or load_default_cpu_roi_profile()
        self.labels = tuple(labels)
        if not self.labels:
            raise RapidOcrFixedRoiError("at least one fixed ROI label is required")
        self.scale = scale
        self.engine = create_cpu_engine()
        self.providers = ("CPUExecutionProvider",)

    def recognize_image(
        self,
        image: str | Path,
        *,
        frame_id: str | None = None,
        expected_sha256: str | None = None,
    ) -> dict[str, Any]:
        path = Path(image).resolve()
        if not path.is_file():
            raise RapidOcrFixedRoiError(f"image does not exist: {path}")
        digest = image_sha256(path)
        if expected_sha256 is not None and digest != expected_sha256:
            raise RapidOcrFixedRoiError("image hash does not match capture evidence")
        frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if frame is None:
            raise RapidOcrFixedRoiError(f"could not decode image: {path}")
        height, width = int(frame.shape[0]), int(frame.shape[1])
        results: list[dict[str, Any]] = []
        for spec in self.labels:
            crop, resolved = self.profile.crop(frame, spec.roi_id)
            started = time.perf_counter()
            text, score = recognize_crop(self.engine, crop, scale=self.scale)
            latency_ms = (time.perf_counter() - started) * 1000.0
            results.append(self._result(spec, resolved, text, score, latency_ms, digest, frame_id))
        return {
            "schema_version": 1,
            "status": "experiment_only",
            "measurement_class": "rapidocr_cpu_fixed_roi_recognition",
            "processing_device": "cpu",
            "onnxruntime_providers": list(self.providers),
            "detector": "disabled_fixed_roi",
            "backend": {
                "name": "RapidOCR.fixed_roi",
                "version": "rapidocr_onnxruntime-1.4.4",
                "device": "cpu",
                "providers": list(self.providers),
            },
            "input_emitted": False,
            "image": str(path),
            "image_sha256": digest,
            "frame_id": frame_id,
            "client_size": [width, height],
            "roi_profile_id": self.profile.profile_id,
            "results": results,
        }

    @staticmethod
    def _result(
        spec: RapidOcrLabelSpec,
        resolved: ResolvedRoi,
        text: str,
        score: float | None,
        latency_ms: float,
        digest: str,
        frame_id: str | None,
    ) -> dict[str, Any]:
        rect = resolved.rect
        return {
            "label": spec.label,
            "roi_id": spec.roi_id,
            "rect": rect.as_list(),
            "text": text,
            "score": score,
            "latency_ms": round(latency_ms, 3),
            "normalized_expected": normalize_text(spec.label),
            "normalized_actual": normalize_text(text),
            "exact": normalize_text(spec.label) == normalize_text(text),
            "source": "rapidocr_fixed_roi",
            "grounding_authority": "ocr_backend",
            "confidence_known": score is not None,
            "frame_id": frame_id,
            "image_sha256": digest,
            "input_emitted": False,
        }
