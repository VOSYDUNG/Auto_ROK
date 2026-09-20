"""The second route to WORLD_MAP_VIEW.

The visual signature cannot carry that state: a city always looks like
itself, open terrain does not. Measured on real frames, the city matches its
prototype at distance 0.0001 while every world frame lands at 0.15-0.22
against a 0.08 threshold. A live world-map frame therefore classified as
UNKNOWN_STATE and the agent sat on it for 24 ticks.

The first attempt read the coordinates with OCR and checked they parsed. The
client's day/night cycle broke it: no single scale read both a daylight and a
night frame of the same view. Presence is a shape question, so it is measured
as a shape now - see harness/map_coordinate.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from harness.contracts import Evidence, Observation
from harness.map_coordinate import (
    ABSENT_BELOW,
    COORDINATE_EVIDENCE,
    PRESENT_ABOVE,
    ROI_ID,
    CoordinateStatus,
    MapCoordinateError,
    MapCoordinateReader,
    classify_columns,
    parse_tokens,
    text_columns,
)
from harness.state_classifier import UNKNOWN_STATE, StateClassifier

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / "workspace" / "runs"


class TestPresence:
    def test_a_dense_region_is_present(self):
        reading = classify_columns(121)
        assert reading.status is CoordinateStatus.PRESENT
        assert reading.on_bare_world_map

    def test_an_empty_region_is_absent_not_an_error(self):
        """The city view and every open panel produce this."""
        reading = classify_columns(2)
        assert reading.status is CoordinateStatus.ABSENT
        assert not reading.on_bare_world_map
        assert "city view" in reading.reason

    def test_the_band_between_the_thresholds_is_refused(self):
        reading = classify_columns((PRESENT_ABOVE + ABSENT_BELOW) // 2)
        assert reading.status is CoordinateStatus.UNCERTAIN
        assert not reading.on_bare_world_map
        assert "rather than guessing" in reading.reason

    def test_only_a_confident_present_counts_as_the_world_map(self):
        for columns in (0, ABSENT_BELOW, ABSENT_BELOW + 1, PRESENT_ABOVE - 1):
            assert not classify_columns(columns).on_bare_world_map
        assert classify_columns(PRESENT_ABOVE).on_bare_world_map

    def test_an_inverted_band_is_refused_rather_than_silently_accepted(self):
        with pytest.raises(MapCoordinateError):
            classify_columns(50, present_above=10, absent_below=10)

    def test_counting_is_relative_to_the_region_median_not_absolute(self):
        """This is what makes it survive the night tint.

        The same pattern, once bright on a bright background and once dim on
        a dim one, must count the same. An absolute threshold would see one
        and miss the other, which is exactly how the OCR version failed.
        """
        import numpy as np

        # Text covers a small share of the region, as it does on the real
        # widget (6-18% measured), so the median is the background rather
        # than something between the two levels.
        pattern = np.zeros((10, 20), dtype=np.uint8)
        pattern[4:6, 5:15] = 1
        day = np.where(pattern == 1, 230, 150).astype(np.uint8)
        night = np.where(pattern == 1, 130, 50).astype(np.uint8)
        assert text_columns(day) == text_columns(night) == 10

    def test_an_empty_region_cannot_be_measured(self):
        import numpy as np

        with pytest.raises(MapCoordinateError):
            text_columns(np.zeros((0, 0), dtype=np.uint8))


class TestCoordinateValues:
    """The numbers are for navigation, and never for classification."""

    def test_a_full_readout_parses(self):
        position = parse_tokens(["#1296", "X:1065", "Y:587", "Q"])
        assert (position.kingdom, position.x, position.y) == (1296, 1065, 587)

    def test_coordinates_without_a_kingdom_still_parse(self):
        assert parse_tokens(["X:12", "Y:9"]).kingdom is None

    def test_a_half_read_widget_yields_nothing_rather_than_half_a_position(self):
        assert parse_tokens(["#1296", "Y:587"]) is None
        assert parse_tokens([]) is None

    def test_case_and_punctuation_variants_are_accepted(self):
        assert parse_tokens(["x:5", "y:6"]) is not None
        assert parse_tokens(["X 5", "Y 6"]) is not None


class TestReader:
    def test_a_bad_roi_is_refused_at_construction(self):
        for roi in ((0, 0, 0, 10), (0, 0, 10, 0), (0, 0, 10)):
            with pytest.raises(MapCoordinateError):
                MapCoordinateReader(roi=roi)

    def test_an_inverted_band_is_refused_at_construction(self):
        with pytest.raises(MapCoordinateError):
            MapCoordinateReader(roi=(0, 0, 10, 10), present_above=5, absent_below=9)

    def test_a_missing_frame_is_unreadable_not_absent(self):
        """ABSENT means not the world map. A missing file means neither."""
        reading = MapCoordinateReader(roi=(0, 0, 10, 10)).read(ROOT / "no-such.png")
        assert reading.status is CoordinateStatus.UNREADABLE
        assert not reading.on_bare_world_map

    def test_a_roi_that_runs_off_the_frame_is_unreadable_not_clamped(self):
        import numpy as np

        reader = MapCoordinateReader(
            roi=(0, 0, 400, 10),
            loader=lambda path: np.zeros((20, 20, 3), dtype=np.uint8),
        )
        reading = reader.read(__file__)
        assert reading.status is CoordinateStatus.UNREADABLE
        assert "does not fit" in reading.reason

    def test_a_loader_failure_is_reported_rather_than_raised(self):
        def explode(path):
            raise RuntimeError("decoder gone")

        reading = MapCoordinateReader(roi=(0, 0, 10, 10), loader=explode).read(__file__)
        assert reading.status is CoordinateStatus.UNREADABLE
        assert "decoder gone" in reading.reason


def _observation(*labels: str, frame_id: str = "f-1") -> Observation:
    return Observation(
        timestamp=0.0,
        frame_id=frame_id,
        window_size=(1366, 768),
        evidence=tuple(
            Evidence("test", label, 1.0, value=label, metadata={"frame_id": frame_id})
            for label in labels
        ),
    )


class TestClassifierRoutes:
    def test_the_coordinate_readout_alone_establishes_the_world_map(self):
        result = StateClassifier().classify(_observation(COORDINATE_EVIDENCE))
        assert result.state_id == "WORLD_MAP_VIEW"

    def test_the_original_visual_route_still_works(self):
        result = StateClassifier().classify(
            _observation(
                "map terrain and world objects occupy central canvas",
                "resource counters across top",
                "bottom-right primary navigation is visible",
            )
        )
        assert result.state_id == "WORLD_MAP_VIEW"

    def test_both_routes_at_once_agree_rather_than_conflict(self):
        """Two proofs of one state is agreement, not competing evidence."""
        result = StateClassifier().classify(
            _observation(
                COORDINATE_EVIDENCE,
                "map terrain and world objects occupy central canvas",
                "resource counters across top",
                "bottom-right primary navigation is visible",
            )
        )
        assert result.state_id == "WORLD_MAP_VIEW"

    def test_a_partial_visual_route_without_coordinates_still_refuses(self):
        result = StateClassifier().classify(_observation("resource counters across top"))
        assert result.state_id == UNKNOWN_STATE

    def test_the_city_route_is_untouched(self):
        result = StateClassifier().classify(
            _observation(
                "city buildings occupy central world canvas",
                "resource counters across top",
                "primary circular navigation/actions at bottom-right",
                "quest/task list at left",
            )
        )
        assert result.state_id == "CITY_VIEW"

    def test_the_coordinate_route_does_not_leak_into_other_states(self):
        """It must not turn a search panel into a world map."""
        result = StateClassifier().classify(
            _observation("SEARCH", "Barbarians", "Cropland")
        )
        assert result.state_id == "RESOURCE_SEARCH_PANEL"


LIVE_CASES = (
    ("p3-observe-20260920/frame-01.png", True),
    ("m7-live-20260920/after-march.png", True),
    ("m7-live-20260920/unknown-state.png", True),
    # The same view at NIGHT. The client tints the whole map dark, which is
    # what defeated the OCR-based version of this sensor.
    ("m7-live-20260920/world-night.png", True),
    ("m7-live-20260920/queue-check.png", True),
    ("m7-live-20260920/city-01.png", False),
    ("m7-live-20260920/troop-setup.png", False),
    ("m7-live-20260920/stuck-01.png", False),
)


@pytest.mark.parametrize("relative,expected", LIVE_CASES)
def test_it_separates_real_frames(relative, expected):
    """Measured 2026-09-20, 8/8 including the frame that stalled the agent.

    ``stuck-01`` is the search panel and expects False on purpose: the client
    replaces the coordinate widget with a back arrow, so the signal means
    "world map with nothing on top of it" rather than merely "world map".

    ``world-night`` is the same view after dark. It is the case that killed
    the first version of this sensor, so it stays in the set.
    """
    from harness.cpu_roi import load_default_cpu_roi_profile
    from harness.map_coordinate import reader_from_profile

    frame = FRAMES / relative
    if not frame.exists():
        pytest.skip(f"{relative} not present")
    reader = reader_from_profile(load_default_cpu_roi_profile(), (1366, 768))
    assert reader.read(frame).on_bare_world_map is expected


def test_the_roi_it_reads_is_the_calibrated_one():
    from harness.cpu_roi import load_default_cpu_roi_profile

    resolved = load_default_cpu_roi_profile().resolve(ROI_ID, (1366, 768))
    assert resolved.rect.as_list() == [160, 0, 185, 36]


def test_the_measured_margin_between_present_and_absent_is_still_wide():
    """80 columns against 2 is why the uncertain band costs nothing."""
    from harness.cpu_roi import load_default_cpu_roi_profile
    from harness.map_coordinate import reader_from_profile

    reader = reader_from_profile(load_default_cpu_roi_profile(), (1366, 768))
    present: list[int] = []
    absent: list[int] = []
    for relative, expected in LIVE_CASES:
        frame = FRAMES / relative
        if not frame.exists():
            continue
        (present if expected else absent).append(reader.read(frame).text_columns)
    if present and absent:
        assert min(present) > max(absent) * 4, (
            f"the margin collapsed: present {sorted(present)} vs absent "
            f"{sorted(absent)}; recalibrate rather than nudging a threshold"
        )
