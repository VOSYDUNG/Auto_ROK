"""Teach the march-queue reader a digit it has not seen, from a known frame.

The queue reader matches glyph bitmaps and refuses anything it does not
recognise. That is the correct behaviour - ``harness/queue_indicator.py``
says so - but it means the profile has to GROW as the queue takes values it
has never displayed. It shipped knowing 1, / and 5 because that is all the
training frame contained; the first time a second march went out it returned
UNKNOWN_GLYPH on a perfectly legible "2/5".

This is the deliberate act that adds one. docs/DESIGN_BRIEF.md D1b forbids a
sensor training itself on frames it read wrong, and this does not: the caller
states what the indicator actually says, the script checks the frame agrees
in shape, and only then writes. A frame plus a human-supplied ground truth is
calibration; a frame alone is self-deception.

    python scripts/train_queue_glyph.py --frame <png> --value 2/5

It refuses to overwrite a glyph the profile already knows unless --replace is
given, so a mislabelled run cannot quietly corrupt a working digit.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.queue_indicator import (  # noqa: E402
    QueueIndicatorProfile,
    QueueIndicatorReader,
)

PROFILE = ROOT / "config" / "queue_indicator_profile.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", required=True, help="a captured 1366x768 client frame")
    parser.add_argument(
        "--value",
        required=True,
        help='what the indicator actually reads, e.g. "2/5" - the operator states this',
    )
    parser.add_argument("--replace", action="store_true", help="allow overwriting a known glyph")
    parser.add_argument("--profile", default=str(PROFILE))
    args = parser.parse_args(argv)

    import cv2

    used, _, capacity = args.value.partition("/")
    if not used.isdigit() or not capacity.isdigit():
        print(f"--value must look like 2/5, got {args.value!r}", file=sys.stderr)
        return 2
    labels = [used, "/", capacity]

    profile_path = Path(args.profile)
    raw = json.loads(profile_path.read_text(encoding="utf-8"))
    profile = QueueIndicatorProfile.from_mapping(raw)

    image = cv2.imread(str(Path(args.frame)))
    if image is None:
        print(f"could not decode {args.frame}", file=sys.stderr)
        return 2
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    x, y, width, height = profile.roi
    mask = (grey[y : y + height, x : x + width] >= profile.threshold).astype("uint8")
    boxes = QueueIndicatorReader(profile)._segment(mask, origin=(x, y))
    if len(boxes) != len(labels):
        print(
            f"the region segmented {len(boxes)} glyphs but {args.value!r} has "
            f"{len(labels)}; the frame and the stated value disagree, so "
            "nothing was written",
            file=sys.stderr,
        )
        return 3

    glyphs = dict(raw.get("glyphs") or {})
    added: list[str] = []
    for label, box in zip(labels, boxes):
        pattern = list(box.pattern)
        known = glyphs.get(label)
        if known is not None and list(known) != pattern and not args.replace:
            print(
                f"glyph {label!r} is already trained with a different shape; "
                "pass --replace only if you are sure the old one was wrong",
                file=sys.stderr,
            )
            return 4
        if known is None or list(known) != pattern:
            glyphs[label] = pattern
            added.append(f"{label} ({box.width}x{box.height})")

    if not added:
        print(f"{args.value} already reads correctly; nothing to add")
        return 0

    raw["glyphs"] = glyphs
    trained = dict(raw.get("trained_from") or {})
    trained[args.value] = Path(args.frame).name
    raw["trained_from"] = trained
    profile_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")

    reading = QueueIndicatorReader(QueueIndicatorProfile.from_mapping(raw)).read(grey)
    print(f"added: {', '.join(added)}")
    print(f"the frame now reads: {reading.status.value} {reading.used}/{reading.capacity}")
    return 0 if f"{reading.used}/{reading.capacity}" == args.value else 5


if __name__ == "__main__":
    raise SystemExit(main())
