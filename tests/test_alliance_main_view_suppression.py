import json

from harness.contracts import Evidence, Observation
from harness.main_view_detector import MainViewProfile, MainViewVisualObservationProvider
from harness.mission_runtime import MissionContext
from harness.mission_tool import ObservationBundle
from harness.scene_graph import SceneGraph


CONTEXT = MissionContext("CLAIM_ALLIANCE_TERRITORY_RSS", "one-character", "run-alliance")


class FakeProvider:
    def __init__(self, evidence):
        self.evidence = tuple(evidence)

    def observe(self, context):
        return ObservationBundle(
            Observation(1.0, "f1", (1280, 720), self.evidence),
            SceneGraph("f1", None, (), {"image_path": "frame.png"}),
        )


def profile(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "min_margin": 0.05,
                "prototypes": [
                    {"state_id": "CITY_VIEW", "vector": [1.0, 0.0], "max_distance": 0.2},
                    {"state_id": "WORLD_MAP_VIEW", "vector": [0.0, 1.0], "max_distance": 0.2},
                ],
            }
        ),
        encoding="utf-8",
    )
    return MainViewProfile.load(path)


def test_alliance_home_marker_suppresses_underlying_city_match(tmp_path):
    marker = Evidence(
        "ocr_phrase",
        "Holy Sites",
        0.0,
        value="Holy Sites",
        metadata={"frame_id": "f1"},
    )
    wrapper = MainViewVisualObservationProvider(
        FakeProvider((marker,)),
        profile(tmp_path),
        extractor=lambda _: [1.0, 0.0],
    )
    bundle = wrapper.observe(CONTEXT)
    assert bundle.observation.evidence == (marker,)
    assert bundle.scene.facts["main_view_detector"]["status"] == "suppressed"
    assert "holy sites" in bundle.scene.facts["main_view_detector"]["foreground_markers"]


def test_alliance_territory_marker_suppresses_underlying_world_match(tmp_path):
    marker = Evidence(
        "ocr_phrase",
        "Territory Resource Earnings",
        0.0,
        value="Territory Resource Earnings",
        metadata={"frame_id": "f1"},
    )
    wrapper = MainViewVisualObservationProvider(
        FakeProvider((marker,)),
        profile(tmp_path),
        extractor=lambda _: [0.0, 1.0],
    )
    bundle = wrapper.observe(CONTEXT)
    assert bundle.observation.evidence == (marker,)
    assert bundle.scene.facts["main_view_detector"]["status"] == "suppressed"
    assert "territory resource earnings" in bundle.scene.facts["main_view_detector"]["foreground_markers"]
