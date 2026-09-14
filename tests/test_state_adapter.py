from harness.contracts import BoundingBox, Evidence, Observation
from harness.mission_runtime import MissionContext
from harness.scene_graph import SceneGraph, VisualTarget
from harness.state_adapter import to_game_state, to_tool_snapshot
from harness.state_classifier import StateClassification
from harness.task_graph import TaskFlow, Transition


def evidence(value, frame="f1", confidence=0.7):
    return Evidence("semantic", value, confidence, metadata={"frame_id": frame})


def scene(frame="f1"):
    return SceneGraph(frame, None, (VisualTarget("SEARCH_CATEGORY_WOOD", frame, "wood", BoundingBox(1, 2, 3, 4), .8, "ocr"),), {"x": 1})


def test_game_state_preserves_evidence_ambiguity_and_explicit_confidence():
    c = StateClassification("RESOURCE_SEARCH_PANEL", (evidence("SEARCH"),), {"candidate_states": ("RESOURCE_SEARCH_PANEL",), "confidence": .8})
    state = to_game_state(c)
    assert state.name == c.state_id and state.evidence == c.matching_evidence
    assert state.attributes["ambiguity"] == dict(c.ambiguity) and state.confidence == .8


def test_unknown_and_ambiguous_have_no_actions_and_no_invented_confidence():
    flow = TaskFlow("GATHER_RESOURCE", (Transition("RESOURCE_SEARCH_PANEL", "OPEN_SEARCH"),))
    ctx = MissionContext("m", "t", "r")
    for value in ("UNKNOWN_STATE", "AMBIGUOUS_STATE"):
        c = StateClassification(value)
        snap = to_tool_snapshot(ctx, c, scene(), flow)
        assert not snap.allowed_actions and to_game_state(c).confidence == 0


def test_compiled_surface_exposes_action_and_grounded_target():
    flow = TaskFlow("GATHER_RESOURCE", (Transition("RESOURCE_SEARCH_PANEL", "SELECT_RESOURCE_TYPE", target_ids=("SEARCH_CATEGORY_WOOD",), requires_target=True),))
    snap = to_tool_snapshot(MissionContext("m", "t", "r"), StateClassification("RESOURCE_SEARCH_PANEL"), scene(), flow)
    assert snap.allowed_actions[0].target_ids == ("SEARCH_CATEGORY_WOOD",)
    assert snap.target_ids == ("SEARCH_CATEGORY_WOOD",)


def test_mismatched_frame_fails():
    c = StateClassification("RESOURCE_SEARCH_PANEL", (evidence("SEARCH", "old"),))
    try:
        to_tool_snapshot(MissionContext("m", "t", "r"), c, scene(), TaskFlow("x", ()))
    except ValueError:
        pass
    else:
        raise AssertionError("stale evidence was accepted")
