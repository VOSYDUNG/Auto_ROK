import json
from pathlib import Path

import pytest

from harness.action_surface import ActionRequest
from harness.contracts import Evidence, Observation
from harness.mission_runtime import MissionContext
from harness.mission_tool import ObservationBundle
from harness.resource_level_control import (
    GatherScreenMappedActionSurface,
    ResourceLevelControlObservationProvider,
    ResourceLevelProfile,
)
from harness.scene_graph import SceneGraph


CONTEXT = MissionContext("GATHER_RESOURCE", "one-character", "run-level")


class FakeProvider:
    def __init__(self, window_size=(1000, 500), client_screen_rect=(100, 200, 1100, 700)):
        self.window_size = window_size
        self.client_screen_rect = client_screen_rect

    def observe(self, context):
        observation = Observation(
            1.0,
            "f1",
            self.window_size,
            (
                Evidence("ocr", "SEARCH", 0.0, value="SEARCH", metadata={"frame_id": "f1"}),
                Evidence("ocr", "Cropland", 0.0, value="Cropland", metadata={"frame_id": "f1"}),
                Evidence("ocr", "Level:", 0.0, value="Level:", metadata={"frame_id": "f1"}),
            ),
        )
        return ObservationBundle(
            observation,
            SceneGraph("f1", None, (), {"client_screen_rect": list(self.client_screen_rect)}),
        )


def trained_profile(tmp_path):
    path = tmp_path / "level.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "trained",
                "control_mode": "horizontal_discrete_slider",
                "min_level": 1,
                "max_level": 10,
                "track_normalized": [0.20, 0.70, 0.80, 0.76],
                "confidence": 0.97,
                "required_anchors": ["SEARCH", "Cropland"],
            }
        ),
        encoding="utf-8",
    )
    return ResourceLevelProfile.load(path)


def test_untrained_profile_never_grounds_control(tmp_path):
    path = tmp_path / "level.json"
    path.write_text(json.dumps({"schema_version": 1, "status": "untrained"}), encoding="utf-8")
    bundle = ResourceLevelControlObservationProvider(FakeProvider(), ResourceLevelProfile.load(path)).observe(CONTEXT)
    assert bundle.scene.target("SEARCH_LEVEL_CONTROL") is None
    assert bundle.scene.facts["resource_level_control"]["status"] == "untrained"


def test_trained_profile_requires_explicit_control_mode(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "trained",
                "min_level": 1,
                "max_level": 10,
                "track_normalized": [0.20, 0.70, 0.80, 0.76],
                "confidence": 0.97,
                "required_anchors": ["SEARCH", "Cropland"],
            }
        ),
        encoding="utf-8",
    )
    try:
        ResourceLevelProfile.load(path)
    except ValueError as exc:
        assert "control_mode" in str(exc)
    else:
        raise AssertionError("trained control without explicit mode must fail closed")


def test_trained_profile_requires_current_search_anchors(tmp_path):
    bundle = ResourceLevelControlObservationProvider(FakeProvider(), trained_profile(tmp_path)).observe(CONTEXT)
    target = bundle.scene.require_target("SEARCH_LEVEL_CONTROL", 0.90)
    assert target.frame_id == "f1"
    assert target.source == "trained_resource_level_profile"
    assert bundle.scene.facts["resource_level_control"]["status"] == "grounded"
    contract = bundle.scene.facts["typed_action_contracts"]["SET_RESOURCE_LEVEL"]
    assert contract["argument"] == "resource_level"
    assert contract["fact"] == "selected_search_level"


def test_typed_surface_maps_requested_level_to_discrete_slider_point(tmp_path):
    bundle = ResourceLevelControlObservationProvider(FakeProvider(), trained_profile(tmp_path)).observe(CONTEXT)
    surface = GatherScreenMappedActionSurface({}, min_target_confidence=0.90)
    resolved = surface.resolve(
        ActionRequest(
            "SET_RESOURCE_LEVEL",
            "SEARCH_LEVEL_CONTROL",
            {"resource_level": 10},
        ),
        scene=bundle.scene,
    )
    assert resolved.point == (900, 565)
    assert resolved.source == "trained_resource_level_profile+client_to_screen"


def test_typed_surface_rejects_out_of_range_level(tmp_path):
    bundle = ResourceLevelControlObservationProvider(FakeProvider(), trained_profile(tmp_path)).observe(CONTEXT)
    surface = GatherScreenMappedActionSurface({}, min_target_confidence=0.90)
    try:
        surface.resolve(
            ActionRequest("SET_RESOURCE_LEVEL", "SEARCH_LEVEL_CONTROL", {"resource_level": 11}),
            scene=bundle.scene,
        )
    except ValueError as exc:
        assert "outside the trained control range" in str(exc)
    else:
        raise AssertionError("out-of-range level must fail closed")


def test_production_profile_maps_observed_level_handles_to_live_client_points():
    profile_path = Path(__file__).resolve().parents[1] / "config" / "resource_level_profile.json"
    profile = ResourceLevelProfile.load(profile_path)
    bundle = ResourceLevelControlObservationProvider(
        FakeProvider(window_size=(1366, 768), client_screen_rect=(0, 0, 1366, 768)),
        profile,
    ).observe(CONTEXT)
    surface = GatherScreenMappedActionSurface({}, min_target_confidence=0.90)

    points = []
    for level in (1, 3, 6):
        resolved = surface.resolve(
            ActionRequest("SET_RESOURCE_LEVEL", "SEARCH_LEVEL_CONTROL", {"resource_level": level}),
            scene=bundle.scene,
        )
        points.append(resolved.point)

    # The persisted training frames show handle centres at x=459, 505, 575;
    # y=546 is the vertical centre of the observed control.
    assert points == [(459, 546), (505, 546), (575, 546)]


def test_the_panel_moves_with_the_selected_category():
    """Measured live 2026-09-20 - this cost a whole run to find.

    The search panel is centred under whichever category icon is selected,
    and the icons sit exactly 142px apart. The slider profile was trained
    with Cropland (FOOD) selected, so on a WOOD run every trained coordinate
    was 142px left of the real control: the level-6 click, which lands at the
    right end of the track, came down on the NEXT panel's minus button and
    walked the level DOWN from 6 to 4.
    """
    from harness.resource_level_control import (
        CATEGORY_CENTRE_X,
        ResourceLevelProfile,
        category_offset,
    )

    spacings = sorted(CATEGORY_CENTRE_X.values())
    gaps = {b - a for a, b in zip(spacings, spacings[1:])}
    assert gaps == {142}, f"the category bar is evenly spaced; got {gaps}"

    assert category_offset("FOOD", 1366) == 0
    assert category_offset("WOOD", 1366) == 142
    assert category_offset(None, 1366) == 0
    assert category_offset("NOT_A_CATEGORY", 1366) == 0

    profile = ResourceLevelProfile.load(
        Path(__file__).resolve().parents[1] / "config" / "resource_level_profile.json"
    )
    food = profile.bbox(1366, 768, resource_type="FOOD")
    wood = profile.bbox(1366, 768, resource_type="WOOD")
    assert wood.x1 - food.x1 == 142
    assert wood.x2 - food.x2 == 142
    assert (wood.y1, wood.y2) == (food.y1, food.y2)


def test_a_panel_shifted_off_the_client_is_refused_not_clamped():
    """Clamping would click whatever control happens to be at the edge.

    Note the offset scales with the client width, so simply using a narrower
    window does NOT push the track off - both move together. What triggers it
    is a track trained near the right edge, which is why this constructs one
    rather than shrinking the client.
    """
    from harness.resource_level_control import (
        CONTROL_MODE,
        ResourceLevelProfile,
        ResourceLevelProfileError,
    )

    near_edge = ResourceLevelProfile(
        True, 1, 6, (0.90, 0.69, 0.98, 0.72), 0.95, ("SEARCH",), CONTROL_MODE
    )
    # FOOD is where it was trained, so it still fits.
    assert near_edge.bbox(1366, 768, resource_type="FOOD").x2 <= 1366
    with pytest.raises(ResourceLevelProfileError, match="outside the"):
        near_edge.bbox(1366, 768, resource_type="GOLD")
