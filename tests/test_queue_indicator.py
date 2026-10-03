"""March-queue indicator reader.

The decoy test is the important one. The same frame that shows queue 1/5 also
shows "Trade Deal (5/5) Make 5 purchases at the Courier Station", so anything
that searches the frame for an n/5 pattern reads quest progress as a full
queue - and then declines to dispatch while four slots sit empty, silently.
"""
from dataclasses import replace
import hashlib
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
FIRST_POST_FRAME = ROOT / "workspace" / "runs" / "f6-first-postcheck-blocker-20260927-05" / "current.png"
FIRST_POST_SHA256 = "c53e3a1301ea8d05ee0184025b0a3003a68a629aeaa82144b3ffe27b798aa5aa"
MEASURED_FIVE = ("####.", "#....", "##...", "####.", "...##", "...##", "####.", ".##..")
SECOND_POST_FRAME = (ROOT / "workspace" / "runtime" / "gather_resource-65256b73ad7ed58a"
                    / "observation-a6d1372389a74a01a8f565905b659b36" / "current.png")
SECOND_POST_SHA256 = "43cc31fec61cbd79016681b6878cead3bddef4ec2a22b6d535132823f6cd80d9"
MEASURED_TWO = ("####", "...#", "...#", "..##", "..#.", ".##.", "###.", "####")
SECOND_MEASURED_FIVE = ("####", "#...", "##..", "####", "...#", "...#", "#.##", ".##.")
THIRD_POST_FRAME = (ROOT / "workspace" / "runtime" / "gather_resource-08997d0c79631279"
                    / "observation-7cd2684846734f60bf6677952cdf7a31" / "current.png")
THIRD_POST_SHA256 = "fd7ee1763c6e87ccf025d59de4f3fed986646433334601049118825b2c6d55c7"
MEASURED_THREE = ("..#...", "#####.", "....#.", "...##.", "..##..", "....#.", "....##", "##.##.", ".###..")
FOURTH_POST_FRAME = (ROOT / "workspace" / "runtime" / "gather_resource-d445aecd201f29bc"
                     / "observation-9dfd764b29e64036a168684562d8e570" / "current.png")
FOURTH_POST_SHA256 = "e068105fe5274166fa6a55afbf3aa6f63b61d2b1501055afb0ac66bd03c4efb4"
MEASURED_FOUR = ("..###.", "..###.", ".##.#.", "##..#.", "######", ".#####", "...##.")


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
        # A label now carries several accepted renderings; draw the first.
        pattern = profile.glyphs[label][0]
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
        _paint(frame, profile.glyphs[label][0], cursor, decoy_y)
        cursor += len(profile.glyphs[label][0]) + 2

    reading = QueueIndicatorReader(profile).read(frame)
    assert reading.ok
    assert reading.used == 1, "the reader must not see the quest progress"
    assert reading.free_slots == 4
    for glyph in reading.glyphs:
        assert glyph.y < 200, "every glyph read must come from the indicator ROI"


def test_an_untrained_digit_is_refused_rather_than_guessed(profile):
    """A shape the profile has never been shown gets no reading at all."""
    frame = _blank()
    x, y, _, _ = profile.roi
    unknown = ("###", "#.#", "#.#", "#.#", "###")  # a zero-ish shape, untrained
    _paint(frame, unknown, x + 12, y + 3)
    cursor = x + 12 + len(unknown[0]) + 2
    for label in ("/", "5"):
        pattern = profile.glyphs[label][0]
        _paint(frame, pattern, cursor, y + 3)
        cursor += len(pattern[0]) + 2

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


def test_measured_five_variant_retains_capture_provenance_and_limits(profile):
    raw = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    assert MEASURED_FIVE in profile.glyphs["5"]
    source = raw["training_sources"]["1/5"]
    assert source["frame_id"] == "rok-20260927T024044381473Z-c53e3a1301ea"
    assert source["frame_sha256"] == FIRST_POST_SHA256
    assert Path(source["frame_path"]).name == "current.png"
    assert Path(source["manifest_path"]).name == "capture.json"
    assert source["archived_frame_path"] == str(FIRST_POST_FRAME.relative_to(ROOT)).replace("\\", "/")
    assert "ROOT inspection" in source["visual_label_source"]
    assert profile.roi == (1310, 113, 40, 15)
    assert profile.threshold == 180 and profile.max_glyph_distance == 1
    assert set(profile.glyphs) == {"1", "2", "3", "4", "5", "/"}


@pytest.mark.skipif(not FIRST_POST_FRAME.exists(), reason="immutable first-March postframe not present")
def test_exact_saved_first_march_postframe_reads_one_of_five(profile):
    import cv2

    assert hashlib.sha256(FIRST_POST_FRAME.read_bytes()).hexdigest() == FIRST_POST_SHA256
    raw = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    source = raw["training_sources"]["1/5"]
    manifest = json.loads((ROOT / source["archived_manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["frame"]["id"] == source["frame_id"]
    assert manifest["frame"]["image_sha256"] == source["frame_sha256"]
    assert manifest["png"] == source["frame_path"]
    gray = cv2.cvtColor(cv2.imread(str(FIRST_POST_FRAME)), cv2.COLOR_BGR2GRAY)
    old_glyphs = dict(profile.glyphs)
    old_glyphs["5"] = tuple(pattern for pattern in old_glyphs["5"] if pattern != MEASURED_FIVE)
    before = QueueIndicatorReader(replace(profile, glyphs=old_glyphs)).read(gray)
    assert before.status is QueueReadStatus.UNKNOWN_GLYPH
    assert before.used is None and before.capacity is None
    after = QueueIndicatorReader(profile).read(gray)
    assert after.status is QueueReadStatus.READ
    assert (after.used, after.capacity, after.free_slots) == (1, 5, 4)
    assert after.glyphs[-1].pattern == MEASURED_FIVE
    assert all(1310 <= box.x < 1350 and 113 <= box.y < 128 for box in after.glyphs)


@pytest.mark.parametrize("used", range(1, 6))
def test_archived_real_queue_values_survive_added_five_variant(profile, used):
    import cv2

    name = "queue-1of5-live.png" if used == 1 else f"queue-{used}of5.png"
    frame = ROOT / "workspace" / "runs" / "m7-live-20260920" / name
    if not frame.exists():
        pytest.skip("archived queue frame not present")
    gray = cv2.cvtColor(cv2.imread(str(frame)), cv2.COLOR_BGR2GRAY)
    reading = QueueIndicatorReader(profile).read(gray)
    assert reading.status is QueueReadStatus.READ
    assert (reading.used, reading.capacity) == (used, 5)


def test_conflicting_label_for_measured_five_is_ambiguous_not_numeric(profile):
    # Fault injection into a test-only profile checks the reader's ambiguity gate.
    glyphs = dict(profile.glyphs)
    glyphs["2"] = glyphs["2"] + (MEASURED_FIVE,)
    ambiguous = replace(profile, glyphs=glyphs)
    frame = _render(profile, ["1", "/"])
    x, y, _, _ = profile.roi
    cursor = x + 12 + sum(len(profile.glyphs[label][0][0]) + 2 for label in ["1", "/"])
    _paint(frame, MEASURED_FIVE, cursor, y + 3)
    reading = QueueIndicatorReader(ambiguous).read(frame)
    assert reading.status is QueueReadStatus.AMBIGUOUS_GLYPH
    assert reading.used is None and reading.capacity is None


def test_second_march_samples_have_native_capture_provenance_and_unchanged_limits(profile):
    raw = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    source = raw["training_sources"]["2/5"]
    assert source["frame_id"] == "rok-20260927T032011022422Z-43cc31fec61c"
    assert source["frame_sha256"] == SECOND_POST_SHA256
    assert Path(source["frame_path"]) == SECOND_POST_FRAME
    assert Path(source["manifest_path"]) == SECOND_POST_FRAME.with_name("capture.json")
    assert MEASURED_TWO in profile.glyphs["2"]
    assert SECOND_MEASURED_FIVE in profile.glyphs["5"]
    assert profile.roi == (1310, 113, 40, 15)
    assert profile.threshold == 180 and profile.max_glyph_distance == 1
    assert set(profile.glyphs) == {"1", "2", "3", "4", "5", "/"}


@pytest.mark.skipif(not SECOND_POST_FRAME.exists(), reason="immutable second-March postframe not present")
def test_exact_second_march_capture_reads_two_with_both_measured_variants(profile):
    import cv2

    assert hashlib.sha256(SECOND_POST_FRAME.read_bytes()).hexdigest() == SECOND_POST_SHA256
    manifest = json.loads(SECOND_POST_FRAME.with_name("capture.json").read_text())
    assert manifest["frame"]["image_sha256"] == SECOND_POST_SHA256
    assert manifest["frame"]["id"] == "rok-20260927T032011022422Z-43cc31fec61c"
    assert Path(manifest["png"]) == SECOND_POST_FRAME
    gray = cv2.cvtColor(cv2.imread(str(SECOND_POST_FRAME)), cv2.COLOR_BGR2GRAY)
    for label, sample in (("2", MEASURED_TWO), ("5", SECOND_MEASURED_FIVE)):
        old_glyphs = dict(profile.glyphs)
        old_glyphs[label] = tuple(pattern for pattern in old_glyphs[label] if pattern != sample)
        before = QueueIndicatorReader(replace(profile, glyphs=old_glyphs)).read(gray)
        assert before.status is QueueReadStatus.UNKNOWN_GLYPH
        assert before.used is None and before.capacity is None
    after = QueueIndicatorReader(profile).read(gray)
    assert after.status is QueueReadStatus.READ
    assert (after.used, after.capacity, after.free_slots) == (2, 5, 3)
    assert after.glyphs[0].pattern == MEASURED_TWO
    assert after.glyphs[-1].pattern == SECOND_MEASURED_FIVE


def test_conflicting_label_for_measured_two_is_ambiguous_without_numeric_progress(profile):
    glyphs = dict(profile.glyphs)
    glyphs["4"] = glyphs["4"] + (MEASURED_TWO,)
    ambiguous = replace(profile, glyphs=glyphs)
    frame = _blank()
    x, y, _, _ = profile.roi
    cursor = x + 12
    for pattern in (MEASURED_TWO, profile.glyphs["/"][0], SECOND_MEASURED_FIVE):
        _paint(frame, pattern, cursor, y + 3)
        cursor += len(pattern[0]) + 2
    reading = QueueIndicatorReader(ambiguous).read(frame)
    assert reading.status is QueueReadStatus.AMBIGUOUS_GLYPH
    assert reading.used is None and reading.capacity is None and reading.free_slots is None


@pytest.mark.skipif(not THIRD_POST_FRAME.exists(), reason="immutable third-March postframe not present")
def test_exact_third_march_capture_requires_measured_three_variant(profile):
    """The native 3/5 frame is refused until its measured 3 glyph is present."""
    import cv2

    assert hashlib.sha256(THIRD_POST_FRAME.read_bytes()).hexdigest() == THIRD_POST_SHA256
    raw = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    source = raw["training_sources"]["3/5"]
    assert source["frame_id"] == "rok-20260927T080529556776Z-fd7ee1763c6e"
    assert source["frame_sha256"] == THIRD_POST_SHA256
    assert source["visual_label_source"].startswith("ROOT inspection")
    manifest = json.loads(Path(source["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["frame"]["image_sha256"] == THIRD_POST_SHA256
    assert manifest["backend"]["cursor_capture"] is False

    gray = cv2.cvtColor(cv2.imread(str(THIRD_POST_FRAME)), cv2.COLOR_BGR2GRAY)
    old_glyphs = dict(profile.glyphs)
    old_glyphs["3"] = tuple(pattern for pattern in old_glyphs["3"] if pattern != MEASURED_THREE)
    before = QueueIndicatorReader(replace(profile, glyphs=old_glyphs)).read(gray)
    assert before.status is QueueReadStatus.UNKNOWN_GLYPH
    assert before.used is None and before.capacity is None
    after = QueueIndicatorReader(profile).read(gray)
    assert after.status is QueueReadStatus.READ
    assert (after.used, after.capacity, after.free_slots) == (3, 5, 2)
    assert after.glyphs[0].pattern == MEASURED_THREE


@pytest.mark.skipif(not THIRD_POST_FRAME.exists(), reason="immutable third-March postframe not present")
def test_conflicting_label_for_measured_three_cannot_publish_numeric_progress(profile):
    import cv2

    glyphs = dict(profile.glyphs)
    glyphs["4"] = glyphs["4"] + (MEASURED_THREE,)
    gray = cv2.cvtColor(cv2.imread(str(THIRD_POST_FRAME)), cv2.COLOR_BGR2GRAY)
    reading = QueueIndicatorReader(replace(profile, glyphs=glyphs)).read(gray)
    assert reading.status is QueueReadStatus.AMBIGUOUS_GLYPH
    assert reading.used is None and reading.capacity is None and reading.free_slots is None


@pytest.mark.skipif(not FOURTH_POST_FRAME.exists(), reason="immutable fourth-March postframe not present")
def test_exact_fourth_march_capture_requires_measured_four_variant(profile):
    """The native 4/5 frame is refused until its measured 4 glyph is present."""
    import cv2

    assert hashlib.sha256(FOURTH_POST_FRAME.read_bytes()).hexdigest() == FOURTH_POST_SHA256
    raw = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    source = raw["training_sources"]["4/5"]
    assert source["frame_id"] == "rok-20260927T081135834446Z-e068105fe527"
    assert source["frame_sha256"] == FOURTH_POST_SHA256
    assert source["visual_label_source"].startswith("ROOT inspection")
    manifest = json.loads(Path(source["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["frame"]["image_sha256"] == FOURTH_POST_SHA256
    assert manifest["backend"]["cursor_capture"] is False

    gray = cv2.cvtColor(cv2.imread(str(FOURTH_POST_FRAME)), cv2.COLOR_BGR2GRAY)
    old_glyphs = dict(profile.glyphs)
    old_glyphs["4"] = tuple(pattern for pattern in old_glyphs["4"] if pattern != MEASURED_FOUR)
    before = QueueIndicatorReader(replace(profile, glyphs=old_glyphs)).read(gray)
    assert before.status is QueueReadStatus.UNKNOWN_GLYPH
    assert before.used is None and before.capacity is None
    after = QueueIndicatorReader(profile).read(gray)
    assert after.status is QueueReadStatus.READ
    assert (after.used, after.capacity, after.free_slots) == (4, 5, 1)
    assert after.glyphs[0].pattern == MEASURED_FOUR


@pytest.mark.skipif(not FOURTH_POST_FRAME.exists(), reason="immutable fourth-March postframe not present")
def test_conflicting_label_for_measured_four_cannot_publish_numeric_progress(profile):
    import cv2

    glyphs = dict(profile.glyphs)
    glyphs["3"] = glyphs["3"] + (MEASURED_FOUR,)
    gray = cv2.cvtColor(cv2.imread(str(FOURTH_POST_FRAME)), cv2.COLOR_BGR2GRAY)
    reading = QueueIndicatorReader(replace(profile, glyphs=glyphs)).read(gray)
    assert reading.status is QueueReadStatus.AMBIGUOUS_GLYPH
    assert reading.used is None and reading.capacity is None and reading.free_slots is None
