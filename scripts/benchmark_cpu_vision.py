"""Benchmark the CPU-only main-view signature without touching the game.

This is an offline/read-only benchmark over captured PNGs.  It intentionally
does not capture a window, call OCR, start a model, or emit input.  Use it to
separate the cheap native OpenCV feature step from the slower acquisition/OCR
stages before deciding whether a C/C++ replacement is warranted.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import time
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.cpu_roi import CpuRoiProfile  # noqa: E402
from harness.main_view_detector import (  # noqa: E402
    MainViewProfile,
    classify_signature,
    extract_visual_signature,
)


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * quantile)))
    return ordered[index]


def benchmark_image(path: Path, profile: MainViewProfile, roi_profile: CpuRoiProfile, iterations: int) -> dict[str, object]:
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - dependency contract
        raise RuntimeError("OpenCV is required for the CPU benchmark") from exc

    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None or image.ndim != 3:
        raise ValueError(f"cannot decode image: {path}")
    height, width = image.shape[:2]
    roi = roi_profile.describe("signature_canvas", (width, height))
    samples: list[float] = []
    match = None
    for _ in range(iterations):
        started = time.perf_counter()
        vector = extract_visual_signature(path, roi_profile=roi_profile)
        match = classify_signature(vector, profile)
        samples.append((time.perf_counter() - started) * 1000.0)
    return {
        "path": str(path),
        "size": [width, height],
        "roi": roi,
        "iterations": iterations,
        "median_ms": statistics.median(samples),
        "p95_ms": _percentile(samples, 0.95),
        "samples_ms": samples,
        "match": {
            "state_id": match.state_id if match else None,
            "best_distance": match.best_distance if match else None,
            "second_distance": match.second_distance if match else None,
            "reason": match.reason if match else None,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument(
        "--profile",
        type=Path,
        default=ROOT / "config" / "main_view_profiles.json",
    )
    parser.add_argument(
        "--roi-profile",
        type=Path,
        default=ROOT / "config" / "cpu_rois.yaml",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="optional evidence JSON path under workspace/evidence/cpu",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.iterations < 1 or args.iterations > 100:
        raise SystemExit("iterations must be within 1..100")
    profile = MainViewProfile.load(args.profile)
    roi_profile = CpuRoiProfile.load(args.roi_profile)
    results = [benchmark_image(path.resolve(), profile, roi_profile, args.iterations) for path in args.images]
    try:
        import cv2

        opencl_enabled = bool(cv2.ocl.useOpenCL()) if hasattr(cv2, "ocl") else False
        cuda_devices = int(cv2.cuda.getCudaEnabledDeviceCount()) if hasattr(cv2, "cuda") else 0
        opencv_version = cv2.__version__
    except ImportError:  # pragma: no cover - handled above in benchmark_image
        opencl_enabled, cuda_devices, opencv_version = False, 0, None
    payload = {
        "schema_version": 1,
        "status": "pass",
        "processing_device": "cpu",
        "opencl_enabled": opencl_enabled,
        "cuda_devices_visible": cuda_devices,
        "opencv_version": opencv_version,
        "ocr_included": False,
        "capture_included": False,
        "input_emitted": False,
        "results": results,
    }
    if args.output is not None:
        output = args.output.resolve()
        if not output.is_relative_to((ROOT / "workspace" / "evidence" / "cpu").resolve()):
            raise SystemExit("output must stay under workspace/evidence/cpu")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(output.name + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
