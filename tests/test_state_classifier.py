from harness.contracts import Evidence, Observation
from harness.scene_graph import SceneGraph
from harness.state_classifier import AMBIGUOUS_STATE, UNKNOWN_STATE, StateClassifier


FRAME = "frame-01"


def observed(*values: str, frame_id: str = FRAME) -> Observation:
    return Observation(
        1.0,
        FRAME,
        (1280, 720),
        tuple(Evidence("semantic", value, 1.0, value=value, metadata={"frame_id": frame_id}) for value in values),
    )


def test_classifies_each_supported_gather_state() -> None:
    classifier = StateClassifier()
    cases = {
        "CITY_VIEW": ("city buildings occupy central world canvas", "resource counters across top", "primary circular navigation/actions at bottom-right", "quest/task list at left"),
        "WORLD_MAP_VIEW": ("map terrain and world objects occupy central canvas", "resource counters across top", "bottom-right primary navigation is visible"),
        "RESOURCE_SEARCH_PANEL": ("SEARCH", "Barbarians", "Cropland"),
        "RESOURCE_POINT_DETAIL": ("Resource Point", "GATHER"),
        "TROOP_DISPATCH_DRAWER": ("Dispatch a new troop from your city", "New Troop", "Queue X/5"),
        "NEW_TROOP_SETUP": ("New Troop", "MARCH", "Units", "Load"),
        "MARCH_IN_PROGRESS": ("used march count is greater than before dispatch", "troop/path indicator may be visible on map"),
    }
    for expected, values in cases.items():
        result = classifier.classify(observed(*values))
        assert result.state_id == expected
        assert len(result.matching_evidence) == len(values)
        assert result.ambiguity["candidate_states"] == (expected,)


def test_missing_evidence_is_unknown() -> None:
    result = StateClassifier().classify(observed("Resource Point"))
    assert result.state_id == UNKNOWN_STATE
    assert result.ambiguity["reason"] == "missing_current_frame_evidence"


def test_competing_complete_states_are_ambiguous() -> None:
    result = StateClassifier().classify(observed(
        "Resource Point", "GATHER", "SEARCH", "Barbarians", "Cropland"
    ))
    assert result.state_id == AMBIGUOUS_STATE
    assert result.ambiguity["candidate_states"] == ("RESOURCE_SEARCH_PANEL", "RESOURCE_POINT_DETAIL")


def test_stale_or_mismatched_frame_evidence_cannot_match() -> None:
    values = ("Resource Point", "GATHER")
    classifier = StateClassifier()
    assert classifier.classify(observed(*values, frame_id="old-frame")).state_id == UNKNOWN_STATE
    assert classifier.classify(observed(*values), SceneGraph("other-frame", None)).state_id == UNKNOWN_STATE
