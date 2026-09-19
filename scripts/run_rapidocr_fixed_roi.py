"""Run the optional CPU fixed-ROI OCR adapter against one persisted capture.

This command is observation-only and experiment-only.  It requires a
successful ROK capture metadata file, binds the image hash/frame id, and
never activates a window or emits input.  The production Windows OCR bridge
is not changed by this command.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.rapidocr_fixed_roi import RapidOcrFixedRoiBackend, RapidOcrFixedRoiError


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    image = args.image.resolve()
    capture_path = args.capture.resolve()
    output = args.output.resolve()
    if not image.is_file() or not capture_path.is_file():
        raise SystemExit("image and capture metadata must exist")
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    if (
        capture.get("status") != "captured"
        or capture.get("target", {}).get("title") != "Rise of Kingdoms"
        or capture.get("target", {}).get("exe") != "MASS.exe"
    ):
        raise SystemExit("capture metadata is not successful Rise of Kingdoms/MASS.exe evidence")
    frame = capture.get("frame", {})
    frame_id = frame.get("id")
    expected_hash = frame.get("image_sha256")
    if not isinstance(frame_id, str) or not isinstance(expected_hash, str):
        raise SystemExit("capture metadata lacks frame id/image hash")

    try:
        backend = RapidOcrFixedRoiBackend()
        report = backend.recognize_image(
            image,
            frame_id=frame_id,
            expected_sha256=expected_hash,
        )
    except RapidOcrFixedRoiError as exc:
        raise SystemExit(str(exc)) from exc
    report.update(
        {
            "capture_path": str(capture_path),
            "capture_binding_verified": True,
            "input_emitted": False,
        }
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
