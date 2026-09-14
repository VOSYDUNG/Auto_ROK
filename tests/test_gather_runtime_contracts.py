from pathlib import Path

from harness.mission_engine import EngineDecision, MissionEngine
from harness.mission_loader import compile_mission
from harness.mission_runtime import ActionChoice, AllowedAction, MissionContext, ToolFeedback, ToolSnapshot


ROOT = Path(__file__).parents[1]
MISSIONS = ROOT / "config" / "mission_flows.yaml"
STATES = ROOT / "config" / "ui_states.yaml"
CONTEXT = MissionContext("GATHER_RESOURCE", "one-character", "run-contract")
PRECONDITION = "troop/commander selection policy is valid for this mission"


def compiled(level=6):
    return compile_mission(
        MISSIONS,
        STATES,
        "GATHER_RESOURCE",
        {"resource_type": "WOOD", "resource_level": level},
    )


class Tool:
    def __init__(self, snapshots, feedback=ToolFeedback(True, "VERIFIED")):
        self.snapshots = iter(snapshots)
        self.feedback = feedback
        self.executions = []

    def observe(self, context):
        return next(self.snapshots)

    def execute(self, context, before, choice):
        self.executions.append(choice)
        return self.feedback


def test_compiler_does_not_leak_mission_parameters_into_unrelated_actions():
    mission = compiled()
    select = mission.flow.transition_for("RESOURCE_SEARCH_PANEL", "SELECT_RESOURCE_TYPE")
    level = mission.flow.transition_for("RESOURCE_SEARCH_PANEL", "SET_RESOURCE_LEVEL")
    search = mission.flow.transition_for("RESOURCE_SEARCH_PANEL", "SEARCH_RESOURCE_NODE")
    assert select.arguments == {}
    assert level.arguments == {"resource_level": 6}
    assert search.arguments == {}


def test_parameterized_level_control_is_blocked_until_typed_handler_is_trained():
    action = AllowedAction(
        "SET_RESOURCE_LEVEL",
        True,
        ("SEARCH_LEVEL_CONTROL",),
        {"resource_level": 6},
    )
    before = ToolSnapshot(
        "GATHER_RESOURCE",
        "one-character",
        "f1",
        "RESOURCE_SEARCH_PANEL",
        allowed_actions=(action,),
        target_ids=("SEARCH_LEVEL_CONTROL",),
    )
    tool = Tool((before,))
    result = MissionEngine(compiled(), tool).step(
        CONTEXT,
        ActionChoice("SET_RESOURCE_LEVEL", "SEARCH_LEVEL_CONTROL", {"resource_level": 6}),
    )
    assert result.decision is EngineDecision.NEEDS_DECISION
    assert "typed handler" in result.reason
    assert tool.executions == []


def test_final_completion_predicate_can_finish_from_fresh_unclassified_post_frame():
    action = AllowedAction("MARCH_WITH_CURRENT_SELECTION", True, ("TROOP_MARCH",))
    before = ToolSnapshot(
        "GATHER_RESOURCE",
        "one-character",
        "f1",
        "NEW_TROOP_SETUP",
        facts={
            "march_queue_used": 0,
            "character_id": "hien",
            "precondition_evidence": {PRECONDITION: True},
        },
        allowed_actions=(action,),
        target_ids=("TROOP_MARCH",),
    )
    after = ToolSnapshot(
        "GATHER_RESOURCE",
        "one-character",
        "f2",
        "UNKNOWN_STATE",
        facts={"march_queue_used": 1, "character_id": "hien"},
    )
    feedback = ToolFeedback(
        True,
        "VERIFIED",
        facts={
            "receipt": {
                "before_frame_id": "f1",
                "after_frame_id": "f2",
                "character_id": "hien",
            }
        },
    )
    result = MissionEngine(compiled(), Tool((before, after), feedback)).step(
        CONTEXT,
        ActionChoice("MARCH_WITH_CURRENT_SELECTION", "TROOP_MARCH"),
    )
    assert result.decision is EngineDecision.COMPLETE
    assert result.after_snapshot.state == "UNKNOWN_STATE"
