"""Run an offline Tesseract CPU OCR experiment on persisted ROK frames.

This script is deliberately not part of the runtime OCR path.  It compares
bounded label crops and preprocessing variants, records the original image
hash, and never opens the game or emits input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

import cv2


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
LABELS = (
    ("Barbarians", (350, 732, 105, 24)),
    ("Cropland", (500, 732, 105, 24)),
    ("Logging Camp", (625, 732, 125, 24)),
    ("Stone Deposit", (770, 732, 135, 24)),
    ("Gold Deposit", (915, 732, 140, 24)),
)
VARIANTS = ("raw", "gray", "otsu", "adaptive", "bright_text")
PSMS = (6, 7, 11, 13)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--tesseract", type=Path, default=DEFAULT_TESSERACT)
    parser.add_argument("--user-words", type=Path)
    return parser.parse_args()


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


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
        # The labels are light text over a dark, textured panel.  Keep bright
        # pixels and the warm icon/text range, without using any game state.
        b, g, r = cv2.split(crop)
        mask = ((gray >= 120) | ((r >= 150) & (g >= 110) & (b <= 150))).astype("uint8") * 255
        return cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    raise ValueError(f"unknown variant: {name}")


def _ocr(executable: Path, image: Path, psm: int, user_words: Path | None = None) -> tuple[str, str]:
    command = [str(executable), str(image), "stdout", "--psm", str(psm), "--oem", "1", "-l", "eng"]
    if user_words is not None:
        command.extend(["--user-words", str(user_words)])
    completed = subprocess.run(command, capture_output=True, check=False)
    stdout = completed.stdout.decode("utf-8", errors="replace") if completed.stdout else ""
    stderr = completed.stderr.decode("utf-8", errors="replace") if completed.stderr else ""
    return stdout.strip(), stderr.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    args = _parse_args()
    image = args.image.resolve()
    executable = args.tesseract.resolve()
    if not image.is_file():
        raise SystemExit(f"image does not exist: {image}")
    if not executable.is_file():
        raise SystemExit(f"tesseract executable does not exist: {executable}")
    user_words = args.user_words.resolve() if args.user_words else None
    if user_words is not None and not user_words.is_file():
        raise SystemExit(f"user-words file does not exist: {user_words}")
    frame = cv2.imread(str(image), cv2.IMREAD_COLOR)
    if frame is None:
        raise SystemExit(f"could not decode image: {image}")

    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="autorok-tesseract-") as temp_dir:
        temp_root = Path(temp_dir)
        for label, (x, y, width, height) in LABELS:
            crop = frame[y : y + height, x : x + width]
            if crop.size == 0:
                continue
            for variant_name in VARIANTS:
                processed = _variant(crop, variant_name)
                for psm in PSMS:
                    scaled = cv2.resize(processed, None, fx=12, fy=12, interpolation=cv2.INTER_CUBIC)
                    candidate = temp_root / f"{_normalize(label)}-{variant_name}-{psm}.png"
                    if not cv2.imwrite(str(candidate), scaled):
                        raise SystemExit(f"could not write temporary crop: {candidate}")
                    text, stderr = _ocr(executable, candidate, psm, user_words)
                    results.append(
                        {
                            "label": label,
                            "variant": variant_name,
                            "psm": psm,
                            "text": text,
                            "normalized_expected": _normalize(label),
                            "normalized_actual": _normalize(text),
                            "exact": _normalize(text) == _normalize(label),
                            "stderr": stderr[-500:] if stderr else None,
                        }
                    )

    exact = sum(1 for item in results if item["exact"])
    report = {
        "schema_version": 1,
        "status": "experiment_only",
        "measurement_class": "tesseract_cpu_label_crop_screening",
        "processing_device": "cpu",
        "input_emitted": False,
        "image": str(image),
        "image_sha256": _sha256(image),
        "tesseract": str(executable),
        "user_words": str(user_words) if user_words else None,
        "labels": len(LABELS),
        "variants": list(VARIANTS),
        "psms": list(PSMS),
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
