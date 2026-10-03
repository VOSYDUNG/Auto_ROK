import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from harness.gather_job_store import (
    GatherJobRevokedError, GatherJobStoreError, JsonGatherJobStore, load_gather_job_authority,
)
from harness.gather_job_authority import schedule_digest


NOW = datetime(2026, 9, 23, 8, tzinfo=timezone.utc)
ACTIONS = frozenset({"MARCH_WITH_CURRENT_SELECTION", "CREATE_NEW_TROOP"})
WINDOW = {"hwnd": 1001, "pid": 2001, "process_path": r"C:\Game\MASS.exe"}


def verified_entry(number):
    before, after = f"frame-{number}", f"after-{number}"
    return {
        "sequence": number, "job_id": "job-1", "run_id": f"run-{number}",
        "before_frame_id": before, "after_frame_id": after,
        "baseline_frame_id": before if number == 1 else f"queue-{number - 1}",
        "before_count": number - 1, "after_count": number, "capacity": 5,
        "before_source": "job_initial_slot_ordinal" if number == 1 else "visible_ocr_queue_anchor",
        "after_source": "visible_ocr_march_queue_region",
        "character_id": "character-1", "client_binding": {
            "hwnd": WINDOW["hwnd"], "pid": WINDOW["pid"],
            "process_path": WINDOW["process_path"].casefold(),
        },
        "before_observed_at": NOW.timestamp() + number * 3,
        "after_observed_at": NOW.timestamp() + number * 3 + 1,
        "verified_at": NOW.isoformat(),
        "receipt": {
            "action_id": "MARCH_WITH_CURRENT_SELECTION", "target_id": "TROOP_MARCH",
            "before_frame_id": before, "after_frame_id": after,
            "character_id": "character-1", "non_interference_confirmed": True,
        },
    }


def artifact():
    return {
        "schema_version": 1,
        "job_id": "job-1",
        "task_id": "task-1",
        "character_id": "character-1",
        "catalog_digest": "compiled-catalog-1",
        "starts_at": (NOW - timedelta(minutes=1)).isoformat(),
        "expires_at": (NOW + timedelta(minutes=20)).isoformat(),
        "allowed_actions": ["MARCH_WITH_CURRENT_SELECTION"],
        "max_marches": 5,
        "mission_id": "GATHER_RESOURCE",
    }


def load(tmp_path, data=None):
    path = tmp_path / "operator-job.json"
    path.write_text(json.dumps(artifact() if data is None else data), encoding="utf-8")
    return load_gather_job_authority(
        path, canonical_actions=ACTIONS, expected_catalog_digest="compiled-catalog-1")


def test_strict_artifact_load_and_malformed_scope(tmp_path):
    job = load(tmp_path)
    assert job.character_id == "character-1"
    assert job.allowed_actions == frozenset({"MARCH_WITH_CURRENT_SELECTION"})
    for change in (
        {"max_marches": True}, {"starts_at": "2026-09-23T08:00:00"},
        {"allowed_actions": ["MARCH_WITH_CURRENT_SELECTION", "CHANGE_PASSWORD"]},
        {"catalog_digest": "old"}, {"mission_id": "OTHER"},
        {"unknown_field": "x"},
    ):
        with pytest.raises(GatherJobStoreError):
            load(tmp_path, artifact() | change)
    with pytest.raises(GatherJobStoreError, match="duplicate JSON key"):
        path = tmp_path / "duplicate.json"
        path.write_text('{"job_id":"a","job_id":"b"}', encoding="utf-8")
        load_gather_job_authority(path, canonical_actions=ACTIONS,
                                  expected_catalog_digest="compiled-catalog-1")


@pytest.mark.parametrize('change', ['catalog', 'level'])
def test_mixed_schedule_cannot_adopt_existing_reservation(tmp_path, change):
    legacy = load(tmp_path)
    resources = ('GOLD', 'GOLD', 'WOOD', 'STONE', 'FOOD')
    catalogs = (legacy.catalog_digest,) * 5
    job = replace(legacy, schema_version=2, resource_schedule=resources,
        slot_catalog_digests=catalogs, resource_level=6,
        schedule_digest=schedule_digest(resources, catalogs, 6))
    store = JsonGatherJobStore(tmp_path / 'ledger')
    store.bind_client(job, WINDOW)
    store.reserve_dispatch(job, run_id='run-1', frame_id='frame-1',
        action='MARCH_WITH_CURRENT_SELECTION', now=NOW)
    ledger_path = store._path(job)
    before = ledger_path.read_bytes()
    changed_catalogs = catalogs if change == 'level' else catalogs[:1] + ('changed',) + catalogs[2:]
    changed_level = 7 if change == 'level' else 6
    changed = replace(job, slot_catalog_digests=changed_catalogs, resource_level=changed_level,
        schedule_digest=schedule_digest(resources, changed_catalogs, changed_level))
    with pytest.raises(GatherJobStoreError, match='conflicting'):
        JsonGatherJobStore(store.root).progress(changed)
    assert ledger_path.read_bytes() == before
    assert JsonGatherJobStore(store.root).progress(job).dispatched_marches == 1


def test_mixed_ledger_with_unbound_schedule_fails_without_migration(tmp_path):
    legacy = load(tmp_path)
    resources = ('GOLD', 'GOLD', 'WOOD', 'STONE', 'FOOD')
    catalogs = (legacy.catalog_digest,) * 5
    job = replace(legacy, schema_version=2, resource_schedule=resources,
        slot_catalog_digests=catalogs, resource_level=6,
        schedule_digest=schedule_digest(resources, catalogs, 6))
    store = JsonGatherJobStore(tmp_path / 'ledger')
    store.bind_client(job, WINDOW)
    ledger_path = store._path(job)
    raw = json.loads(ledger_path.read_text(encoding='utf-8'))
    for field in ('resource_schedule', 'slot_catalog_digests', 'resource_level', 'schedule_digest'):
        raw['scope'].pop(field)
    ledger_path.write_text(json.dumps(raw), encoding='utf-8')
    before = ledger_path.read_bytes()
    with pytest.raises(GatherJobStoreError, match='conflicting'):
        store.progress(job)
    assert ledger_path.read_bytes() == before


def test_five_verified_reservations_are_durable_and_bounded(tmp_path):
    job = load(tmp_path)
    store = JsonGatherJobStore(tmp_path / "ledger")
    assert store.progress(job).dispatched_marches == 0
    store.bind_client(job, WINDOW)
    for number in range(1, 6):
        entry = store.reserve_dispatch(job, run_id=f"run-{number}", frame_id=f"frame-{number}",
                                       action="MARCH_WITH_CURRENT_SELECTION", now=NOW)
        assert entry.sequence == number
        assert entry.run_id == f"run-{number}"
        assert store.progress(job).verified_marches == number - 1
        store.record_verified(job, verified_entry(number))
        reopened = JsonGatherJobStore(tmp_path / "ledger")
        assert reopened.progress(job).dispatched_marches == number
        assert reopened.progress(job).verified_marches == number
        assert len(reopened.reservations(job)) == number
    with pytest.raises(GatherJobStoreError, match="full"):
        store.reserve_dispatch(job, run_id="run-6", frame_id="frame-6",
                               action="MARCH_WITH_CURRENT_SELECTION", now=NOW)


@pytest.mark.parametrize("damage", ["prior_time", "reused_before", "reused_after"])
def test_cross_entry_time_and_transition_frames_must_advance(tmp_path, damage):
    job = load(tmp_path)
    store = JsonGatherJobStore(tmp_path / "ledger")
    store.bind_client(job, WINDOW)
    store.reserve_dispatch(job, run_id="run-1", frame_id="frame-1",
                           action="MARCH_WITH_CURRENT_SELECTION", now=NOW)
    store.record_verified(job, verified_entry(1))
    next_frame = "after-1" if damage == "reused_before" else "frame-2"
    store.reserve_dispatch(job, run_id="run-2", frame_id=next_frame,
                           action="MARCH_WITH_CURRENT_SELECTION", now=NOW)
    entry = verified_entry(2)
    if damage == "prior_time":
        entry["before_observed_at"] = verified_entry(1)["after_observed_at"]
    elif damage == "reused_before":
        entry["before_frame_id"] = "after-1"
        entry["receipt"]["before_frame_id"] = "after-1"
    else:
        entry["after_frame_id"] = "frame-1"
        entry["receipt"]["after_frame_id"] = "frame-1"
    with pytest.raises(GatherJobStoreError):
        store.record_verified(job, entry)
    assert JsonGatherJobStore(tmp_path / "ledger").progress(job).verified_marches == 1


def test_duplicate_frame_or_run_fail_without_consuming_slot(tmp_path):
    job = load(tmp_path)
    store = JsonGatherJobStore(tmp_path / "ledger")
    store.bind_client(job, WINDOW)
    store.reserve_dispatch(job, run_id="run-1", frame_id="frame-1",
                           action="MARCH_WITH_CURRENT_SELECTION", now=NOW)
    for run_id, frame_id in (("run-1", "frame-1"), ("run-1", "frame-2"),
                             ("run-2", "frame-1")):
        with pytest.raises(GatherJobStoreError):
            store.reserve_dispatch(job, run_id=run_id, frame_id=frame_id,
                                   action="MARCH_WITH_CURRENT_SELECTION", now=NOW)
    assert store.progress(job).dispatched_marches == 1


def test_revoke_persists_and_identity_conflict_fails_closed(tmp_path):
    job = load(tmp_path)
    store = JsonGatherJobStore(tmp_path / "ledger")
    store.bind_client(job, WINDOW)
    store.reserve_dispatch(job, run_id="run-1", frame_id="frame-1",
                           action="MARCH_WITH_CURRENT_SELECTION", now=NOW)
    assert store.revoke(job).revoked
    reopened = JsonGatherJobStore(tmp_path / "ledger")
    assert reopened.progress(job).revoked
    assert reopened.progress(job).dispatched_marches == 1
    with pytest.raises(GatherJobRevokedError):
        reopened.require_client(job, WINDOW)
    with pytest.raises(GatherJobStoreError):
        reopened.reserve_dispatch(job, run_id="run-1", frame_id="frame-2",
                                  action="MARCH_WITH_CURRENT_SELECTION", now=NOW)
    with pytest.raises(GatherJobStoreError, match="conflicting"):
        reopened.progress(replace(job, character_id="different-character"))


def test_uncertain_lock_and_corrupt_ledger_fail_closed(tmp_path):
    job = load(tmp_path)
    store = JsonGatherJobStore(tmp_path / "ledger")
    store.bind_client(job, WINDOW)
    store.reserve_dispatch(job, run_id="run-1", frame_id="frame-1",
                           action="MARCH_WITH_CURRENT_SELECTION", now=NOW)
    lock = store._path(job).with_suffix(".lock")
    lock.write_text("uncertain", encoding="utf-8")
    with pytest.raises(GatherJobStoreError, match="locked"):
        store.progress(job)
    with pytest.raises(GatherJobStoreError, match="locked"):
        store.reserve_dispatch(job, run_id="run-1", frame_id="frame-2",
                               action="MARCH_WITH_CURRENT_SELECTION", now=NOW)
    lock.unlink()
    store._path(job).write_text("{bad", encoding="utf-8")
    with pytest.raises(GatherJobStoreError):
        store.progress(job)
