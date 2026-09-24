from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness.gather_job_authority import (
    GatherJobAuthority,
    GatherJobAuthorityError,
    GatherJobProgress,
    compiled_gather_catalog,
)
from harness.mission_loader import compile_mission
from harness.mission_runtime import MissionContext
from harness.troop_policy import TROOP_SELECTION_PRECONDITION


NOW = datetime(2026, 9, 23, 8, 0, tzinfo=timezone.utc)
CONTEXT = MissionContext("GATHER_RESOURCE", "round-1", "run-1")


def job():
    return GatherJobAuthority(
        job_id="farm-round-1",
        task_id="round-1",
        character_id="character-1",
        catalog_digest="compiled-gather-catalog",
        starts_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=20),
        allowed_actions=frozenset({"MARCH_WITH_CURRENT_SELECTION"}),
    )


def decision(**overrides):
    values = {
        "current_character_id": "character-1",
        "current_catalog_digest": "compiled-gather-catalog",
        "canonical_actions": frozenset({"MARCH_WITH_CURRENT_SELECTION"}),
        "frame_id": "frame-new-troop",
        "frame_timestamp": NOW.timestamp() - 1,
        "max_frame_age_seconds": 10,
        "target_ids": frozenset({"TROOP_MARCH"}),
        "progress": GatherJobProgress("farm-round-1", 0),
        "now": NOW,
    }
    values.update(overrides)
    return job().march_precondition(CONTEXT, **values)


def test_one_startup_job_covers_each_of_five_marches_without_b003():
    for dispatched in range(5):
        assert decision(progress=GatherJobProgress("farm-round-1", dispatched, verified_marches=dispatched)) == {
            TROOP_SELECTION_PRECONDITION: True
        }
    assert decision(progress=GatherJobProgress("farm-round-1", 5)) == {}


@pytest.mark.parametrize("overrides", [
    {"current_character_id": "other-character"},
    {"current_catalog_digest": "different-catalog"},
    {"canonical_actions": frozenset({"CREATE_NEW_TROOP"})},
    {"frame_id": ""},
    {"frame_timestamp": NOW.timestamp() - 30},
    {"frame_timestamp": NOW.timestamp() + 1},
    {"target_ids": frozenset()},
    {"progress": GatherJobProgress("other-job", 0)},
    {"progress": GatherJobProgress("farm-round-1", 0, revoked=True)},
    {"progress": GatherJobProgress("farm-round-1", 1, verified_marches=0)},
    {"now": NOW + timedelta(minutes=20)},
])
def test_job_precondition_fails_closed_for_wrong_or_stale_scope(overrides):
    assert decision(**overrides) == {}


def test_task_and_mission_must_match():
    assert job().march_precondition(
        MissionContext("GATHER_RESOURCE", "other-task", "run-1"),
        current_character_id="character-1",
        current_catalog_digest="compiled-gather-catalog",
        canonical_actions=frozenset({"MARCH_WITH_CURRENT_SELECTION"}),
        frame_id="f1",
        frame_timestamp=NOW.timestamp(),
        max_frame_age_seconds=10,
        target_ids=frozenset({"TROOP_MARCH"}),
        progress=GatherJobProgress("farm-round-1", 0),
        now=NOW,
    ) == {}


def test_bad_job_contract_rejected_without_requiring_24_hours():
    assert job().expires_at - job().starts_at < timedelta(hours=24)
    with pytest.raises(GatherJobAuthorityError):
        replace(job(), max_marches=6)
    with pytest.raises(GatherJobAuthorityError):
        replace(job(), starts_at=NOW.replace(tzinfo=None))
    with pytest.raises(GatherJobAuthorityError):
        replace(job(), allowed_actions=frozenset({"CHANGE_PASSWORD"}))
    with pytest.raises(GatherJobAuthorityError):
        GatherJobProgress("farm-round-1", -1)
    with pytest.raises(GatherJobAuthorityError):
        GatherJobProgress("farm-round-1", 1, verified_marches=2)


def test_out_of_catalog_action_cannot_be_granted_by_job_text():
    expanded = replace(
        job(),
        allowed_actions=frozenset({
            "MARCH_WITH_CURRENT_SELECTION", "CHANGE_PASSWORD",
        }),
    )
    assert expanded.march_precondition(
        CONTEXT,
        current_character_id="character-1",
        current_catalog_digest="compiled-gather-catalog",
        canonical_actions=frozenset({"MARCH_WITH_CURRENT_SELECTION"}),
        frame_id="f1",
        frame_timestamp=NOW.timestamp(),
        max_frame_age_seconds=10,
        target_ids=frozenset({"TROOP_MARCH"}),
        progress=GatherJobProgress("farm-round-1", 0),
        now=NOW,
    ) == {}


def test_catalog_digest_comes_from_compiled_gather_flow_and_parameters():
    root = Path(__file__).resolve().parents[1]
    flows = root / "config" / "mission_flows.yaml"
    states = root / "config" / "ui_states.yaml"
    food = compile_mission(flows, states, "GATHER_RESOURCE", {
        "resource_type": "FOOD", "resource_level": 5,
    })
    wood = compile_mission(flows, states, "GATHER_RESOURCE", {
        "resource_type": "WOOD", "resource_level": 5,
    })
    identity = compiled_gather_catalog(food)
    assert len(identity.digest) == 64
    assert identity.actions == frozenset(edge.action_id for edge in food.flow.transitions)
    assert "MARCH_WITH_CURRENT_SELECTION" in identity.actions
    assert compiled_gather_catalog(food) == identity
    assert compiled_gather_catalog(wood).digest != identity.digest
    altered = replace(food, transition_preconditions={})
    assert compiled_gather_catalog(altered).digest != identity.digest
    with pytest.raises(GatherJobAuthorityError):
        compiled_gather_catalog(replace(food, flow=replace(food.flow, flow_id="OTHER")))
