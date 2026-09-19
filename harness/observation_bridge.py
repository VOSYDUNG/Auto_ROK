"""Validate passive window/OCR evidence and project it into harness contracts.

This module is deliberately acquisition-agnostic: capture and OCR backends produce
JSON plus persisted image bytes; this bridge rejects evidence that is not bound to
one current Rise of Kingdoms client frame.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from harness.contracts import BoundingBox, Evidence, Observation
from harness.scene_graph import SceneGraph, VisualTarget


class ObservationBridgeError(ValueError):
    """Capture/OCR evidence is malformed or violates the passive-frame contract."""


@dataclass(frozen=True)
class CandidateSpec:
    target_id: str
    labels: tuple[str, ...]
    min_confidence: float = 0.0


@dataclass(frozen=True)
class ProjectionResult:
    status: str
    reason: str | None
    observation: Observation | None
    scene: SceneGraph | None
    decisions: tuple[Mapping[str, Any], ...] = ()


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise ObservationBridgeError(message)


def _utc(value: Any, label: str) -> datetime:
    _need(isinstance(value, str), f"{label} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ObservationBridgeError(f"{label} is not valid ISO-8601") from exc
    _need(parsed.tzinfo is not None, f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _number(value: Any, label: str, *, low: float | None = None) -> float:
    _need(type(value) in (int, float), f"{label} must be numeric")
    result = float(value)
    _need(result == result and result not in (float("inf"), float("-inf")), f"{label} must be finite")
    if low is not None:
        _need(result >= low, f"{label} must be >= {low}")
    return result


def _rect(value: Any, label: str) -> tuple[int, int, int, int]:
    _need(isinstance(value, list) and len(value) == 4, f"{label} must contain four integers")
    _need(all(type(item) is int for item in value), f"{label} must contain four integers")
    x, y, width, height = value
    _need(x >= 0 and y >= 0 and width > 0 and height > 0, f"{label} has invalid geometry")
    return x, y, width, height


def _validate_specs(specs: Sequence[CandidateSpec]) -> None:
    ids: set[str] = set()
    for spec in specs:
        _need(bool(spec.target_id) and spec.target_id not in ids, "candidate target ids must be unique")
        ids.add(spec.target_id)
        _need(bool(spec.labels) and all(isinstance(label, str) and label.strip() for label in spec.labels),
              f"candidate {spec.target_id!r} needs non-empty labels")
        _need(0.0 <= spec.min_confidence <= 1.0, f"candidate {spec.target_id!r} confidence is invalid")


def project_observation(
    capture: Mapping[str, Any],
    ocr: Mapping[str, Any],
    image_path: str | Path,
    candidates: Sequence[CandidateSpec] = (),
    *,
    now: datetime | None = None,
    max_age_seconds: float = 10.0,
    future_tolerance_seconds: float = 1.0,
    previous_timestamp: float | None = None,
    expected_title: str = "Rise of Kingdoms",
    expected_exe: str = "MASS.exe",
) -> ProjectionResult:
    """Return a frame-bound scene, or NEEDS_DECISION for missing/ambiguous labels.

    Structural or provenance failures raise ``ObservationBridgeError``. Candidate
    absence/ambiguity is valid uncertain perception and therefore returns a
    fail-closed decision result without inventing a target.
    """
    _need(max_age_seconds > 0 and future_tolerance_seconds >= 0, "freshness limits are invalid")
    _validate_specs(candidates)
    _need(capture.get("schema_version") == 1 and capture.get("status") == "captured",
          "capture must be successful schema version 1 evidence")

    backend = capture.get("backend")
    _need(isinstance(backend, Mapping) and isinstance(backend.get("name"), str)
          and bool(backend["name"]) and isinstance(backend.get("version"), str)
          and bool(backend["version"]), "capture backend name/version are required")
    target = capture.get("target")
    _need(isinstance(target, Mapping), "capture target identity is required")
    _need(target.get("title") == expected_title and str(target.get("exe", "")).casefold() == expected_exe.casefold(),
          "capture target identity does not match Rise of Kingdoms/MASS.exe")
    _need(type(target.get("hwnd")) is int and target["hwnd"] > 0 and type(target.get("pid")) is int
          and target["pid"] > 0, "capture target hwnd/pid are required")

    frame = capture.get("frame")
    _need(isinstance(frame, Mapping), "capture frame provenance is required")
    frame_id = frame.get("id")
    digest = frame.get("image_sha256")
    _need(isinstance(frame_id, str) and bool(frame_id), "capture frame id is required")
    _need(isinstance(digest, str) and _SHA256.fullmatch(digest) is not None, "capture image SHA-256 is invalid")
    captured_at = _utc(frame.get("captured_at"), "capture frame time")
    current_raw = now or datetime.now(timezone.utc)
    _need(current_raw.tzinfo is not None, "current time must include a timezone")
    current = current_raw.astimezone(timezone.utc)
    age = (current - captured_at).total_seconds()
    _need(age >= -future_tolerance_seconds, "capture frame is from the future")
    _need(age <= max_age_seconds, "capture frame is stale")
    timestamp = captured_at.timestamp()
    if previous_timestamp is not None:
        _need(timestamp > previous_timestamp, "capture frames are unordered or duplicated")

    width, height = frame.get("width"), frame.get("height")
    _need(type(width) is int and type(height) is int and width > 0 and height > 0, "frame dimensions are invalid")
    bounds = _rect(frame.get("client_bounds"), "capture client bounds")
    _need(bounds == (0, 0, width, height), "capture client bounds do not match frame dimensions")
    dpi_scale = _number(frame.get("dpi_scale"), "capture DPI scale", low=0.25)
    _need(dpi_scale <= 8.0, "capture DPI scale is implausible")

    image = Path(image_path)
    _need(image.is_file(), "persisted frame image is missing")
    persisted_digest = hashlib.sha256(image.read_bytes()).hexdigest()
    _need(persisted_digest == digest, "persisted frame image hash does not match capture evidence")

    _need(ocr.get("schema_version") == 1, "OCR must use schema version 1")
    _need(ocr.get("frame_id") == frame_id and ocr.get("image_sha256") == digest,
          "OCR does not match the captured frame id/hash")
    _need(ocr.get("coordinate_space") == "ocr_crop_pixels", "OCR source coordinates must be ocr_crop_pixels")
    _need(ocr.get("output_coordinate_space") == "client_pixels",
          "OCR output coordinates must map to client_pixels")
    _need(ocr.get("client_bounds") == list(bounds), "OCR client bounds do not match capture evidence")
    _need(_number(ocr.get("dpi_scale"), "OCR DPI scale", low=0.25) == dpi_scale,
          "OCR DPI scale does not match capture evidence")
    ocr_backend = ocr.get("backend")
    _need(isinstance(ocr_backend, Mapping) and bool(ocr_backend.get("name")) and bool(ocr_backend.get("version")),
          "OCR backend name/version are required")
    crop = _rect(ocr.get("crop"), "OCR crop")
    _need(crop[0] + crop[2] <= width and crop[1] + crop[3] <= height, "OCR crop exceeds client bounds")
    scale_x = _number(ocr.get("scale_x"), "OCR scale_x", low=0.000001)
    scale_y = _number(ocr.get("scale_y"), "OCR scale_y", low=0.000001)
    _need(isinstance(ocr.get("text"), str), "OCR raw text is required")
    elements = ocr.get("elements")
    _need(isinstance(elements, list), "OCR elements must be a list")

    evidence: list[Evidence] = []
    normalized: list[tuple[str, BoundingBox, float | None, int]] = []
    metadata_by_index: dict[int, dict[str, Any]] = {}
    crop_x, crop_y, crop_width, crop_height = crop
    for index, item in enumerate(elements):
        _need(isinstance(item, Mapping) and isinstance(item.get("text"), str), f"OCR element {index} text is invalid")
        x, y, box_width, box_height = _rect(item.get("bbox"), f"OCR element {index} bbox")
        _need(x + box_width <= round(crop_width * scale_x)
              and y + box_height <= round(crop_height * scale_y),
              f"OCR element {index} bbox exceeds OCR crop")
        mapped_x1 = crop_x + round(x / scale_x)
        mapped_y1 = crop_y + round(y / scale_y)
        mapped_x2 = crop_x + round((x + box_width) / scale_x)
        mapped_y2 = crop_y + round((y + box_height) / scale_y)
        _need(0 <= mapped_x1 < mapped_x2 <= width and 0 <= mapped_y1 < mapped_y2 <= height,
              f"OCR element {index} mapped bbox exceeds client bounds")
        confidence_raw = item.get("confidence")
        _need(confidence_raw is None or type(confidence_raw) in (int, float),
              f"OCR element {index} confidence must be numeric or null")
        confidence = None if confidence_raw is None else _number(confidence_raw, f"OCR element {index} confidence", low=0.0)
        _need(confidence is None or confidence <= 1.0, f"OCR element {index} confidence exceeds 1")
        bbox = BoundingBox(mapped_x1, mapped_y1, mapped_x2, mapped_y2)
        metadata = {"frame_id": frame_id, "image_sha256": digest, "detector": dict(ocr_backend),
                    "source_coordinate_space": "ocr_crop_pixels", "coordinate_space": "client_pixels",
                    "ocr_element_index": index, "raw_confidence": confidence_raw,
                    "confidence_known": confidence is not None}
        for key in ("acquisition", "grounding_authority", "semantic_excluded"):
            value = item.get(key)
            if key == "semantic_excluded":
                if value is True:
                    metadata[key] = True
            elif isinstance(value, str) and value:
                metadata[key] = value
        metadata_by_index[index] = metadata
        evidence.append(Evidence("ocr", item["text"], confidence or 0.0, bbox, item["text"], metadata))
        normalized.append((item["text"], bbox, confidence, index))

    targets: list[VisualTarget] = []
    decisions: list[Mapping[str, Any]] = []
    for spec in candidates:
        labels = {label.strip().casefold() for label in spec.labels}
        matches = [item for item in normalized if item[0].strip().casefold() in labels
                   and item[2] is not None and item[2] >= spec.min_confidence]
        if len(matches) != 1:
            decisions.append({"target_id": spec.target_id, "status": "NEEDS_DECISION",
                              "reason": "candidate_missing" if not matches else "candidate_ambiguous",
                              "match_count": len(matches)})
            continue
        label, bbox, confidence, index = matches[0]
        target_metadata = {"frame_id": frame_id, "image_sha256": digest,
                           "detector": dict(ocr_backend), "ocr_element_index": index,
                           "calibrated_anchor": False}
        for key in ("acquisition", "grounding_authority", "semantic_excluded"):
            if key in metadata_by_index.get(index, {}):
                target_metadata[key] = metadata_by_index[index][key]
        targets.append(VisualTarget(spec.target_id, frame_id, label, bbox, float(confidence), "ocr",
                                    target_metadata))

    facts = {"image_sha256": digest, "captured_at": captured_at.isoformat(),
             "window": {"title": target["title"], "exe": target["exe"], "hwnd": target["hwnd"], "pid": target["pid"]},
             "client_bounds": list(bounds), "dpi_scale": dpi_scale, "capture_backend": dict(backend),
             "ocr_backend": dict(ocr_backend), "raw_text": ocr["text"]}
    observation = Observation(timestamp, frame_id, (width, height), tuple(evidence))
    scene = SceneGraph(frame_id, None, tuple(targets), facts)
    if decisions:
        return ProjectionResult("NEEDS_DECISION", "one or more requested candidates are missing or ambiguous",
                                observation, scene, tuple(decisions))
    return ProjectionResult("READY", None, observation, scene)
