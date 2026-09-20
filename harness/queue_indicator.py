"""Read the march-queue indicator from a fixed region of the world map.

Why this is not OCR.  The indicator was measured on 2026-09-20 at roughly
x=1322..1336, y=116..125 - white glyphs about 3x7 pixels on open grass, with
no panel behind them.  Windows OCR does not see it at all in a full-frame
pass, and when the region is cropped and upscaled it returns "115" for "1/5":
it finds the digits and swallows the slash.  Padding the crop made it return
nothing.

A reading of "115" that should be "1/5" is worse than no reading, because the
number it produces is plausible.  So this module does not use OCR.  The
alphabet here is six digits and a slash in one fixed bitmap font at one fixed
size, which is exactly the case template matching solves exactly.

The other reason for a dedicated reader is STA-005.  The same frame contains
"Trade Deal (5/5) Make 5 purchases at the Courier Station", so any code that
searches the frame for an n/5 pattern will read quest progress as a full march
queue - concluding there is nothing to dispatch while four slots sit empty,
and failing silently.  This reader only ever looks inside its ROI.

Unknown glyphs return UNKNOWN_GLYPH rather than a guess.  The profile ships
with the glyphs observed so far, and grows as the queue takes other values;
until then the honest answer is that it cannot tell.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


class QueueIndicatorError(ValueError):
    """Raised when a profile or an image violates the contract."""


class QueueReadStatus(str, Enum):
    READ = "READ"
    NO_TEXT = "NO_TEXT"
    UNKNOWN_GLYPH = "UNKNOWN_GLYPH"
    BAD_SHAPE = "BAD_SHAPE"
    AMBIGUOUS_GLYPH = "AMBIGUOUS_GLYPH"


@dataclass(frozen=True)
class GlyphBox:
    """One segmented glyph, kept for evidence and for training new templates."""

    x: int
    y: int
    width: int
    height: int
    pattern: tuple[str, ...]
    label: str | None = None


@dataclass(frozen=True)
class QueueReading:
    """What the indicator says, or why it could not be read.

    ``used`` and ``capacity`` are None unless ``status`` is READ.  There is no
    partial success: a reader that returns a number it is unsure of is the
    failure this module exists to prevent.
    """

    status: QueueReadStatus
    used: int | None = None
    capacity: int | None = None
    reason: str = ""
    glyphs: tuple[GlyphBox, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status is QueueReadStatus.READ

    @property
    def free_slots(self) -> int | None:
        if not self.ok or self.used is None or self.capacity is None:
            return None
        return self.capacity - self.used


def _pattern_of(mask: np.ndarray) -> tuple[str, ...]:
    return tuple("".join("#" if value else "." for value in row) for row in mask)


def _distance(left: Sequence[str], right: Sequence[str]) -> int | None:
    """Differing pixels, or None when the two shapes are not the same size."""
    if len(left) != len(right):
        return None
    if any(len(a) != len(b) for a, b in zip(left, right)):
        return None
    return sum(
        1
        for row_a, row_b in zip(left, right)
        for a, b in zip(row_a, row_b)
        if a != b
    )


@dataclass(frozen=True)
class QueueIndicatorProfile:
    """A trained ROI plus the glyph bitmaps observed for it."""

    roi: tuple[int, int, int, int]
    threshold: int
    client_size: tuple[int, int]
    #: label -> the accepted bitmaps for it. SEVERAL per label on purpose.
    #: One bitmap per glyph turned out to be too brittle twice over: a single
    #: pixel of antialiasing shrank "/" at threshold 200, and the same "/"
    #: renders slightly differently under the client's night tint. Both are
    #: the same character; neither is wrong. A label is matched if the glyph
    #: is within max_glyph_distance of ANY of its samples.
    glyphs: Mapping[str, tuple[tuple[str, ...], ...]]
    max_glyph_distance: int = 1
    source_frame_id: str | None = None

    def __post_init__(self) -> None:
        x, y, width, height = self.roi
        if width <= 0 or height <= 0 or x < 0 or y < 0:
            raise QueueIndicatorError("roi must be a positive region inside the frame")
        if not 0 < self.threshold < 256:
            raise QueueIndicatorError("threshold must be in 1..255")
        if not self.glyphs:
            raise QueueIndicatorError("a profile with no glyphs can never read anything")
        if self.max_glyph_distance < 0:
            raise QueueIndicatorError("max_glyph_distance must not be negative")

    @classmethod
    def load(cls, path: str | Path) -> "QueueIndicatorProfile":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_mapping(raw)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "QueueIndicatorProfile":
        roi = raw.get("roi") or {}
        try:
            region = (int(roi["x"]), int(roi["y"]), int(roi["width"]), int(roi["height"]))
            size = tuple(int(item) for item in raw["client_size"])
        except (KeyError, TypeError, ValueError) as exc:
            raise QueueIndicatorError(f"malformed queue indicator profile: {exc}") from exc
        if len(size) != 2:
            raise QueueIndicatorError("client_size must be [width, height]")
        glyphs: dict[str, tuple[tuple[str, ...], ...]] = {}
        for label, value in (raw.get("glyphs") or {}).items():
            if not isinstance(value, list) or not value:
                raise QueueIndicatorError(f"glyph {label!r} must be a non-empty list")
            # Accept both shapes: a single bitmap (a list of row strings) as
            # the profile originally shipped, and a list of bitmaps.
            samples = value if isinstance(value[0], list) else [value]
            glyphs[str(label)] = tuple(
                tuple(str(row) for row in sample) for sample in samples
            )
        return cls(
            roi=region,
            threshold=int(raw.get("threshold", 200)),
            client_size=(size[0], size[1]),
            glyphs=glyphs,
            max_glyph_distance=int(raw.get("max_glyph_distance", 1)),
            source_frame_id=raw.get("source_frame_id"),
        )


class QueueIndicatorReader:
    """Segment the ROI into glyphs and match them against the profile."""

    def __init__(self, profile: QueueIndicatorProfile) -> None:
        self.profile = profile

    def read(self, gray: np.ndarray) -> QueueReading:
        if gray.ndim != 2:
            raise QueueIndicatorError("expected a single-channel grayscale frame")
        height, width = gray.shape
        expected_w, expected_h = self.profile.client_size
        if (width, height) != (expected_w, expected_h):
            return QueueReading(
                QueueReadStatus.BAD_SHAPE,
                reason=(
                    f"frame is {width}x{height} but the profile was trained on "
                    f"{expected_w}x{expected_h}; the ROI would point somewhere else"
                ),
            )

        x, y, roi_w, roi_h = self.profile.roi
        patch = gray[y : y + roi_h, x : x + roi_w]
        mask = (patch >= self.profile.threshold).astype(np.uint8)

        boxes = self._segment(mask, origin=(x, y))
        if not boxes:
            return QueueReading(
                QueueReadStatus.NO_TEXT,
                reason="no bright glyphs inside the indicator region",
            )
        if len(boxes) != 3:
            return QueueReading(
                QueueReadStatus.BAD_SHAPE,
                reason=f"expected three glyphs in the form n/N, segmented {len(boxes)}",
                glyphs=boxes,
            )

        labelled: list[GlyphBox] = []
        for box in boxes:
            label, problem = self._classify(box.pattern)
            if problem is not None:
                return QueueReading(
                    problem,
                    reason=(
                        f"glyph at x={box.x} ({box.width}x{box.height}) does not match "
                        f"any trained glyph; the profile knows "
                        f"{sorted(self.profile.glyphs)}"
                    ),
                    glyphs=tuple(labelled) + (box,),
                )
            labelled.append(
                GlyphBox(box.x, box.y, box.width, box.height, box.pattern, label)
            )

        left, middle, right = labelled
        if middle.label != "/":
            return QueueReading(
                QueueReadStatus.BAD_SHAPE,
                reason=f"middle glyph read as {middle.label!r}, expected a separator",
                glyphs=tuple(labelled),
            )
        if not (left.label or "").isdigit() or not (right.label or "").isdigit():
            return QueueReading(
                QueueReadStatus.BAD_SHAPE,
                reason="queue must read as digit, separator, digit",
                glyphs=tuple(labelled),
            )

        used, capacity = int(left.label), int(right.label)
        if used > capacity:
            return QueueReading(
                QueueReadStatus.BAD_SHAPE,
                reason=f"{used}/{capacity} is not a possible queue state",
                glyphs=tuple(labelled),
            )
        return QueueReading(
            QueueReadStatus.READ,
            used=used,
            capacity=capacity,
            glyphs=tuple(labelled),
        )

    def _segment(self, mask: np.ndarray, *, origin: tuple[int, int]) -> tuple[GlyphBox, ...]:
        """Split on empty columns, then crop each glyph to its own ink."""
        columns = mask.sum(axis=0)
        spans: list[tuple[int, int]] = []
        start: int | None = None
        for index, value in enumerate(columns):
            if value and start is None:
                start = index
            elif not value and start is not None:
                spans.append((start, index - 1))
                start = None
        if start is not None:
            spans.append((start, len(columns) - 1))

        boxes: list[GlyphBox] = []
        for first, last in spans:
            block = mask[:, first : last + 1]
            rows = np.where(block.sum(axis=1) > 0)[0]
            if rows.size == 0:
                continue
            tight = block[rows.min() : rows.max() + 1]
            boxes.append(
                GlyphBox(
                    x=origin[0] + first,
                    y=origin[1] + int(rows.min()),
                    width=tight.shape[1],
                    height=tight.shape[0],
                    pattern=_pattern_of(tight),
                )
            )
        return tuple(boxes)

    def _classify(
        self, pattern: Sequence[str]
    ) -> tuple[str | None, QueueReadStatus | None]:
        """Nearest trained glyph, or a refusal.

        A tie between two templates is refused rather than broken arbitrarily:
        picking one would be a guess dressed as a reading.
        """
        best: list[tuple[int, str]] = []
        for label, samples in self.profile.glyphs.items():
            # Closest sample for this label; a label with three renderings is
            # not three votes, it is one character with three faces.
            distances = [
                distance
                for sample in samples
                if (distance := _distance(pattern, sample)) is not None
                and distance <= self.profile.max_glyph_distance
            ]
            if distances:
                best.append((min(distances), label))
        if not best:
            return None, QueueReadStatus.UNKNOWN_GLYPH
        best.sort()
        if len(best) > 1 and best[0][0] == best[1][0]:
            return None, QueueReadStatus.AMBIGUOUS_GLYPH
        return best[0][1], None


def train_glyph(gray: np.ndarray, profile: QueueIndicatorProfile, index: int) -> tuple[str, ...]:
    """Return the bitmap of one segmented glyph, for adding to a profile.

    Training stays a deliberate operator step: the reader never adds a glyph
    to its own profile from a frame it could not read.
    """
    reader = QueueIndicatorReader(profile)
    x, y, roi_w, roi_h = profile.roi
    patch = gray[y : y + roi_h, x : x + roi_w]
    mask = (patch >= profile.threshold).astype(np.uint8)
    boxes = reader._segment(mask, origin=(x, y))
    if not 0 <= index < len(boxes):
        raise QueueIndicatorError(f"glyph {index} not present; segmented {len(boxes)}")
    return boxes[index].pattern
