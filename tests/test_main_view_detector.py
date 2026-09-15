import json

from harness.contracts import Evidence, Observation
from harness.main_view_detector import (
    CITY_VIEW,
    WORLD_MAP_VIEW,
    MainViewProfile,
    MainViewVisualObservationProvider,
    classify_signature,
)
from harness.mission_runtime import MissionContext
from harness.mission_tool import ObservationBundle
from harness.scene_graph import SceneGraph


CONTEXT = MissionContext("GATHER_RESOURCE", "one-character", "run-main-view")


class FakeProvider:
    def __init__(self, image_path="frame.png", evidence=()):
        self.image_path = image_path
        self.evidence = tuple(evidence)

    def observe(self, context):
        return ObservationBundle(
            Observation(1.0, "f1", (1280, 720), self.evidence),
            SceneGraph("f1", None, (), {"image_path": self.image_path}),
        )


def profile(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "min_margin": 0.05,
                "prototypes": [
                    {"state_id": CITY_VIEW, "vector": [1.0, 0.0, 0.0], "max_distance": 0.10},
                    {"state_id": WORLD_MAP_VIEW, "vector": [0.0, 1.0, 0.0], "max_distance": 0.10},
                ],
            }
        ),
        encoding="utf-8",
    )
    return MainViewProfile.load(path)


def test_signature_classifier_matches_only_clear_trained_state(tmp_path):
    trained = profile(tmp_path)
    assert classify_signature([0.99, 0.01, 0.0], trained).state_id == CITY_VIEW
    assert classify_signature([0.01, 0.99, 0.0], trained).state_id == WORLD_MAP_VIEW


def test_signature_classifier_fails_closed_outside_threshold(tmp_path):
    trained = profile(tmp_path)
    result = classify_signature([0.0, 0.0, 1.0], trained)
    assert result.state_id is None
    assert result.reason == "best_match_outside_threshold"


def test_untrained_profile_emits_no_state_evidence(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps({"schema_version": 1, "prototypes": []}), encoding="utf-8")
    wrapper = MainViewVisualObservationProvider(
        FakeProvider(),
        MainViewProfile.load(path),
        extractor=lambda _: [1.0, 0.0],
    )
    bundle = wrapper.observe(CONTEXT)
    assert bundle.observation.evidence == ()
    assert bundle.scene.facts["main_view_detector"]["reason"] == "profile_untrained"


def test_visual_provider_appends_current_frame_city_evidence(tmp_path):
    wrapper = MainViewVisualObservationProvider(
        FakeProvider(),
        profile(tmp_path),
        extractor=lambda _: [1.0, 0.0, 0.0],
    )
    bundle = wrapper.observe(CONTEXT)
    labels = {item.label for item in bundle.observation.evidence}
    assert "city buildings occupy central world canvas" in labels
    assert "resource counters across top" in labels
    assert all(item.metadata["frame_id"] == "f1" for item in bundle.observation.evidence)
    assert bundle.scene.facts["main_view_detector"]["state_id"] == CITY_VIEW


def test_foreground_search_surface_suppresses_background_main_view_match(tmp_path):
    search = Evidence("ocr", "SEARCH", 0.0, value="SEARCH", metadata={"frame_id": "f1"})
    wrapper = MainViewVisualObservationProvider(
        FakeProvider(evidence=(search,)),
        profile(tmp_path),
        extractor=lambda _: [1.0, 0.0, 0.0],
    )
    bundle = wrapper.observe(CONTEXT)
    assert bundle.observation.evidence == (search,)
    assert bundle.scene.facts["main_view_detector"]["status"] == "suppressed"
    assert bundle.scene.facts["main_view_detector"]["reason"] == "foreground_gather_surface_visible"
