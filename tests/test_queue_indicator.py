"""March-queue indicator reader.

The decoy test is the important one. The same frame that shows queue 1/5 also
shows "Trade Deal (5/5) Make 5 purchases at the Courier Station", so anything
that searches the frame for an n/5 pattern reads quest progress as a full
queue - and then declines to dispatch while four slots sit empty, silently.
"""
import json
from pathlib import Path

import numpy as np
import pytest

from harness.queue_indicator import (
    QueueIndicatorError,
    QueueIndicatorProfile,
    QueueIndicatorReader,
    QueueReadStatus,
    train_glyph,
)

ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "config" / "queue_indicator_profile.json"
LIVE_FRAME = ROOT / "workspace" / "runs" / "p3-observe-20260920" / "frame-01.png"


@pytest.fixture
def profile() -> QueueIndicatorProfile:
    return QueueIndicatorProfile.load(PROFILE_PATH)


def _blank(width: int = 1366, height: int = 768) -> np.ndarray:
    """Mid-grey, like the open grass the indicator sits on."""
    return np.full((height, width), 120, dtype=np.uint8)


def _paint(frame: np.ndarray, pattern, x: int, y: int, value: int = 255) -> None:
    for row_index, row in enumerate(pattern):
        for col_index, cell in enumerate(row):
            if cell == "#":
                frame[y + row_index, x + col_index] = value


def _render(profile: QueueIndicatorProfile, labels, frame=None) -> np.ndarray:
    """Draw glyphs inside the ROI with the spacing the client uses."""
    frame = _blank() if frame is None else frame
    x, y, _, _ = profile.roi
    cursor = x + 12
    for label in labels:
        pattern = profile.glyphs[label]
        _paint(frame, pattern, cursor, y + 3)
        cursor += len(pattern[0]) + 2
    return frame


def test_the_profile_holds_only_glyphs_that_were_actually_observed(profile):
    """The profile GROWS as the queue takes new values, and only then.

    It shipped knowing 1, / and 5 because that is all the training frame
    showed. "2" was added on 2026-09-20 from a live frame after a second
    march went out, through scripts/train_queue_glyph.py, which requires the
    operator to state what the indicator reads. Each entry must trace back to
    a frame; a digit nobody saw is a digit nobody can vouch for.
    """
    raw = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    assert raw["observed_value"] == "1/5"
    assert profile.client_size == (1366, 768)

    assert {"1", "/", "5"} <= set(profile.glyphs), "the original glyphs must survive"
    trained_from = raw.get("trained_from") or {}
    for label in set(profile.glyphs) - {"1", "/", "5"}:
        assert any(label in value for value in trained_from), (
            f"glyph {label!r} has no frame recorded in trained_from; add it "
            "with scripts/train_queue_glyph.py rather than by hand"
        )


def test_it_reads_the_queue_it_was_trained_on(profile):
    reading = QueueIndicatorReader(profile).read(_render(profile, ["1", "/", "5"]))
    assert reading.status is QueueReadStatus.READ
    assert (reading.used, reading.capacity) == (1, 5)
    assert reading.free_slots == 4


def test_a_full_queue_reads_as_full(profile):
    reading = QueueIndicatorReader(profile).read(_render(profile, ["5", "/", "5"]))
    assert reading.ok
    assert (reading.used, reading.capacity) == (5, 5)
    assert reading.free_slots == 0


def test_the_quest_decoy_elsewhere_in_the_frame_is_ignored(profile):
    """STA-005. The decoy is real and was observed on the live client."""
    frame = _render(profile, ["1", "/", "5"])
    # "(5/5)" painted where the quest list sits, far from the indicator.
    decoy_x, decoy_y = 40, 400
    cursor = decoy_x
    for label in ("5", "/", "5"):
        _paint(frame, profile.glyphs[label], cursor, decoy_y)
        cursor += len(profile.glyphs[label][0]) + 2

    reading = QueueIndicatorReader(profile).read(frame)
    assert reading.ok
    assert reading.used == 1, "the reader must not see the quest progress"
    assert reading.free_slots == 4
    for glyph in reading.glyphs:
        assert glyph.y < 200, "every glyph read must come from the indicator ROI"


def test_an_untrained_digit_is_refused_rather_than_guessed(profile):
    """Digits 0, 2, 3 and 4 have not been observed yet."""
    frame = _blank()
    x, y, _, _ = profile.roi
    unknown = ("###", "#.#", "#.#", "#.#", "###")  # a zero-ish shape, untrained
    _paint(frame, unknown, x + 12, y + 3)
    cursor = x + 12 + 5
    for label in ("/", "5"):
        _paint(frame, profile.glyphs[label], cursor, y + 3)
        cursor += len(profile.glyphs[label][0]) + 2

    reading = QueueIndicatorReader(profile).read(frame)
    assert reading.status is QueueReadStatus.UNKNOWN_GLYPH
    assert reading.used is None and reading.capacity is None
    assert "does not match" in reading.reason


def test_an_empty_region_reports_no_text_not_zero(profile):
    reading = QueueIndicatorReader(profile).read(_blank())
    assert reading.status is QueueReadStatus.NO_TEXT
    assert reading.used is None
    assert reading.free_slots is None


def test_the_wrong_frame_size_is_refused_because_the_roi_would_move(profile):
    reading = QueueIndicatorReader(profile).read(_blank(1920, 1080))
    assert reading.status is QueueReadStatus.BAD_SHAPE
    assert "1366x768" in reading.reason


def test_a_missing_separator_is_refused(profile):
    reading = QueueIndicatorReader(profile).read(_render(profile, ["1", "5", "5"]))
    assert reading.status is QueueReadStatus.BAD_SHAPE
    assert not reading.ok


def test_an_impossible_queue_state_is_refused(profile):
    """A denominator smaller than the numerator means something misread."""
    reading = QueueIndicatorReader(profile).read(_render(profile, ["5", "/", "1"]))
    assert reading.status is QueueReadStatus.BAD_SHAPE
    assert "not a possible queue state" in reading.reason


def test_two_glyphs_are_refused(profile):
    reading = QueueIndicatorReader(profile).read(_render(profile, ["1", "5"]))
    assert reading.status is QueueReadStatus.BAD_SHAPE
    assert "segmented 2" in reading.reason


def test_a_colour_frame_is_refused(profile):
    with pytest.raises(QueueIndicatorError):
        QueueIndicatorReader(profile).read(np.zeros((768, 1366, 3), dtype=np.uint8))


def test_a_profile_with_no_glyphs_is_refused():
    with pytest.raises(QueueIndicatorError):
        QueueIndicatorProfile(
            roi=(0, 0, 10, 10), threshold=200, client_size=(1366, 768), glyphs={}
        )


@pytest.mark.parametrize("threshold", [0, 256, -1])
def test_an_unusable_threshold_is_refused(threshold):
    with pytest.raises(QueueIndicatorError):
        QueueIndicatorProfile(
            roi=(0, 0, 10, 10),
            threshold=threshold,
            client_size=(1366, 768),
            glyphs={"1": ("#",)},
        )


def test_training_refuses_a_glyph_index_that_was_not_segmented(profile):
    with pytest.raises(QueueIndicatorError):
        train_glyph(_blank(), profile, 0)


@pytest.mark.skipif(not LIVE_FRAME.exists(), reason="live capture not present")
def test_it_reads_one_of_five_from_the_real_captured_frame(profile):
    """The frame OCR could not read at all."""
    cv2 = pytest.importorskip("cv2")
    frame = cv2.imread(str(LIVE_FRAME))
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    reading = QueueIndicatorReader(profile).read(gray)
    assert reading.status is QueueReadStatus.READ
    assert (reading.used, reading.capacity) == (1, 5)
    assert reading.free_slots == 4


def test_it_reads_an_independent_live_frame_not_just_its_training_frame():
    """Recalibrated 2026-09-20 after the sensor refused a real 1/5.

    The profile was trained at threshold 200 on one frame, with a one-pixel
    tolerance. On a live frame captured right after the agent dispatched its
    first march, one pixel of antialiasing shrank the "/" from 3x10 to 2x8 -
    a different SHAPE, so it could not even be compared, and a true 1/5 came
    back UNKNOWN_GLYPH.

    Measured across thresholds, 160 and 180 segment the three glyphs
    identically on both frames while 200 and 220 do not. 200 was sitting on
    a cliff edge.

    This test exists because one training frame cannot show that. A second,
    independently captured frame can.
    """
    import cv2

    root = Path(__file__).resolve().parents[1]
    live = root / "workspace" / "runs" / "m7-live-20260920" / "queue-1of5-live.png"
    if not live.exists():
        pytest.skip("live 1/5 frame not present")

    profile = QueueIndicatorProfile.load(root / "config" / "queue_indicator_profile.json")
    reading = QueueIndicatorReader(profile).read(
        cv2.cvtColor(cv2.imread(str(live)), cv2.COLOR_BGR2GRAY)
    )
    assert reading.status is QueueReadStatus.READ
    assert (reading.used, reading.capacity) == (1, 5)
    assert reading.free_slots == 4


def test_the_threshold_is_not_back_on_the_cliff_edge():
    """200 refused a real reading; 180 does not. Do not drift back."""
    root = Path(__file__).resolve().parents[1]
    profile = QueueIndicatorProfile.load(root / "config" / "queue_indicator_profile.json")
    assert profile.threshold <= 180, (
        "raising the threshold above 180 shrinks the / glyph on dimmer "
        "frames and turns real readings into UNKNOWN_GLYPH"
    )
    assert profile.max_glyph_distance <= 1, (
        "widening the glyph distance to paper over a threshold problem would "
        "make 1 and 4 confusable; fix the threshold instead"
    )
