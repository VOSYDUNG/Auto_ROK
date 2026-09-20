"""Did the world view move, or did the client ignore the search?

The operator's description of scarcity: "bấm tìm kiếm mà nó không di chuyển
hoặc đưa chúng ta tới mỏ để bấm, thường nó sẽ đứng yên". On success the client
pans the map to a node; on failure the view simply stays where it is.

So scarcity is not an empty result list - there is no list. It is a property
of two consecutive frames, which makes it a perception question rather than an
OCR one, and puts it here beside the main-view detector.

The hard part is that the map is never completely still. Water animates,
troops walk, banners sway. A pixel-exact comparison would call every frame
"moved". A camera pan, though, changes almost the whole frame at once, while
animation changes a small scattered fraction of it. That gap is what this
measures.

Sensor discipline, per docs/DESIGN_BRIEF.md D1b: it returns MOVED, STILL, or a
refusal. Readings that land between the two thresholds are UNCOMPARABLE, not
rounded to the nearer answer - forcing a verdict there would be a guess
wearing a measurement's clothes.

KNOWN LIMIT, found while testing. The method needs the frame to have structure
at the comparison grid's scale. Over terrain that is uniform at that scale -
open water, blank desert - a real pan leaves the block averages unchanged and
reads as STILL. A false STILL demotes the agent to SCARCITY_FILL, which is the
safe direction to be wrong in, but it is wrong. If the fleet ever farms a
featureless region this needs a second cue.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

#: Coarse grid the frames are reduced to before comparing. Fine enough that a
#: pan is unmistakable, coarse enough that a walking troop is not.
GRID = (48, 27)

#: Per-cell intensity change below this is treated as sensor noise and
#: compression wobble rather than movement.
NOISE_FLOOR = 12

#: NEEDS_CALIBRATION on real before/after pairs. These are starting values
#: chosen so the uncertain band is wide rather than narrow: a wrong STILL
#: makes the agent degrade when it did not need to, a wrong MOVED makes it
#: hunt for a node that is not there, and refusing costs one more frame.
STILL_BELOW = 0.10
MOVED_ABOVE = 0.45


class ViewportVerdict(str, Enum):
    MOVED = "MOVED"
    STILL = "STILL"
    UNCOMPARABLE = "UNCOMPARABLE"


class ViewportChangeError(ValueError):
    """Raised when two frames cannot be compared at all."""


@dataclass(frozen=True)
class ViewportChange:
    verdict: ViewportVerdict
    changed_fraction: float
    reason: str = ""

    @property
    def is_still(self) -> bool:
        """True only on a confident STILL.

        Deliberately not ``verdict is not MOVED`` - an UNCOMPARABLE reading
        must not be quietly counted as scarcity.
        """
        return self.verdict is ViewportVerdict.STILL


class ViewportChangeDetector:
    def __init__(
        self,
        *,
        grid: tuple[int, int] = GRID,
        noise_floor: int = NOISE_FLOOR,
        still_below: float = STILL_BELOW,
        moved_above: float = MOVED_ABOVE,
    ) -> None:
        if grid[0] < 4 or grid[1] < 4:
            raise ViewportChangeError("grid must be at least 4x4 to mean anything")
        if not 0 < noise_floor < 255:
            raise ViewportChangeError("noise_floor must be in 1..254")
        if not 0.0 <= still_below < moved_above <= 1.0:
            raise ViewportChangeError(
                "thresholds must satisfy 0 <= still_below < moved_above <= 1; "
                "an empty or inverted band would remove the refusal case"
            )
        self.grid = grid
        self.noise_floor = noise_floor
        self.still_below = still_below
        self.moved_above = moved_above

    def compare(self, before: Any, after: Any) -> ViewportChange:
        import numpy as np  # noqa: PLC0415

        if before is None or after is None:
            raise ViewportChangeError("both frames are required")
        before = np.asarray(before)
        after = np.asarray(after)
        if before.ndim != 2 or after.ndim != 2:
            raise ViewportChangeError("expected two single-channel grayscale frames")
        if before.shape != after.shape:
            raise ViewportChangeError(
                f"frames differ in size: {before.shape} vs {after.shape}; "
                "a resized client cannot be compared against an older frame"
            )

        left = _reduce(before, self.grid)
        right = _reduce(after, self.grid)
        delta = np.abs(left.astype(np.int16) - right.astype(np.int16))
        fraction = float((delta >= self.noise_floor).mean())

        if fraction <= self.still_below:
            return ViewportChange(
                ViewportVerdict.STILL,
                fraction,
                "the view did not pan; the client offered no node",
            )
        if fraction >= self.moved_above:
            return ViewportChange(
                ViewportVerdict.MOVED,
                fraction,
                "the view panned to a node",
            )
        return ViewportChange(
            ViewportVerdict.UNCOMPARABLE,
            fraction,
            (
                f"changed fraction {fraction:.3f} falls between the still "
                f"({self.still_below}) and moved ({self.moved_above}) "
                f"thresholds; observe another frame rather than guessing"
            ),
        )


def _reduce(frame: Any, grid: tuple[int, int]) -> Any:
    """Average the frame down onto the comparison grid.

    Averaging rather than sampling, so a single bright animated pixel cannot
    carry a whole cell over the noise floor.
    """
    import numpy as np  # noqa: PLC0415

    height, width = frame.shape
    cols, rows = grid
    ys = np.linspace(0, height, rows + 1).astype(int)
    xs = np.linspace(0, width, cols + 1).astype(int)
    out = np.empty((rows, cols), dtype=np.float32)
    for r in range(rows):
        for c in range(cols):
            block = frame[ys[r] : ys[r + 1], xs[c] : xs[c + 1]]
            out[r, c] = block.mean() if block.size else 0.0
    return out


__all__ = [
    "GRID",
    "MOVED_ABOVE",
    "NOISE_FLOOR",
    "STILL_BELOW",
    "ViewportChange",
    "ViewportChangeDetector",
    "ViewportChangeError",
    "ViewportVerdict",
]
