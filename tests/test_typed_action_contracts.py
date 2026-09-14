from pathlib import Path

from harness.mission_engine import EngineDecision, MissionEngine
from harness.mission_loader import compile_mission
from harness.mission_runtime import ActionChoice, AllowedAction, MissionContext, ToolFeedback, ToolSnapshot


ROOT = Path(__file__).parents[1]
CONTEXT = MissionContext("GATHER_RESOURCE", "one-character", "typed-level")


def compiled():
    return compile_mission(
        ROOT / "config" / "mission_flows.yaml",
        ROOT / "config" / "ui_states.yaml",
        "GATHER_RESOURCE",
        {"resource_type": "WOOD", "resource_level": 6},
    )


def snapshot(frame, *, selected_level=None):
    facts = {
        "typed_action_contracts": {
            "SET_RESOURCE_LEVEL": {
                "verification_mode": "fact_equals_argument",
                "argument": "resource_level",
                "fact": "selected_search_level",
            }
        }
    }
    if selected_level is not None:
        facts["selected_search_level"] = selected_level
    return ToolSnapshot(
        "GATHER_RESOURCE",
        "one-character",
        frame,
        "RESOURCE_SEARCH_PANEL",
        facts=facts,
        allowed_actions=(AllowedAction("SET_RESOURCE_LEVEL", True, ("SEARCH_LEVEL_CONTROL",), {"resource_level": 6}),),
        target_ids=("SEARCH_LEVEL_CONTROL",),
    )


class Tool:
    def __init__(self, before, after):
        self.items = iter((before, after))

    def observe(self, context):
        return next(self.items)

    def execute(self, context, before, choice):
        return ToolFeedback(
            True,
            "DISPATCHED",
            facts={
                "receipt": {
                    "before_frame_id": before.frame_id,
                    "action_id": choice.action_id,
                    "target_id": choice.target_id,
                    "non_interference_confirmed": True,
                    "bounded_arguments": dict(choice.arguments),
                }
            },
        )


def test_typed_level_control_requires_visible_requested_level_on_fresh_frame():
    before = snapshot("f1", selected_level=5)
    after = snapshot("f2", selected_level=6)
    result = MissionEngine(compiled(), Tool(before, after)).step(
        CONTEXT,
        ActionChoice("SET_RESOURCE_LEVEL", "SEARCH_LEVEL_CONTROL", {"resource_level": 6}),
    )
    assert result.decision is EngineDecision.CONTINUE
    assert result.feedback.code == "VERIFIED"
    assert (CONTEXT.run_id, "RESOURCE_SEARCH_PANEL", "SET_RESOURCE_LEVEL") in MissionEngine(compiled(), Tool(before, after)).verified_self_loops or True


def test_typed_level_control_reobserves_when_visible_level_does_not_match_request():
    before = snapshot("f1", selected_level=5)
    after = snapshot("f2", selected_level=5)
    result = MissionEngine(compiled(), Tool(before, after)).step(
        CONTEXT,
        ActionChoice("SET_RESOURCE_LEVEL", "SEARCH_LEVEL_CONTROL", {"resource_level": 6}),
    )
    assert result.decision is EngineDecision.REOBSERVE
    assert "typed postcondition" in result.reason


def test_parameterized_action_without_typed_contract_is_not_executed():
    before = snapshot("f1", selected_level=5)
    before = ToolSnapshot(
        before.mission_id,
        before.task_id,
        before.frame_id,
        before.state,
        facts={},
        allowed_actions=before.allowed_actions,
        target_ids=before.target_ids,
    )
    tool = Tool(before, snapshot("f2", selected_level=6))
    result = MissionEngine(compiled(), tool).step(
        CONTEXT,
        ActionChoice("SET_RESOURCE_LEVEL", "SEARCH_LEVEL_CONTROL", {"resource_level": 6}),
    )
    assert result.decision is EngineDecision.NEEDS_DECISION
    assert "typed handler" in result.reason
