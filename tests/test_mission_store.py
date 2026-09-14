import json

import pytest

from harness.mission_runtime import MissionContext
from harness.mission_store import (
    CheckpointConflict,
    CheckpointStatus,
    JsonMissionStore,
    MissionCheckpoint,
)


CONTEXT = MissionContext("GATHER_RESOURCE", "one-character", "run-store")


def checkpoint(**changes):
    values = dict(
        mission_id=CONTEXT.mission_id,
        task_id=CONTEXT.task_id,
        run_id=CONTEXT.run_id,
        attempt=0,
        parameters={"resource_type": "WOOD", "resource_level": 6},
        status=CheckpointStatus.RUNNING,
        last_frame_id="f1",
        last_state="CITY_VIEW",
        verified_self_loops=(("run-store", "RESOURCE_SEARCH_PANEL", "SELECT_RESOURCE_TYPE"),),
    )
    values.update(changes)
    return MissionCheckpoint(**values)


def test_atomic_checkpoint_roundtrip_and_revision(tmp_path):
    store = JsonMissionStore(tmp_path)
    saved = store.save(checkpoint(), expected_revision=0)
    assert saved.revision == 1

    loaded = store.load(CONTEXT)
    assert loaded == saved
    assert loaded.verified_self_loops[0][2] == "SELECT_RESOURCE_TYPE"

    saved2 = store.save(
        checkpoint(status=CheckpointStatus.REOBSERVE, revision=1, last_frame_id="f2"),
        expected_revision=1,
    )
    assert saved2.revision == 2
    assert store.load(CONTEXT).last_frame_id == "f2"

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8"))["schema_version"] == 1
    assert list(tmp_path.glob("*.tmp")) == []


def test_compare_and_swap_rejects_stale_writer(tmp_path):
    store = JsonMissionStore(tmp_path)
    store.save(checkpoint(), expected_revision=0)
    with pytest.raises(CheckpointConflict):
        store.save(checkpoint(last_frame_id="stale"), expected_revision=0)


def test_completed_checkpoint_is_durable(tmp_path):
    store = JsonMissionStore(tmp_path)
    saved = store.save(checkpoint(status=CheckpointStatus.COMPLETE), expected_revision=0)
    assert store.load(CONTEXT).status is CheckpointStatus.COMPLETE
    assert saved.revision == 1
