from pathlib import Path

from harness.mission_engine import EngineDecision, MissionEngine
from harness.mission_loader import compile_mission
from harness.mission_runtime import ActionChoice, AllowedAction, MissionContext, ToolFeedback, ToolSnapshot
from harness.mission_selector import DeterministicMissionSelector, SelectionDecision


ROOT = Path(__file__).parents[1]
MISSIONS = ROOT / "config" / "mission_flows.yaml"
STATES = ROOT / "config" / "ui_states.yaml"
CONTEXT = MissionContext("CLAIM_ALLIANCE_TERRITORY_RSS", "one-character", "run-alliance-contract")


def compiled():
    return compile_mission(MISSIONS, STATES, "CLAIM_ALLIANCE_TERRITORY_RSS")


class Tool:
    def __init__(self, snapshots, feedback):
        self.snapshots = iter(snapshots)
        self.feedback = feedback
        self.executions = []

    def observe(self, context):
        return next(self.snapshots)

    def execute(self, context, before, choice):
        self.executions.append(choice)
        return self.feedback


def dispatched(before_frame, *, action_id, target_id=None):
    return ToolFeedback(
        True,
        "DISPATCHED",
        facts={
            "receipt": {
                "action_id": action_id,
                "target_id": target_id,
                "before_frame_id": before_frame,
                "bounded_arguments": {},
                "non_interference_confirmed": True,
            }
        },
        reobserve_required=True,
    )


def test_open_alliance_is_deterministic_from_both_main_views():
    flow = compiled().flow
    selector = DeterministicMissionSelector()
    for state in ("CITY_VIEW", "WORLD_MAP_VIEW"):
        snapshot = ToolSnapshot(
            CONTEXT.mission_id,
            CONTEXT.task_id,
            f"frame-{state}",
            state,
            allowed_actions=(AllowedAction("OPEN_ALLIANCE"),),
        )
        result = selector.select(CONTEXT, snapshot, flow)
        assert result.decision is SelectionDecision.AUTO
        assert result.choice == ActionChoice("OPEN_ALLIANCE")


def test_alliance_home_requires_current_grounded_territory_target():
    flow = compiled().flow
    selector = DeterministicMissionSelector()
    action = AllowedAction(
        "OPEN_ALLIANCE_TERRITORY",
        True,
        ("ALLIANCE_TERRITORY_ENTRY",),
    )
    missing = ToolSnapshot(
        CONTEXT.mission_id,
        CONTEXT.task_id,
        "f1",
        "ALLIANCE_HOME",
        allowed_actions=(action,),
        target_ids=(),
    )
    result = selector.select(CONTEXT, missing, flow)
    assert result.decision is SelectionDecision.REOBSERVE

    grounded = ToolSnapshot(
        CONTEXT.mission_id,
        CONTEXT.task_id,
        "f2",
        "ALLIANCE_HOME",
        allowed_actions=(action,),
        target_ids=("ALLIANCE_TERRITORY_ENTRY",),
    )
    result = selector.select(CONTEXT, grounded, flow)
    assert result.decision is SelectionDecision.AUTO
    assert result.choice == ActionChoice("OPEN_ALLIANCE_TERRITORY", "ALLIANCE_TERRITORY_ENTRY")


def test_claim_dispatch_requires_fresh_alliance_territory_post_observation():
    mission = compiled()
    action = AllowedAction(
        "CLAIM_ALLIANCE_TERRITORY_RSS",
        True,
        ("TERRITORY_RSS_CLAIM",),
    )
    before = ToolSnapshot(
        CONTEXT.mission_id,
        CONTEXT.task_id,
        "before",
        "ALLIANCE_TERRITORY",
        allowed_actions=(action,),
        target_ids=("TERRITORY_RSS_CLAIM",),
    )
    after = ToolSnapshot(
        CONTEXT.mission_id,
        CONTEXT.task_id,
        "after",
        "ALLIANCE_TERRITORY",
    )
    choice = ActionChoice("CLAIM_ALLIANCE_TERRITORY_RSS", "TERRITORY_RSS_CLAIM")
    engine = MissionEngine(
        mission,
        Tool(
            (before, after),
            dispatched(
                "before",
                action_id=choice.action_id,
                target_id=choice.target_id,
            ),
        ),
    )
    result = engine.step(CONTEXT, choice)

    assert result.decision is EngineDecision.CONTINUE
    assert result.after_snapshot is after
    assert result.feedback is not None and result.feedback.code == "VERIFIED"
    assert (CONTEXT.run_id, "ALLIANCE_TERRITORY", "CLAIM_ALLIANCE_TERRITORY_RSS") in engine.verified_self_loops


def test_claim_never_becomes_complete_without_post_claim_training():
    mission = compiled()
    action = AllowedAction(
        "CLAIM_ALLIANCE_TERRITORY_RSS",
        True,
        ("TERRITORY_RSS_CLAIM",),
    )
    before = ToolSnapshot(
        CONTEXT.mission_id,
        CONTEXT.task_id,
        "before",
        "ALLIANCE_TERRITORY",
        allowed_actions=(action,),
        target_ids=("TERRITORY_RSS_CLAIM",),
    )
    after = ToolSnapshot(
        CONTEXT.mission_id,
        CONTEXT.task_id,
        "after",
        "ALLIANCE_TERRITORY",
    )
    choice = ActionChoice("CLAIM_ALLIANCE_TERRITORY_RSS", "TERRITORY_RSS_CLAIM")
    engine = MissionEngine(
        mission,
        Tool(
            (before, after),
            dispatched("before", action_id=choice.action_id, target_id=choice.target_id),
        ),
    )
    result = engine.step(CONTEXT, choice)
    assert result.decision is not EngineDecision.COMPLETE

    next_snapshot = ToolSnapshot(
        CONTEXT.mission_id,
        CONTEXT.task_id,
        "later",
        "ALLIANCE_TERRITORY",
        allowed_actions=(action,),
        target_ids=("TERRITORY_RSS_CLAIM",),
    )
    selection = DeterministicMissionSelector().select(
        CONTEXT,
        next_snapshot,
        mission.flow,
        verified_self_loops=engine.verified_self_loops,
    )
    assert selection.decision is SelectionDecision.REOBSERVE
    assert "already verified" in selection.reason


def test_stale_post_claim_frame_is_rejected():
    mission = compiled()
    action = AllowedAction(
        "CLAIM_ALLIANCE_TERRITORY_RSS",
        True,
        ("TERRITORY_RSS_CLAIM",),
    )
    before = ToolSnapshot(
        CONTEXT.mission_id,
        CONTEXT.task_id,
        "same",
        "ALLIANCE_TERRITORY",
        allowed_actions=(action,),
        target_ids=("TERRITORY_RSS_CLAIM",),
    )
    after = ToolSnapshot(CONTEXT.mission_id, CONTEXT.task_id, "same", "ALLIANCE_TERRITORY")
    choice = ActionChoice("CLAIM_ALLIANCE_TERRITORY_RSS", "TERRITORY_RSS_CLAIM")
    result = MissionEngine(
        mission,
        Tool(
            (before, after),
            dispatched("same", action_id=choice.action_id, target_id=choice.target_id),
        ),
    ).step(CONTEXT, choice)
    assert result.decision is EngineDecision.REOBSERVE
    assert result.reason == "post-observation is not fresh"
