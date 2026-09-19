"""Run an offline RapidOCR CPU experiment on persisted ROK frames.

This is an experiment-only comparator for the fixed resource-label crops.  It
forces ONNX Runtime's CPU execution provider, records the source image hash,
and never opens the game or emits keyboard/mouse input.  RapidOCR may split a
label into several tokens; tokens are joined in left-to-right box order for a
bounded exact-match measurement.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
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
VARIANTS = ("raw", "gray", "otsu", "adaptive", "bright_text")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _variant(crop: Any, name: str) -> Any:
    if name == "raw":
        return crop
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    if name == "gray":
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    if name == "otsu":
        _, result = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return cv2.cvtColor(result, cv2.COLOR_GRAY2BGR)
    if name == "adaptive":
        result = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            11,
            2,
        )
        return cv2.cvtColor(result, cv2.COLOR_GRAY2BGR)
    if name == "bright_text":
        b, g, r = cv2.split(crop)
        mask = ((gray >= 120) | ((r >= 150) & (g >= 110) & (b <= 150))).astype("uint8") * 255
        return cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    raise ValueError(f"unknown variant: {name}")


def main() -> int:
    args = _parse_args()
    image = args.image.resolve()
    if not image.is_file():
        raise SystemExit(f"image does not exist: {image}")
    frame = cv2.imread(str(image), cv2.IMREAD_COLOR)
    if frame is None:
        raise SystemExit(f"could not decode image: {image}")

    # Explicitly disable CUDA/DirectML.  The product target is CPU/RAM only.
    profile = load_default_cpu_roi_profile()
    ocr = create_cpu_engine()
    providers = ["CPUExecutionProvider"]
    results: list[dict[str, Any]] = []
    for spec in DEFAULT_LABELS:
        crop, resolved = profile.crop(frame, spec.roi_id)
        for variant_name in VARIANTS:
            processed = _variant(crop, variant_name)
            started = time.perf_counter()
            text, score = recognize_crop(ocr, processed)
            latency_ms = (time.perf_counter() - started) * 1000.0
            results.append(
                {
                    "label": spec.label,
                    "roi_id": spec.roi_id,
                    "rect": resolved.rect.as_list(),
                    "variant": variant_name,
                    "text": text,
                    "score": score,
                    "latency_ms": round(latency_ms, 3),
                    "normalized_expected": normalize_text(spec.label),
                    "normalized_actual": normalize_text(text),
                    "exact": normalize_text(text) == normalize_text(spec.label),
                    "source": "rapidocr_fixed_roi",
                    "grounding_authority": "ocr_backend",
                    "confidence_known": score is not None,
                    "input_emitted": False,
                }
            )

    exact = sum(1 for item in results if item["exact"])
    report = {
        "schema_version": 1,
        "status": "experiment_only",
        "measurement_class": "rapidocr_cpu_fixed_roi_recognition_screening",
        "detector": "disabled_fixed_roi",
        "processing_device": "cpu",
        "onnxruntime_providers": providers,
        "input_emitted": False,
        "image": str(image),
        "image_sha256": image_sha256(image),
        "labels": len(DEFAULT_LABELS),
        "roi_profile_id": profile.profile_id,
        "variants": list(VARIANTS),
        "sample_count": len(results),
        "exact_count": exact,
        "exact_rate": exact / len(results) if results else None,
        "results": results,
    }
    output = args.output.resolve() if args.output else None
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
