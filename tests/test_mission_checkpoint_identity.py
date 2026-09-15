from pathlib import Path

from harness.mission_loader import compile_mission
from harness.mission_runner import MissionRunner
from harness.mission_runtime import AllowedAction, MissionContext, ToolFeedback, ToolSnapshot
from harness.mission_store import CheckpointStatus, JsonMissionStore, MissionCheckpoint


ROOT = Path(__file__).parents[1]
MISSIONS = ROOT / "config" / "mission_flows.yaml"
STATES = ROOT / "config" / "ui_states.yaml"


def compiled(resource_type="WOOD", level=None):
    return compile_mission(
        MISSIONS,
        STATES,
        "GATHER_RESOURCE",
        {"resource_type": resource_type, "resource_level": level},
    )


class NeverTool:
    def observe(self, context):
        raise AssertionError("mismatched checkpoint must block before observation")

    def execute(self, context, before, choice):
        raise AssertionError("mismatched checkpoint must block before execution")


def test_same_run_id_cannot_resume_with_changed_parameters(tmp_path):
    context = MissionContext("GATHER_RESOURCE", "one-character", "stable-run", 0)
    store = JsonMissionStore(tmp_path)
    store.save(MissionCheckpoint(
        context.mission_id,
        context.task_id,
        context.run_id,
        context.attempt,
        parameters={"resource_type": "WOOD", "resource_level": None},
    ), expected_revision=0)

    result = MissionRunner(compiled("STONE", None), NeverTool(), store).tick(context)
    assert result.status is CheckpointStatus.BLOCKED
    assert "parameters differ" in result.reason
    assert result.checkpoint.revision == 1


def test_same_run_id_cannot_change_attempt_number(tmp_path):
    stored_context = MissionContext("GATHER_RESOURCE", "one-character", "stable-run", 0)
    store = JsonMissionStore(tmp_path)
    store.save(MissionCheckpoint(
        stored_context.mission_id,
        stored_context.task_id,
        stored_context.run_id,
        stored_context.attempt,
        parameters={"resource_type": "WOOD", "resource_level": None},
    ), expected_revision=0)

    requested = MissionContext("GATHER_RESOURCE", "one-character", "stable-run", 1)
    result = MissionRunner(compiled("WOOD", None), NeverTool(), store).tick(requested)
    assert result.status is CheckpointStatus.BLOCKED
    assert "attempt" in result.reason
