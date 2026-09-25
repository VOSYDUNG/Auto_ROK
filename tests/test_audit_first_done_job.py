"""Audit a real five-slot runner replay without promoting synthetic proof live."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from harness.gather_job_authority import compiled_gather_catalog
from harness.gather_job_coordinator import GatherJobCoordinator, gather_slot_run_id
from harness.gather_job_store import JsonGatherJobStore, load_gather_job_authority
from harness.gather_replay_evidence import build_gather_tick_evidence, save_gather_tick_evidence
from harness.mission_loader import compile_mission
from harness.mission_runner import MissionRunner
from harness.mission_runtime import AllowedAction, MissionContext, ToolFeedback, ToolSnapshot
from harness.mission_store import CheckpointStatus, JsonMissionStore
from scripts.audit_first_done_job import audit_first_done_job, preflight_attempt_chain, write_verdict
from scripts.create_gather_job import build_artifact, write_artifact
from scripts.run_gather_job import drive_job


ROOT = Path(__file__).resolve().parents[1]
WINDOW = {"hwnd": 1001, "pid": 2001, "process_path": "C:/Game/MASS.exe"}
PRECONDITION = "troop/commander selection policy is valid for this mission"


class SyntheticMarchTool:
    def __init__(self, job, ledger, sequence):
        self.job, self.ledger, self.sequence = job, ledger, sequence
        self.observations = 0
        self.start = datetime.now(timezone.utc).timestamp() + sequence * 3

    def observe(self, context):
        self.observations += 1
        if self.observations == 1:
            before = f"before-{self.sequence}"
            image_hash = f"{self.sequence:064x}"
            baseline = {
                "predicate_id": "march_queue_used_increased", "counter_fact": "march_queue_used",
                "counter_value": self.sequence - 1, "capacity": 5,
                "source_frame_id": f"baseline-{self.sequence}",
                "source": "visible_ocr_queue_anchor", "character_id": self.job.character_id,
                "source_timestamp": self.start,
            }
            return ToolSnapshot(
                context.mission_id, context.task_id, before, "NEW_TROOP_SETUP",
                facts={
                    "character_id": self.job.character_id, "window": WINDOW,
                    "image_sha256": image_hash,
                    "new_troop_formation_ready": True,
                    "new_troop_formation_source": "same_frame_new_troop_ocr_and_pixels_1366x768",
                    "new_troop_formation_frame_id": before,
                    "new_troop_formation_image_sha256": image_hash,
                    "completion_baseline": baseline,
                    "precondition_evidence": {PRECONDITION: True},
                },
                allowed_actions=(AllowedAction("MARCH_WITH_CURRENT_SELECTION", True,
                                               ("TROOP_MARCH",)),),
                target_ids=("TROOP_MARCH",), observed_at=self.start,
            )
        if self.observations == 2:
            return ToolSnapshot(
                context.mission_id, context.task_id, f"after-{self.sequence}",
                "WORLD_MAP_VIEW",
                facts={"character_id": self.job.character_id, "window": WINDOW,
                       "image_sha256": f"{self.sequence + 100:064x}",
                       "march_queue_used": self.sequence, "march_queue_capacity": 5,
                       "march_queue_source": "visible_ocr_queue_anchor"},
                observed_at=self.start + 1,
            )
        raise AssertionError("synthetic runner must not spin")

    def execute(self, context, before, choice):
        reservation = self.ledger.reserve_dispatch(
            self.job, run_id=context.run_id, frame_id=before.frame_id,
            action=choice.action_id,
        )
        return ToolFeedback(True, "DISPATCHED", facts={
            "gather_job_id": self.job.job_id,
            "gather_job_dispatch_sequence": reservation.sequence,
            "receipt": {
                "action_id": choice.action_id, "target_id": choice.target_id,
                "before_frame_id": before.frame_id,
                "bounded_arguments": dict(choice.arguments),
                "character_id": self.job.character_id,
                "non_interference_confirmed": True,
            },
        })


def replay(tmp_path, *, max_ticks=5):
    workspace = tmp_path / "workspace"
    now = datetime.now(timezone.utc)
    artifact = build_artifact(
        job_id="synthetic-audit", task_id="task-audit", character_id="char-audit",
        resource_type="FOOD", resource_level=5,
        starts_at=now - timedelta(minutes=1), expires_at=now + timedelta(minutes=30),
    )
    job_path = write_artifact(workspace / "jobs" / "job.json", workspace, artifact)
    compiled = compile_mission(
        ROOT / "config" / "mission_flows.yaml", ROOT / "config" / "ui_states.yaml",
        "GATHER_RESOURCE", {"resource_type": "FOOD", "resource_level": 5},
    )
    catalog = compiled_gather_catalog(compiled)
    job = load_gather_job_authority(
        job_path, canonical_actions=catalog.actions,
        expected_catalog_digest=catalog.digest,
    )
    ledger = JsonGatherJobStore(workspace / "ledger")
    checkpoints = JsonMissionStore(workspace / "checkpoints")
    coord = GatherJobCoordinator(job, ledger, checkpoints)
    ledger.bind_client(job, WINDOW)
    evidence_root = workspace / "evidence"
    def synthetic_tick():
        sequence = coord.plan().sequence
        assert sequence is not None
        run_id = coord.plan().run_id
        context = MissionContext(job.mission_id, job.task_id, run_id)
        result = coord.tick(MissionRunner(
            compiled, SyntheticMarchTool(job, ledger, sequence), checkpoints,
        ))
        assert result.result.status is CheckpointStatus.COMPLETE
        assert result.journaled_this_tick and result.error is None
        record = build_gather_tick_evidence(
            context=context, character_id=job.character_id, result=result.result,
            live_armed=False, policy_approval=None, main_view_profile_trained=True,
            resource_level_profile_trained=True,
        )
        record["runtime"]["gather_job"] = {
            "job_id": job.job_id, "verified_marches": sequence,
            "journaled_this_tick": True, "closed_at_five": sequence == 5,
        }
        path = save_gather_tick_evidence(evidence_root, record)
        return 0, {
            "status": "complete", "run_id": run_id, "gather_job_id": job.job_id,
            "gather_job_verified_marches": sequence,
            "gather_job_closed_at_five": sequence == 5,
            "gather_job_closeout": list(coord.plan().closeout) if sequence == 5 else None,
            "gather_job_journaled_this_tick": True, "evidence_path": str(path),
        }

    report = drive_job(synthetic_tick, job_id=job.job_id, max_ticks=max_ticks,
                       max_idle_ticks=0, idle_delay_seconds=0, settle_seconds=0,
                       sleeper=lambda _: None)
    assert report["ticks"] == max_ticks
    assert report["status"] == ("complete" if max_ticks == 5 else "suspended")
    return job, ledger, checkpoints, report, evidence_root


def attempt_chain(tmp_path, *, orphan_second=False):
    job, ledger, checkpoints, report, evidence_root = replay(tmp_path)
    root = tmp_path / "workspace" / "attempts"
    root.mkdir(parents=True)
    instant = datetime.now(timezone.utc)
    # The replay builds all durable slots first. Project their verification
    # wall-times into the two synthetic attempt windows being audited below.
    journal_path = ledger._path(job)
    journal_record = json.loads(journal_path.read_text(encoding="utf-8"))
    for entry, seconds in zip(journal_record["verifications"], (0.2, 0.4, 2.2, 2.4, 2.6)):
        entry["verified_at"] = (instant + timedelta(seconds=seconds)).isoformat()
    journal_path.write_text(json.dumps(journal_record), encoding="utf-8")
    report["closeout"] = list(ledger.verifications(job))

    def put(name, record):
        path = root / name
        path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
        return path

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def start(sequence, initial, previous_start, previous_result, second):
        record = {
            "schema_version": 1, "kind": "attempt_start", "job_id": job.job_id,
            "task_id": job.task_id, "character_id": job.character_id,
            "catalog_digest": job.catalog_digest, "attempt_sequence": sequence,
            "startup_attestation_sha256": "a" * 64,
            "initial_verified": initial, "started_at": (instant + timedelta(seconds=second)).isoformat(),
            "previous_start_sha256": digest(previous_start) if previous_start else None,
            "previous_result_sha256": digest(previous_result) if previous_result else None,
        }
        return put(f"attempt-{sequence:06d}.start.json", record)

    def result(sequence, initial, first, last, status, start_path, second, *, recovered=False):
        value = dict(report)
        value.update({
            "status": status, "reason": ("durable five-march closeout recovered" if recovered
                                      else "five VERIFIED marches closed" if status == "complete"
                                      else "GATHER job tick ceiling reached"),
            "verified_marches": last, "history": report["history"][first:last],
            "ticks": last - first, "closeout": report["closeout"] if status == "complete" else None,
            "attempt_sequence": sequence, "initial_verified": initial,
            "start_sha256": digest(start_path),
            "recorded_at": (instant + timedelta(seconds=second)).isoformat(),
        })
        if recovered:
            value["history"] = [{"status": "complete", "run_id": None,
                                 "verified_marches": 5, "evidence_path": None}]
            value["ticks"] = 1
        return put(f"attempt-{sequence:06d}.result.json", value), value

    start1 = start(1, 0, None, None, 0)
    result1, _ = result(1, 0, 0, 2, "suspended", start1, 1)
    start2 = start(2, 2, start1, result1, 2)
    if orphan_second:
        start3 = start(3, 5, start2, None, 4)
        terminal_path, terminal = result(3, 5, 5, 5, "complete", start3, 5, recovered=True)
    else:
        terminal_path, terminal = result(2, 2, 2, 5, "complete", start2, 3)
    return job, ledger, checkpoints, terminal, evidence_root, root, terminal_path


def partial_chain_for_preflight(tmp_path):
    job, ledger, checkpoints, report, evidence_root = replay(tmp_path, max_ticks=2)
    root = tmp_path / "workspace" / "attempts"
    root.mkdir(parents=True)
    instant = datetime.now(timezone.utc)
    journal_path = ledger._path(job)
    journal_record = json.loads(journal_path.read_text(encoding="utf-8"))
    for entry, seconds in zip(journal_record["verifications"], (0.2, 0.4)):
        entry["verified_at"] = (instant + timedelta(seconds=seconds)).isoformat()
    journal_path.write_text(json.dumps(journal_record), encoding="utf-8")

    def put(name, value):
        path = root / name
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        return path

    first_start = put("attempt-000001.start.json", {
        "schema_version": 1, "kind": "attempt_start", "job_id": job.job_id,
        "task_id": job.task_id, "character_id": job.character_id,
        "catalog_digest": job.catalog_digest, "attempt_sequence": 1,
        "startup_attestation_sha256": "a" * 64,
        "initial_verified": 0, "started_at": instant.isoformat(),
        "previous_start_sha256": None, "previous_result_sha256": None,
    })
    first_report = dict(report)
    first_report.update({
        "recorded_at": (instant + timedelta(seconds=1)).isoformat(),
        "attempt_sequence": 1, "initial_verified": 0,
        "start_sha256": hashlib.sha256(first_start.read_bytes()).hexdigest(),
    })
    first_result = put("attempt-000001.result.json", first_report)
    second_start = put("attempt-000002.start.json", {
        "schema_version": 1, "kind": "attempt_start", "job_id": job.job_id,
        "task_id": job.task_id, "character_id": job.character_id,
        "catalog_digest": job.catalog_digest, "attempt_sequence": 2,
        "startup_attestation_sha256": "a" * 64,
        "initial_verified": 2,
        "started_at": (instant + timedelta(seconds=2)).isoformat(),
        "previous_start_sha256": hashlib.sha256(first_start.read_bytes()).hexdigest(),
        "previous_result_sha256": hashlib.sha256(first_result.read_bytes()).hexdigest(),
    })
    return job, ledger, checkpoints, evidence_root, root, first_result, second_start


@pytest.mark.parametrize("orphan_second", [False, True])
def test_ordered_attempt_chain_and_exact_durable_bridge_pass_offline(tmp_path, orphan_second):
    job, ledger, checkpoints, terminal, evidence_root, root, _ = attempt_chain(
        tmp_path, orphan_second=orphan_second,
    )
    verdict = audit_first_done_job(
        job, ledger, checkpoints, terminal, evidence_root, attempt_root=root,
    )
    assert verdict["status"] == "OFFLINE_REPLAY_PASS", verdict["errors"]
    assert len(verdict["checked_evidence_paths"]) == 5


@pytest.mark.parametrize("damage", [
    "missing", "duplicate", "reordered", "foreign", "edited", "stale",
    "attestation", "failed",
])
def test_attempt_chain_damage_blocks_closeout(tmp_path, damage):
    job, ledger, checkpoints, terminal, evidence_root, root, _ = attempt_chain(tmp_path)
    first = root / "attempt-000001.result.json"
    second_start = root / "attempt-000002.start.json"
    if damage == "missing":
        first.unlink()
    elif damage == "duplicate":
        shutil.copyfile(first, root / "attempt-000001.result-copy.json")
    elif damage == "reordered":
        terminal["history"].reverse()
        (root / "attempt-000002.result.json").write_text(json.dumps(terminal), encoding="utf-8")
    elif damage == "foreign":
        value = json.loads(second_start.read_text(encoding="utf-8"))
        value["job_id"] = "foreign-job"
        second_start.write_text(json.dumps(value), encoding="utf-8")
    elif damage == "edited":
        value = json.loads(first.read_text(encoding="utf-8"))
        value["reason"] = "edited after next attempt started"
        first.write_text(json.dumps(value), encoding="utf-8")
    elif damage == "stale":
        value = json.loads(second_start.read_text(encoding="utf-8"))
        value["started_at"] = (job.starts_at - timedelta(seconds=1)).isoformat()
        second_start.write_text(json.dumps(value), encoding="utf-8")
    elif damage == "attestation":
        value = json.loads(second_start.read_text(encoding="utf-8"))
        value["startup_attestation_sha256"] = "b" * 64
        second_start.write_text(json.dumps(value), encoding="utf-8")
    else:
        value = json.loads(first.read_text(encoding="utf-8"))
        value["status"] = "failed"
        first.write_text(json.dumps(value), encoding="utf-8")
        next_start = json.loads(second_start.read_text(encoding="utf-8"))
        next_start["previous_result_sha256"] = hashlib.sha256(first.read_bytes()).hexdigest()
        second_start.write_text(json.dumps(next_start), encoding="utf-8")
    verdict = audit_first_done_job(
        job, ledger, checkpoints, terminal, evidence_root, attempt_root=root,
    )
    assert verdict["status"] == "BLOCKED"


@pytest.mark.parametrize("damage", ["missing", "ambiguous", "before_persistence"])
def test_unreported_attempt_needs_unique_persisted_tick_artifact(tmp_path, damage):
    job, ledger, checkpoints, terminal, evidence_root, root, _ = attempt_chain(
        tmp_path, orphan_second=True,
    )
    run_id = terminal["closeout"][2]["run_id"]
    source = next(
        path for path in evidence_root.rglob("*.json")
        if json.loads(path.read_text(encoding="utf-8")).get("identity", {}).get("run_id") == run_id
    )
    if damage == "missing":
        source.unlink()
    elif damage == "ambiguous":
        shutil.copyfile(source, source.with_name("duplicate-matching-tick.json"))
    else:
        start = root / "attempt-000003.start.json"
        value = json.loads(start.read_text(encoding="utf-8"))
        value["initial_verified"] = 2
        start.write_text(json.dumps(value), encoding="utf-8")
    verdict = audit_first_done_job(
        job, ledger, checkpoints, terminal, evidence_root, attempt_root=root,
    )
    assert verdict["status"] == "BLOCKED"


def test_orphan_verified_time_must_belong_to_the_missing_result_attempt(tmp_path):
    job, ledger, checkpoints, terminal, evidence_root, root, _ = attempt_chain(
        tmp_path, orphan_second=True,
    )
    journal_path = ledger._path(job)
    raw = json.loads(journal_path.read_text(encoding="utf-8"))
    next_start = json.loads((root / "attempt-000003.start.json").read_text(encoding="utf-8"))
    raw["verifications"][2]["verified_at"] = (
        datetime.fromisoformat(next_start["started_at"]) + timedelta(milliseconds=1)
    ).isoformat()
    journal_path.write_text(json.dumps(raw), encoding="utf-8")
    terminal["closeout"] = list(ledger.verifications(job))
    verdict = audit_first_done_job(
        job, ledger, checkpoints, terminal, evidence_root, attempt_root=root,
    )
    assert verdict["status"] == "BLOCKED"
    assert any("outside orphan attempt" in error for error in verdict["errors"])


def test_preflight_accepts_unique_durable_orphan_bridge(tmp_path):
    job, ledger, checkpoints, evidence_root, root, first_result, second_start = (
        partial_chain_for_preflight(tmp_path)
    )
    first_result.unlink()
    start = json.loads(second_start.read_text(encoding="utf-8"))
    start["previous_result_sha256"] = None
    second_start.write_text(json.dumps(start), encoding="utf-8")
    preflight_attempt_chain(job, ledger, checkpoints, root, evidence_root)


@pytest.mark.parametrize("damage", ["edited", "failed", "foreign", "orphan_ambiguous", "orphan_late"])
def test_preflight_rejects_damaged_predecessor_before_next_tick(tmp_path, damage):
    job, ledger, checkpoints, evidence_root, root, first_result, second_start = (
        partial_chain_for_preflight(tmp_path)
    )
    preflight_attempt_chain(job, ledger, checkpoints, root, evidence_root)
    start = json.loads(second_start.read_text(encoding="utf-8"))
    if damage in {"edited", "failed"}:
        report = json.loads(first_result.read_text(encoding="utf-8"))
        if damage == "edited":
            report["reason"] = "edited after successor started"
        else:
            report["status"] = "failed"
        first_result.write_text(json.dumps(report), encoding="utf-8")
        if damage == "failed":
            start["previous_result_sha256"] = hashlib.sha256(first_result.read_bytes()).hexdigest()
    elif damage == "foreign":
        start["job_id"] = "other-job"
    else:
        first_result.unlink()
        start["previous_result_sha256"] = None
        if damage == "orphan_ambiguous":
            source = next(path for path in evidence_root.rglob("*.json") if
                          json.loads(path.read_text(encoding="utf-8")).get("identity", {}).get("run_id")
                          == gather_slot_run_id(job, 1))
            shutil.copyfile(source, source.with_name("duplicate-matching-tick.json"))
        else:
            journal_path = ledger._path(job)
            raw = json.loads(journal_path.read_text(encoding="utf-8"))
            raw["verifications"][1]["verified_at"] = (
                datetime.fromisoformat(start["started_at"]) + timedelta(milliseconds=1)
            ).isoformat()
            journal_path.write_text(json.dumps(raw), encoding="utf-8")
    second_start.write_text(json.dumps(start), encoding="utf-8")
    with pytest.raises(ValueError, match="attempt chain preflight blocked"):
        preflight_attempt_chain(job, ledger, checkpoints, root, evidence_root)


def test_five_verified_journal_entries_and_frame_facts_pass_only_offline(tmp_path):
    job, ledger, checkpoints, driver, evidence_root = replay(tmp_path)
    closeout = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root)
    assert closeout["status"] == "BLOCKED"
    assert any("durable attempt chain" in error for error in closeout["errors"])
    verdict = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root, historical_replay=True)
    assert verdict["status"] == "OFFLINE_REPLAY_PASS", verdict["errors"]
    assert verdict["audit_scope"] == "historical_replay_only"
    assert verdict["closeout_authoritative"] is False
    assert verdict["highest_proven_status"] == "IMPLEMENTED"
    assert verdict["first_done_live_proven"] is False
    assert verdict["mining_return_estimate"] is None
    assert len(verdict["checked_evidence_paths"]) == 5


def test_missing_or_forged_formation_or_driver_closeout_blocks(tmp_path):
    job, ledger, checkpoints, driver, evidence_root = replay(tmp_path)
    driver["history"].pop(2)
    verdict = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root, historical_replay=True)
    assert verdict["status"] == "BLOCKED"
    assert any("slot 3" in error for error in verdict["errors"])

    job, ledger, checkpoints, driver, evidence_root = replay(tmp_path / "second")
    path = Path(driver["history"][0]["evidence_path"])
    record = json.loads(path.read_text(encoding="utf-8"))
    record["engine"]["before_facts"]["new_troop_formation_ready"] = False
    path.write_text(json.dumps(record), encoding="utf-8")
    verdict = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root, historical_replay=True)
    assert verdict["status"] == "BLOCKED"
    assert any("slot 1" in error for error in verdict["errors"])

    driver["closeout"] = driver["closeout"][:-1]
    verdict = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root, historical_replay=True)
    assert verdict["status"] == "BLOCKED"
    assert any("driver attempt" in error for error in verdict["errors"])


def test_stale_baseline_or_changed_client_cannot_be_closeout_evidence(tmp_path):
    job, ledger, checkpoints, driver, evidence_root = replay(tmp_path / "stale")
    path = Path(driver["history"][1]["evidence_path"])
    record = json.loads(path.read_text(encoding="utf-8"))
    record["engine"]["before_facts"]["completion_baseline"]["source_timestamp"] = (
        record["engine"]["before_observed_at"] - 11
    )
    path.write_text(json.dumps(record), encoding="utf-8")
    verdict = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root, historical_replay=True)
    assert verdict["status"] == "BLOCKED"
    assert any("slot 2" in error for error in verdict["errors"])

    job, ledger, checkpoints, driver, evidence_root = replay(tmp_path / "client")
    path = Path(driver["history"][3]["evidence_path"])
    record = json.loads(path.read_text(encoding="utf-8"))
    record["engine"]["after_facts"]["window"]["pid"] += 1
    path.write_text(json.dumps(record), encoding="utf-8")
    verdict = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root, historical_replay=True)
    assert verdict["status"] == "BLOCKED"
    assert any("slot 4" in error for error in verdict["errors"])


def test_closeout_verdict_is_append_only_and_workspace_scoped(tmp_path):
    workspace = tmp_path / "workspace"
    output = workspace / "evidence" / "first-done-closeout.json"
    written = write_verdict(output, workspace, {"status": "OFFLINE_REPLAY_PASS"})
    original = written.read_bytes()
    with pytest.raises(FileExistsError):
        write_verdict(output, workspace, {"status": "BLOCKED"})
    assert written.read_bytes() == original
    with pytest.raises(ValueError, match="under workspace"):
        write_verdict(tmp_path / "outside.json", workspace, {"status": "BLOCKED"})


@pytest.mark.parametrize("part", ["queue", "receipt", "client", "timestamp"])
def test_checkpoint_proof_must_match_the_durable_journal(tmp_path, part):
    job, ledger, checkpoints, driver, evidence_root = replay(tmp_path)
    first = ledger.verifications(job)[0]
    context = MissionContext(job.mission_id, job.task_id, first["run_id"])
    checkpoint = checkpoints.load(context)
    assert checkpoint is not None and checkpoint.verified_transition is not None
    proof = json.loads(json.dumps(checkpoint.verified_transition))
    if part == "queue":
        proof["before_snapshot"]["facts"]["completion_baseline"]["counter_value"] = 1
        proof["after_snapshot"]["facts"]["march_queue_used"] = 2
    elif part == "receipt":
        proof["feedback"]["facts"]["receipt"]["target_id"] = "OTHER_TARGET"
    elif part == "client":
        proof["before_snapshot"]["facts"]["window"]["pid"] += 1
    else:
        proof["before_snapshot"]["observed_at"] += 0.2
    checkpoints.save(replace(checkpoint, verified_transition=proof),
                     expected_revision=checkpoint.revision)
    verdict = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root, historical_replay=True)
    assert verdict["status"] == "BLOCKED"
    assert any("slot 1 checkpoint proof" in error for error in verdict["errors"])


def test_driver_attempt_order_count_and_revocation_are_required(tmp_path):
    job, ledger, checkpoints, driver, evidence_root = replay(tmp_path)
    driver["ticks"] -= 1
    verdict = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root, historical_replay=True)
    assert verdict["status"] == "BLOCKED"
    assert any("driver attempt" in error for error in verdict["errors"])

    driver["ticks"] += 1
    driver["history"][0], driver["history"][1] = driver["history"][1], driver["history"][0]
    verdict = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root, historical_replay=True)
    assert verdict["status"] == "BLOCKED"
    assert any("driver attempt" in error for error in verdict["errors"])

    driver["history"].sort(key=lambda item: item["verified_marches"])
    ledger.revoke(job)
    verdict = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root, historical_replay=True)
    assert verdict["status"] == "BLOCKED"
    assert any("revoked" in error for error in verdict["errors"])


def test_unsupported_formation_source_cannot_pass_offline_audit(tmp_path):
    job, ledger, checkpoints, driver, evidence_root = replay(tmp_path)
    path = Path(driver["history"][0]["evidence_path"])
    record = json.loads(path.read_text(encoding="utf-8"))
    record["engine"]["before_facts"]["new_troop_formation_source"] = "untrusted_source"
    path.write_text(json.dumps(record), encoding="utf-8")
    verdict = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root, historical_replay=True)
    assert verdict["status"] == "BLOCKED"
    assert any("slot 1" in error for error in verdict["errors"])
