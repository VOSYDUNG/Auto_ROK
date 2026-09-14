import json

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
    def observe(self, context):
        observation = Observation(
            1.0,
            "f1",
            (1000, 500),
            (
                Evidence("ocr", "SEARCH", 0.0, value="SEARCH", metadata={"frame_id": "f1"}),
                Evidence("ocr", "Cropland", 0.0, value="Cropland", metadata={"frame_id": "f1"}),
            ),
        )
        return ObservationBundle(
            observation,
            SceneGraph("f1", None, (), {"client_screen_rect": [100, 200, 1100, 700]}),
        )


def trained_profile(tmp_path):
    path = tmp_path / "level.json"
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
    return ResourceLevelProfile.load(path)


def test_untrained_profile_never_grounds_control(tmp_path):
    path = tmp_path / "level.json"
    path.write_text(json.dumps({"schema_version": 1, "status": "untrained"}), encoding="utf-8")
    bundle = ResourceLevelControlObservationProvider(FakeProvider(), ResourceLevelProfile.load(path)).observe(CONTEXT)
    assert bundle.scene.target("SEARCH_LEVEL_CONTROL") is None
    assert bundle.scene.facts["resource_level_control"]["status"] == "untrained"


def test_trained_profile_requires_current_search_anchors(tmp_path):
    bundle = ResourceLevelControlObservationProvider(FakeProvider(), trained_profile(tmp_path)).observe(CONTEXT)
    target = bundle.scene.require_target("SEARCH_LEVEL_CONTROL", 0.90)
    assert target.frame_id == "f1"
    assert target.source == "trained_resource_level_profile"
    assert bundle.scene.facts["resource_level_control"]["status"] == "grounded"


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
    # Track runs from client x=200..800; level 10 selects right edge (x=800).
    # Current client begins at screen x=100, y=200.
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
