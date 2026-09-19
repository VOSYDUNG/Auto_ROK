from harness.alliance_state_classifier import AllianceClaimStateClassifier
from harness.contracts import Evidence, Observation
from harness.scene_graph import SceneGraph
from harness.state_classifier import AMBIGUOUS_STATE, UNKNOWN_STATE


FRAME = "frame-1"


def ev(text: str, *, frame_id: str = FRAME, source: str = "ocr") -> Evidence:
    return Evidence(source, text, 0.0, value=text, metadata={"frame_id": frame_id})


def classify(*items: Evidence, scene_frame: str = FRAME):
    observation = Observation(1.0, FRAME, (1280, 720), items)
    scene = SceneGraph(scene_frame, None)
    return AllianceClaimStateClassifier().classify(observation, scene)


def test_classifies_alliance_home_from_current_frame_anchors_case_insensitively():
    result = classify(ev("alliance"), ev("WAR"), ev("Territory"), ev("help"))
    assert result.state_id == "ALLIANCE_HOME"
    assert result.ambiguity["classifier"] == "alliance_claim"


def test_classifies_alliance_territory_from_trained_phrases():
    result = classify(
        ev("Alliance Territory", source="ocr_phrase"),
        ev("Territory Resource Earnings", source="ocr_phrase"),
        ev("Territory Buildings", source="ocr_phrase"),
    )
    assert result.state_id == "ALLIANCE_TERRITORY"


def test_classifies_main_view_evidence_produced_by_visual_detector():
    result = classify(
        ev("map terrain and world objects occupy central canvas", source="visual_signature"),
        ev("resource counters across top", source="visual_signature"),
        ev("bottom-right primary navigation is visible", source="visual_signature"),
    )
    assert result.state_id == "WORLD_MAP_VIEW"


def test_missing_or_stale_evidence_fails_closed():
    assert classify(ev("ALLIANCE"), ev("War")).state_id == UNKNOWN_STATE
    stale = classify(
        ev("ALLIANCE", frame_id="old"),
        ev("War", frame_id="old"),
        ev("Territory", frame_id="old"),
        ev("Help", frame_id="old"),
    )
    assert stale.state_id == UNKNOWN_STATE
    assert classify(
        ev("ALLIANCE"), ev("War"), ev("Territory"), ev("Help"), scene_frame="other-frame"
    ).state_id == UNKNOWN_STATE


def test_competing_state_evidence_is_ambiguous():
    result = classify(
        ev("ALLIANCE"),
        ev("War"),
        ev("Territory"),
        ev("Help"),
        ev("ALLIANCE TERRITORY", source="ocr_phrase"),
        ev("Territory Resource Earnings", source="ocr_phrase"),
        ev("Territory Buildings", source="ocr_phrase"),
    )
    assert result.state_id == AMBIGUOUS_STATE
    assert set(result.ambiguity["candidate_states"]) == {"ALLIANCE_HOME", "ALLIANCE_TERRITORY"}
