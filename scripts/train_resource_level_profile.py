"""Create a trained resource-level slider profile from operator-labelled geometry.

This script does not infer the slider. The operator supplies the real client
frame dimensions, slider track bbox and visible level range after training it in
the game UI.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame-width", type=int, required=True)
    parser.add_argument("--frame-height", type=int, required=True)
    parser.add_argument("--track-bbox", nargs=4, type=int, metavar=("X1", "Y1", "X2", "Y2"), required=True)
    parser.add_argument("--min-level", type=int, required=True)
    parser.add_argument("--max-level", type=int, required=True)
    parser.add_argument("--confidence", type=float, default=0.95)
    parser.add_argument("--anchor", action="append", dest="anchors", default=[])
    parser.add_argument("--output", default=str(ROOT / "config" / "resource_level_profile.json"))
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.frame_width <= 0 or args.frame_height <= 0:
        raise SystemExit("frame dimensions must be positive")
    x1, y1, x2, y2 = args.track_bbox
    if not (0 <= x1 < x2 <= args.frame_width and 0 <= y1 < y2 <= args.frame_height):
        raise SystemExit("track-bbox must be inside the labelled client frame")
    if not (0 <= args.min_level < args.max_level <= 30):
        raise SystemExit("level range must satisfy 0 <= min < max <= 30")
    if not 0.0 < args.confidence <= 1.0:
        raise SystemExit("confidence must be within (0, 1]")
    anchors = args.anchors or ["SEARCH", "Cropland"]
    payload = {
        "schema_version": 1,
        "status": "trained",
        "control_mode": "horizontal_discrete_slider",
        "min_level": args.min_level,
        "max_level": args.max_level,
        "track_normalized": [
            x1 / args.frame_width,
            y1 / args.frame_height,
            x2 / args.frame_width,
            y2 / args.frame_height,
        ],
        "confidence": args.confidence,
        "required_anchors": anchors,
        "training_frame_size": [args.frame_width, args.frame_height],
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
