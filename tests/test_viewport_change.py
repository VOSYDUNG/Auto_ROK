"""Scarcity detected from two frames, not from an empty list.

The operator: pressing Search either pans the view to a node, or the view
simply stays where it is. The map is never perfectly still - water animates,
troops walk - so the test is whether the whole frame moved, not whether any
pixel changed.
"""
import numpy as np
import pytest

from harness.viewport_change import (
    ViewportChangeDetector,
    ViewportChangeError,
    ViewportVerdict,
)

H, W = 768, 1366


def _terrain(seed=0):
    """Grass with large features on it - trees, buildings, roads.

    A uniform-noise field would be wrong here: block averages of uniform noise
    are the same everywhere, so shifting it does not change them and a real
    pan would read as STILL. Real terrain has structure at this scale, which
    is exactly what the detector relies on.
    """
    rng = np.random.default_rng(seed)
    frame = rng.integers(100, 140, size=(H, W), dtype=np.uint8)
    for _ in range(60):
        y, x = rng.integers(0, H - 90), rng.integers(0, W - 90)
        h, w = rng.integers(40, 90), rng.integers(40, 90)
        frame[y : y + h, x : x + w] = rng.integers(20, 240)
    return frame


def _animate(frame, cells=40, seed=1):
    """Small scattered changes, like troops walking and water moving."""
    out = frame.copy()
    rng = np.random.default_rng(seed)
    for _ in range(cells):
        y, x = rng.integers(0, H - 20), rng.integers(0, W - 20)
        out[y : y + 16, x : x + 16] = rng.integers(0, 255)
    return out


def _pan(frame, dx=260):
    """A camera pan: the whole frame shifts."""
    return np.roll(frame, dx, axis=1)


@pytest.fixture
def detector():
    return ViewportChangeDetector()


def test_an_identical_frame_reads_as_still(detector):
    frame = _terrain()
    result = detector.compare(frame, frame)
    assert result.verdict is ViewportVerdict.STILL
    assert result.changed_fraction == 0.0
    assert result.is_still


def test_ordinary_animation_does_not_count_as_movement(detector):
    """Water and troops move on every frame; that is not a search result."""
    frame = _terrain()
    result = detector.compare(frame, _animate(frame))
    assert result.verdict is ViewportVerdict.STILL, result
    assert result.is_still


def test_a_camera_pan_reads_as_moved(detector):
    frame = _terrain()
    result = detector.compare(frame, _pan(frame))
    assert result.verdict is ViewportVerdict.MOVED, result
    assert not result.is_still


def test_a_reading_between_the_thresholds_is_refused():
    """Forcing a verdict here would be a guess wearing a measurement's clothes."""
    detector = ViewportChangeDetector(still_below=0.0, moved_above=1.0)
    frame = _terrain()
    result = detector.compare(frame, _animate(frame, cells=60))
    assert result.verdict is ViewportVerdict.UNCOMPARABLE
    assert "rather than guessing" in result.reason


def test_an_uncomparable_reading_is_not_quietly_treated_as_scarcity():
    detector = ViewportChangeDetector(still_below=0.0, moved_above=1.0)
    frame = _terrain()
    result = detector.compare(frame, _animate(frame, cells=60))
    assert result.verdict is ViewportVerdict.UNCOMPARABLE
    assert not result.is_still, "only a confident STILL may mean scarcity"


def test_frames_of_different_sizes_cannot_be_compared(detector):
    with pytest.raises(ViewportChangeError, match="differ in size"):
        detector.compare(_terrain(), np.zeros((100, 100), dtype=np.uint8))


def test_a_colour_frame_is_refused(detector):
    with pytest.raises(ViewportChangeError, match="grayscale"):
        detector.compare(np.zeros((H, W, 3), np.uint8), np.zeros((H, W, 3), np.uint8))


def test_a_missing_frame_is_refused(detector):
    with pytest.raises(ViewportChangeError, match="both frames"):
        detector.compare(_terrain(), None)


def test_an_inverted_threshold_band_is_refused():
    """An empty band would remove the refusal case entirely."""
    with pytest.raises(ViewportChangeError, match="still_below < moved_above"):
        ViewportChangeDetector(still_below=0.6, moved_above=0.2)
    with pytest.raises(ViewportChangeError, match="still_below < moved_above"):
        ViewportChangeDetector(still_below=0.3, moved_above=0.3)


def test_a_grid_too_coarse_to_mean_anything_is_refused():
    with pytest.raises(ViewportChangeError, match="4x4"):
        ViewportChangeDetector(grid=(2, 2))


def test_the_verdict_drives_the_ladder_the_way_the_operator_described():
    """STILL after a search is what demotes to SCARCITY_FILL."""
    from datetime import datetime, timezone

    from autorok.mission.ladder import Ladder, Rung

    detector = ViewportChangeDetector()
    frame = _terrain()
    result = detector.compare(frame, _animate(frame))

    ladder = Ladder(start=Rung.DEFAULT_FARM)
    if result.is_still:
        ladder.demote(
            f"search did not pan the view ({result.changed_fraction:.3f} changed)",
            at=datetime(2026, 9, 20, tzinfo=timezone.utc),
        )
    assert ladder.current is Rung.SCARCITY_FILL
