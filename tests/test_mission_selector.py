from harness.mission_runtime import AllowedAction, MissionContext, ToolSnapshot
from harness.mission_selector import DeterministicMissionSelector, SelectionDecision
from harness.task_graph import TaskFlow, Transition


CONTEXT = MissionContext("GATHER_RESOURCE", "one-character", "run-1")


def snap(state, *, actions=(), targets=()):
    return ToolSnapshot(
        "GATHER_RESOURCE",
        "one-character",
        "frame-1",
        state,
        allowed_actions=actions,
        target_ids=targets,
    )


def test_single_action_is_auto_selected_without_model():
    flow = TaskFlow("GATHER_RESOURCE", (Transition("CITY_VIEW", "TOGGLE_CITY_MAP", ("WORLD_MAP_VIEW",)),))
    result = DeterministicMissionSelector().select(
        CONTEXT,
        snap("CITY_VIEW", actions=(AllowedAction("TOGGLE_CITY_MAP"),)),
        flow,
    )
    assert result.decision is SelectionDecision.AUTO
    assert result.choice.action_id == "TOGGLE_CITY_MAP"


def test_ordered_self_loops_are_consumed_before_advancing_edge():
    flow = TaskFlow(
        "GATHER_RESOURCE",
        (
            Transition("RESOURCE_SEARCH_PANEL", "SELECT_RESOURCE_TYPE", ("RESOURCE_SEARCH_PANEL",), requires_target=True, target_ids=("WOOD",)),
            Transition("RESOURCE_SEARCH_PANEL", "SET_RESOURCE_LEVEL", ("RESOURCE_SEARCH_PANEL",), requires_target=True, target_ids=("LEVEL",)),
            Transition("RESOURCE_SEARCH_PANEL", "SEARCH_RESOURCE_NODE", ("RESOURCE_POINT_DETAIL",), requires_target=True, target_ids=("SEARCH",)),
        ),
    )
    snapshot = snap(
        "RESOURCE_SEARCH_PANEL",
        actions=(
            AllowedAction("SELECT_RESOURCE_TYPE", True, ("WOOD",)),
            AllowedAction("SET_RESOURCE_LEVEL", True, ("LEVEL",)),
            AllowedAction("SEARCH_RESOURCE_NODE", True, ("SEARCH",)),
        ),
        targets=("WOOD", "LEVEL", "SEARCH"),
    )
    selector = DeterministicMissionSelector()

    first = selector.select(CONTEXT, snapshot, flow)
    assert first.choice.action_id == "SELECT_RESOURCE_TYPE"

    second = selector.select(
        CONTEXT,
        snapshot,
        flow,
        verified_self_loops=(("run-1", "RESOURCE_SEARCH_PANEL", "SELECT_RESOURCE_TYPE"),),
    )
    assert second.choice.action_id == "SET_RESOURCE_LEVEL"

    third = selector.select(
        CONTEXT,
        snapshot,
        flow,
        verified_self_loops=(
            ("run-1", "RESOURCE_SEARCH_PANEL", "SELECT_RESOURCE_TYPE"),
            ("run-1", "RESOURCE_SEARCH_PANEL", "SET_RESOURCE_LEVEL"),
        ),
    )
    assert third.choice.action_id == "SEARCH_RESOURCE_NODE"


def test_multiple_grounded_advancing_targets_require_bounded_decision():
    flow = TaskFlow(
        "X",
        (Transition("S", "CHOOSE", ("T",), requires_target=True, target_ids=("A", "B")),),
    )
    snapshot = ToolSnapshot(
        "GATHER_RESOURCE",
        "one-character",
        "frame",
        "S",
        allowed_actions=(AllowedAction("CHOOSE", True, ("A", "B")),),
        target_ids=("A", "B"),
    )
    result = DeterministicMissionSelector().select(CONTEXT, snapshot, flow)
    assert result.decision is SelectionDecision.NEEDS_DECISION
    assert {choice.target_id for choice in result.candidates} == {"A", "B"}


def test_missing_target_requests_reobservation_not_guess():
    flow = TaskFlow(
        "X",
        (Transition("S", "CLICK", ("T",), requires_target=True, target_ids=("A",)),),
    )
    snapshot = ToolSnapshot(
        "GATHER_RESOURCE",
        "one-character",
        "frame",
        "S",
        allowed_actions=(AllowedAction("CLICK", True, ("A",)),),
        target_ids=(),
    )
    result = DeterministicMissionSelector().select(CONTEXT, snapshot, flow)
    assert result.decision is SelectionDecision.REOBSERVE
