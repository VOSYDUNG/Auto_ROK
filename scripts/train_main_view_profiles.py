"""Build CITY_VIEW/WORLD_MAP_VIEW visual prototypes from labelled real frames."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.main_view_detector import (  # noqa: E402
    CITY_VIEW,
    WORLD_MAP_VIEW,
    cosine_distance,
    extract_visual_signature,
)


def _centroid(vectors):
    size = len(vectors[0])
    values = [sum(vector[i] for vector in vectors) / len(vectors) for i in range(size)]
    norm = sum(value * value for value in values) ** 0.5
    if norm <= 1e-12:
        raise ValueError("prototype centroid is zero")
    return [value / norm for value in values]


def _prototype(state_id, paths, threshold_pad):
    if len(paths) < 2:
        raise ValueError(f"{state_id} requires at least two labelled frames")
    vectors = [extract_visual_signature(path) for path in paths]
    lengths = {len(vector) for vector in vectors}
    if len(lengths) != 1:
        raise ValueError(f"{state_id} signature dimensions disagree")
    center = _centroid(vectors)
    radius = max(cosine_distance(vector, center) for vector in vectors)
    max_distance = min(0.45, max(0.02, radius + threshold_pad))
    return {
        "state_id": state_id,
        "vector": [round(value, 10) for value in center],
        "max_distance": round(max_distance, 6),
        "training_frames": [str(Path(path).resolve()) for path in paths],
        "training_radius": round(radius, 6),
    }


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", nargs="+", required=True, help="2+ labelled CITY_VIEW PNG/JPG frames")
    parser.add_argument("--world", nargs="+", required=True, help="2+ labelled WORLD_MAP_VIEW PNG/JPG frames")
    parser.add_argument("--output", default=str(ROOT / "config" / "main_view_profiles.json"))
    parser.add_argument("--threshold-pad", type=float, default=0.03)
    parser.add_argument("--min-margin", type=float, default=0.08)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not 0.0 <= args.threshold_pad <= 0.25:
        raise SystemExit("threshold-pad must be within [0, 0.25]")
    if not 0.0 <= args.min_margin <= 0.5:
        raise SystemExit("min-margin must be within [0, 0.5]")
    payload = {
        "schema_version": 1,
        "status": "trained",
        "min_margin": args.min_margin,
        "prototypes": [
            _prototype(CITY_VIEW, args.city, args.threshold_pad),
            _prototype(WORLD_MAP_VIEW, args.world, args.threshold_pad),
        ],
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
