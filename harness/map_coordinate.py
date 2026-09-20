"""Is the world-map coordinate readout on screen?

The client draws "#1296 X:1065 Y:587" in the top-left corner, and only there,
and only on the bare world map. Open the search panel and the widget is
replaced by a back arrow. Switch to the city and it is gone. So its presence
means more than "this is the world map": it means "the world map, with
nothing on top of it".

WHY THIS EXISTS. ``main_view_detector`` decides CITY_VIEW vs WORLD_MAP_VIEW by
comparing a low-resolution signature of the whole canvas against a trained
prototype. That works for the city, which always looks like itself. It cannot
work for the world map, which looks different everywhere you pan. Measured
2026-09-20 on real frames: the city matches its prototype at distance 0.0001,
while every world-map frame lands at 0.15 to 0.22 against a 0.08 threshold.
Not a threshold to widen - widening it to 0.22 would swallow the city too.
One prototype cannot represent open terrain, so a second signal carries the
state instead.

WHY NOT OCR. The obvious approach is to read the coordinates and check they
parsed. It was tried and it does not hold up, because the client has a DAY AND
NIGHT CYCLE. Measured on two frames of the same view minutes apart, the ROI's
mean brightness went 117.6 to 74.6, and no single scale read both: scale 2
read the day frame and failed at night, scale 1.5 did the reverse. Grayscale,
min-max stretch, Otsu, CLAHE and fixed binarisation were each tried at four
scales; none read every frame.

That was the wrong question. The classifier does not need the numbers, it
needs to know the widget is THERE, and presence is a shape question - the same
reason ``queue_indicator`` matches templates instead of asking OCR for a
number it never returns.

What this measures instead is how many columns of the region contain a pixel
clearly brighter than the region's own median. Using the median makes it
lighting-invariant: the text stays bright relative to its local background
whether that background is noon grass or midnight water. Measured:

    day world map        121 columns      median 115
    night world map      132 columns      median  54
    daylight, panned      80 columns      median 151
    city view              2 columns
    search panel open      0 columns
    troop panel open       0 columns

80 against 2 is a margin wide enough that the uncertain band between the
thresholds costs nothing, and readings that land in it are refused rather than
rounded - per docs/DESIGN_BRIEF.md D1b.

The coordinate VALUES are still worth having for navigation later.
``read_values`` does that with OCR, and is explicitly not what the classifier
depends on.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Sequence

#: The ROI id this sensor reads, calibrated in config/cpu_rois.yaml.
ROI_ID = "map_coordinate_readout"

#: Emitted so the state classifier can name what was actually observed,
#: rather than borrowing the visual detector's phrases and claiming to have
#: checked the HUD and the navigation bar when it only looked at one corner.
COORDINATE_EVIDENCE = "world-map coordinate readout is visible"

#: How far above the region's own median a pixel must be to count as text.
#: Against the median rather than an absolute level, so the day/night cycle
#: moves the baseline and the measurement does not move with it.
BRIGHT_MARGIN = 60

#: Columns containing text. The observed gap is 80 versus 2, so these sit far
#: from both sides on purpose and the band between them is wide.
PRESENT_ABOVE = 40
ABSENT_BELOW = 10


class MapCoordinateError(ValueError):
    """Raised when the region cannot be examined at all."""


class CoordinateStatus(str, Enum):
    #: The widget is there: the bare world map, nothing over it.
    PRESENT = "PRESENT"
    #: The region is empty. The correct answer for the city view and for any
    #: frame with a panel open, so it is information rather than a failure.
    ABSENT = "ABSENT"
    #: Between the thresholds. Refused rather than rounded to the nearer
    #: answer, because forcing a verdict there is a guess in a measurement's
    #: clothing.
    UNCERTAIN = "UNCERTAIN"
    #: The frame could not be read at all.
    UNREADABLE = "UNREADABLE"


@dataclass(frozen=True)
class MapCoordinateReading:
    status: CoordinateStatus
    text_columns: int = 0
    reason: str = ""

    @property
    def on_bare_world_map(self) -> bool:
        """True only on a confident PRESENT.

        Deliberately not ``status is not ABSENT`` - an UNCERTAIN or UNREADABLE
        region must not be quietly counted as evidence of the world map.
        """
        return self.status is CoordinateStatus.PRESENT


def text_columns(patch: Any, *, margin: int = BRIGHT_MARGIN) -> int:
    """Columns of the region holding a pixel brighter than its own median."""
    import numpy as np  # noqa: PLC0415

    array = np.asarray(patch)
    if array.ndim == 3:
        import cv2  # noqa: PLC0415

        array = cv2.cvtColor(array, cv2.COLOR_BGR2GRAY)
    if array.ndim != 2 or array.size == 0:
        raise MapCoordinateError("expected a non-empty single-channel region")
    values = array.astype(np.int16)
    bright = values > (int(np.median(values)) + margin)
    return int((bright.any(axis=0)).sum())


def classify_columns(
    columns: int,
    *,
    present_above: int = PRESENT_ABOVE,
    absent_below: int = ABSENT_BELOW,
) -> MapCoordinateReading:
    if absent_below >= present_above:
        raise MapCoordinateError(
            "absent_below must be under present_above; an empty or inverted "
            "band would remove the refusal case"
        )
    if columns >= present_above:
        return MapCoordinateReading(
            CoordinateStatus.PRESENT,
            columns,
            "the coordinate widget is drawn; this is the bare world map",
        )
    if columns <= absent_below:
        return MapCoordinateReading(
            CoordinateStatus.ABSENT,
            columns,
            "the readout region is empty; the client hides this widget in the "
            "city view and behind every open panel",
        )
    return MapCoordinateReading(
        CoordinateStatus.UNCERTAIN,
        columns,
        f"{columns} text columns falls between absent ({absent_below}) and "
        f"present ({present_above}); observe another frame rather than guessing",
    )


class MapCoordinateReader:
    """Decide from one calibrated corner whether the widget is drawn."""

    def __init__(
        self,
        *,
        roi: tuple[int, int, int, int],
        scale: float = 1.0,
        margin: int = BRIGHT_MARGIN,
        present_above: int = PRESENT_ABOVE,
        absent_below: int = ABSENT_BELOW,
        loader: Callable[[Path], Any] | None = None,
    ) -> None:
        if len(roi) != 4 or roi[2] <= 0 or roi[3] <= 0:
            raise MapCoordinateError("roi must be (x, y, positive width, positive height)")
        if not 0 < margin < 255:
            raise MapCoordinateError("margin must be in 1..254")
        if absent_below >= present_above:
            raise MapCoordinateError("absent_below must be under present_above")
        self.roi = (int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3]))
        #: Kept only so ``read_values`` can use the calibrated OCR scale. The
        #: presence decision does no scaling at all - it counts columns of the
        #: native pixels, and resampling them would invent some.
        self.scale = float(scale)
        self.margin = int(margin)
        self.present_above = int(present_above)
        self.absent_below = int(absent_below)
        self._load = loader or _load_bgr

    def read(self, image: str | Path) -> MapCoordinateReading:
        path = Path(image)
        if not path.exists():
            return MapCoordinateReading(
                CoordinateStatus.UNREADABLE, reason=f"no frame at {path}"
            )
        try:
            frame = self._load(path)
            x, y, width, height = self.roi
            patch = frame[y : y + height, x : x + width]
            if patch.shape[0] != height or patch.shape[1] != width:
                raise MapCoordinateError(
                    f"roi {self.roi} does not fit inside this frame; a clamped "
                    "region would measure different pixels than the calibration"
                )
            columns = text_columns(patch, margin=self.margin)
        except Exception as exc:  # noqa: BLE001 - a sensor that cannot read says so
            return MapCoordinateReading(
                CoordinateStatus.UNREADABLE, reason=f"{type(exc).__name__}: {exc}"
            )
        return classify_columns(
            columns,
            present_above=self.present_above,
            absent_below=self.absent_below,
        )


def _load_bgr(path: Path) -> Any:
    import cv2  # noqa: PLC0415

    image = cv2.imread(str(path))
    if image is None:
        raise MapCoordinateError(f"could not decode {path}")
    return image


_KINGDOM = re.compile(r"^#(\d{1,6})$")
_X = re.compile(r"^X[:.]?\s*(\d{1,5})$", re.IGNORECASE)
_Y = re.compile(r"^Y[:.]?\s*(\d{1,5})$", re.IGNORECASE)


@dataclass(frozen=True)
class MapPosition:
    kingdom: int | None
    x: int
    y: int


def parse_tokens(tokens: Sequence[str]) -> MapPosition | None:
    """Coordinates from OCR words, or None when they are not all there.

    Used for navigation, never for classification - see the module docstring
    on why the day/night cycle makes OCR the wrong basis for presence.
    """
    kingdom = x = y = None
    for token in tokens:
        text = str(token).strip()
        if (match := _KINGDOM.match(text)) is not None:
            kingdom = int(match.group(1))
        elif (match := _X.match(text)) is not None:
            x = int(match.group(1))
        elif (match := _Y.match(text)) is not None:
            y = int(match.group(1))
    if x is None or y is None:
        return None
    return MapPosition(kingdom, x, y)


def read_values(image: str | Path, roi: tuple[int, int, int, int], scale: float) -> MapPosition | None:
    """OCR the coordinates themselves. Optional, and lighting-sensitive."""
    from harness.windows_ocr_direct import WindowsOcr, recognize_path  # noqa: PLC0415

    payload = recognize_path(
        Path(image), {"frame": {}}, engine=_engine(), roi=roi, scale=scale
    )
    return parse_tokens([str(item["text"]) for item in payload["elements"]])


_CACHED_ENGINE: Any = None


def _engine():
    """One engine per process; creating one costs about 7 ms."""
    global _CACHED_ENGINE  # noqa: PLW0603
    if _CACHED_ENGINE is None:
        from harness.windows_ocr_direct import WindowsOcr  # noqa: PLC0415

        _CACHED_ENGINE = WindowsOcr()
    return _CACHED_ENGINE


def reader_from_profile(
    roi_profile: Any, window_size: tuple[int, int], **kwargs: Any
) -> MapCoordinateReader:
    """Build a reader from the calibrated CPU ROI profile."""
    resolved = roi_profile.resolve(ROI_ID, window_size)
    return MapCoordinateReader(
        roi=tuple(resolved.rect.as_list()),  # type: ignore[arg-type]
        scale=resolved.ocr_scale,
        **kwargs,
    )


__all__ = [
    "ABSENT_BELOW",
    "BRIGHT_MARGIN",
    "COORDINATE_EVIDENCE",
    "PRESENT_ABOVE",
    "ROI_ID",
    "CoordinateStatus",
    "MapCoordinateError",
    "MapCoordinateReader",
    "MapCoordinateReading",
    "MapPosition",
    "classify_columns",
    "parse_tokens",
    "read_values",
    "reader_from_profile",
    "text_columns",
]
