"""Screen fixed resource-label OCR across the persisted CPU corpus.

The corpus is observation-only.  This comparator uses RapidOCR's
recognizer-only mode on the existing fixed label ROIs and forces ONNX Runtime
to CPU.  It is not the runtime acceptance path: labels remain provisional and
the report cannot replace independent label review.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import time
from typing import Any

import cv2
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.cpu_roi import load_default_cpu_roi_profile
from harness.rapidocr_fixed_roi import (
    DEFAULT_LABELS,
    create_cpu_engine,
    image_sha256,
    normalize_text,
    recognize_crop,
)
VARIANTS = ("raw", "gray")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _variant(crop: Any, name: str) -> Any:
    if name == "raw":
        return crop
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    if name == "gray":
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    raise ValueError(f"unknown variant: {name}")


def _capture_binding(image: Path) -> tuple[str | None, str | None, bool]:
    capture_path = image.parent / "capture.json"
    if not capture_path.is_file():
        return None, None, False
    try:
        capture = json.loads(capture_path.read_text(encoding="utf-8"))
        frame = capture.get("frame", {})
        frame_id = frame.get("id")
        expected_hash = frame.get("image_sha256")
        if not isinstance(frame_id, str) or not isinstance(expected_hash, str):
            return None, str(capture_path), False
        return frame_id, str(capture_path), expected_hash == image_sha256(image)
    except (OSError, json.JSONDecodeError):
        return None, str(capture_path), False


def main() -> int:
    args = _parse_args()
    manifest = args.manifest.resolve()
    if not manifest.is_file():
        raise SystemExit(f"manifest does not exist: {manifest}")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    entries = payload.get("results", [])
    image_paths: list[Path] = []
    seen: set[str] = set()
    for entry in entries:
        if entry.get("expected_state") != "RESOURCE_SEARCH_PANEL":
            continue
        source = entry.get("source", {})
        candidate = source.get("image")
        if not candidate:
            continue
        image = Path(candidate).resolve()
        key = str(image).casefold()
        if key not in seen:
            seen.add(key)
            image_paths.append(image)
    if not image_paths:
        raise SystemExit("manifest has no RESOURCE_SEARCH_PANEL source images")

    # The product target is CPU/RAM only.  Detector and classifier are not
    # needed for a known single-line fixed ROI.
    profile = load_default_cpu_roi_profile()
    ocr = create_cpu_engine()
    providers = ["CPUExecutionProvider"]
    results: list[dict[str, Any]] = []
    for image in image_paths:
        if not image.is_file():
            results.append({"image": str(image), "status": "missing"})
            continue
        frame = cv2.imread(str(image), cv2.IMREAD_COLOR)
        if frame is None:
            results.append({"image": str(image), "status": "decode_error"})
            continue
        frame_id, capture_path, capture_verified = _capture_binding(image)
        image_digest = image_sha256(image)
        for spec in DEFAULT_LABELS:
            crop, resolved = profile.crop(frame, spec.roi_id)
            for variant_name in VARIANTS:
                started = time.perf_counter()
                text, score = recognize_crop(ocr, _variant(crop, variant_name))
                latency_ms = (time.perf_counter() - started) * 1000.0
                results.append(
                    {
                        "image": str(image),
                        "image_sha256": image_digest,
                        "frame_id": frame_id,
                        "capture_path": capture_path,
                        "capture_binding_verified": capture_verified,
                        "label": spec.label,
                        "roi_id": spec.roi_id,
                        "rect": resolved.rect.as_list(),
                        "variant": variant_name,
                        "text": text,
                        "score": score,
                        "latency_ms": round(latency_ms, 3),
                        "normalized_expected": normalize_text(spec.label),
                        "normalized_actual": normalize_text(text),
                        "exact": normalize_text(spec.label) == normalize_text(text),
                        "source": "rapidocr_fixed_roi",
                        "grounding_authority": "ocr_backend",
                        "confidence_known": score is not None,
                        "input_emitted": False,
                    }
                )

    valid = [item for item in results if "exact" in item]
    exact = sum(1 for item in valid if item["exact"])
    latencies = [float(item["latency_ms"]) for item in valid if item.get("latency_ms") is not None]
    by_variant = {}
    for variant in VARIANTS:
        subset = [item for item in valid if item["variant"] == variant]
        by_variant[variant] = {
            "sample_count": len(subset),
            "exact_count": sum(1 for item in subset if item["exact"]),
            "exact_rate": (
                sum(1 for item in subset if item["exact"]) / len(subset) if subset else None
            ),
        }
    report = {
        "schema_version": 1,
        "status": "experiment_only",
        "measurement_class": "rapidocr_cpu_fixed_roi_recognition_corpus_screening",
        "manifest": str(manifest),
        "manifest_sha256": image_sha256(manifest),
        "processing_device": "cpu",
        "onnxruntime_providers": providers,
        "detector": "disabled_fixed_roi",
        "input_emitted": False,
        "image_count": len(image_paths),
        "label_count": len(DEFAULT_LABELS),
        "roi_profile_id": profile.profile_id,
        "variants": list(VARIANTS),
        "sample_count": len(valid),
        "exact_count": exact,
        "exact_rate": exact / len(valid) if valid else None,
        "latency_ms": {
            "sample_count": len(latencies),
            "median": round(statistics.median(latencies), 3) if latencies else None,
            "p95": round(statistics.quantiles(latencies, n=20, method="inclusive")[18], 3)
            if len(latencies) >= 2
            else (round(latencies[0], 3) if latencies else None),
        },
        "by_variant": by_variant,
        "results": results,
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
