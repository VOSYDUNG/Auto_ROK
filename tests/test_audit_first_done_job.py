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
from scripts import audit_first_done_job as audit_module


ROOT = Path(__file__).resolve().parents[1]
WINDOW = {"hwnd": 1001, "pid": 2001, "process_path": "C:/Game/MASS.exe"}
PRECONDITION = "troop/commander selection policy is valid for this mission"


class SyntheticMarchTool:
    def __init__(self, job, ledger, sequence, *, first_measured_zero=False):
        self.job, self.ledger, self.sequence = job, ledger, sequence
        self.first_measured_zero = first_measured_zero
        self.observations = 0
        self.start = datetime.now(timezone.utc).timestamp() + sequence * 3

    def observe(self, context):
        self.observations += 1
        if self.observations == 1:
            before = f"before-{self.sequence}"
            image_hash = f"{self.sequence:064x}"
            facts = {
                "character_id": self.job.character_id, "window": WINDOW,
                "image_sha256": image_hash, "new_troop_formation_ready": True,
                "new_troop_formation_source": "same_frame_new_troop_ocr_and_pixels_1366x768",
                "new_troop_formation_frame_id": before,
                "new_troop_formation_image_sha256": image_hash,
                "precondition_evidence": {PRECONDITION: True},
                "gather_job_id": self.job.job_id,
            }
            if self.sequence == 1 and self.first_measured_zero:
                facts.update(march_queue_used=0, march_queue_capacity=5,
                             march_queue_source="visible_ocr_queue_anchor",
                             captured_at=datetime.fromtimestamp(self.start, timezone.utc).isoformat())
            if self.sequence > 1:
                facts["completion_baseline"] = {
                    "predicate_id": "march_queue_used_increased", "counter_fact": "march_queue_used",
                    "counter_value": self.sequence - 1, "capacity": 5,
                    "source_frame_id": f"baseline-{self.sequence}",
                    "source": "visible_ocr_queue_anchor", "character_id": self.job.character_id,
                    "source_timestamp": self.start,
                }
            return ToolSnapshot(
                context.mission_id, context.task_id, before, "NEW_TROOP_SETUP",
                facts=facts,
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


def replay(tmp_path, *, max_ticks=5, first_measured_zero=False):
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
            compiled, SyntheticMarchTool(job, ledger, sequence, first_measured_zero=first_measured_zero), checkpoints,
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


def pending_chain_for_preflight(tmp_path):
    """A real offline runner dispatch with no numeric postcondition yet."""
    workspace = tmp_path / "workspace"
    now = datetime.now(timezone.utc)
    artifact = build_artifact(
        job_id="pending-audit", task_id="pending-task", character_id="pending-char",
        resource_type="FOOD", resource_level=5,
        starts_at=now - timedelta(minutes=1), expires_at=now + timedelta(minutes=30),
    )
    path = write_artifact(workspace / "jobs" / "job.json", workspace, artifact)
    compiled = compile_mission(ROOT / "config" / "mission_flows.yaml", ROOT / "config" / "ui_states.yaml",
                               "GATHER_RESOURCE", {"resource_type": "FOOD", "resource_level": 5})
    catalog = compiled_gather_catalog(compiled)
    job = load_gather_job_authority(path, canonical_actions=catalog.actions, expected_catalog_digest=catalog.digest)
    ledger, checkpoints = JsonGatherJobStore(workspace / "ledger"), JsonMissionStore(workspace / "checkpoints")
    ledger.bind_client(job, WINDOW)
    context = MissionContext(job.mission_id, job.task_id, gather_slot_run_id(job, 1))

    class PendingTool(SyntheticMarchTool):
        def observe(self, context):
            snapshot = super().observe(context)
            if self.observations == 2:
                facts = {key: value for key, value in snapshot.facts.items() if not key.startswith("march_queue")}
                return replace(snapshot, facts=facts)
            return snapshot

    tool = PendingTool(job, ledger, 1)
    tool.start = datetime.now(timezone.utc).timestamp()
    result = GatherJobCoordinator(job, ledger, checkpoints).tick(MissionRunner(compiled, tool, checkpoints))
    assert result.result.status is CheckpointStatus.REOBSERVE and not result.journaled_this_tick
    record = build_gather_tick_evidence(context=context, character_id=job.character_id, result=result.result,
                                       live_armed=False, policy_approval=None, main_view_profile_trained=True,
                                       resource_level_profile_trained=True)
    record["runtime"]["gather_job"] = {"job_id": job.job_id, "verified_marches": 0,
                                            "reserved_marches": 1, "journaled_this_tick": False}
    evidence_root = workspace / "evidence"
    evidence_path = save_gather_tick_evidence(evidence_root, record)
    root = workspace / "attempts"
    root.mkdir()
    start = {"schema_version": 1, "kind": "attempt_start", "job_id": job.job_id,
             "task_id": job.task_id, "character_id": job.character_id, "catalog_digest": job.catalog_digest,
             "attempt_sequence": 1, "startup_attestation_sha256": "a" * 64, "initial_verified": 0,
             "started_at": now.isoformat(), "previous_start_sha256": None, "previous_result_sha256": None}
    first_start = root / "attempt-000001.start.json"
    first_start.write_text(json.dumps(start), encoding="utf-8")
    tick = {"status": "reobserve", "run_id": context.run_id, "verified_marches": 0,
            "evidence_path": str(evidence_path)}
    report = {"job_id": job.job_id, "attempt_sequence": 1, "initial_verified": 0,
              "start_sha256": hashlib.sha256(first_start.read_bytes()).hexdigest(),
              "status": "suspended", "reason": "tick ceiling", "ticks": 1,
              "history": [tick], "verified_marches": 0,
              "recorded_at": (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()}
    first_result = root / "attempt-000001.result.json"
    first_result.write_text(json.dumps(report), encoding="utf-8")
    latest = {**start, "attempt_sequence": 2, "started_at": (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat(),
              "previous_start_sha256": hashlib.sha256(first_start.read_bytes()).hexdigest(),
              "previous_result_sha256": hashlib.sha256(first_result.read_bytes()).hexdigest()}
    (root / "attempt-000002.start.json").write_text(json.dumps(latest), encoding="utf-8")
    return job, ledger, checkpoints, context, evidence_root, root, evidence_path


def test_preflight_accepts_exact_pending_march_without_mutation(tmp_path):
    job, ledger, checkpoints, context, evidence_root, root, evidence_path = pending_chain_for_preflight(tmp_path)
    paths = [ledger._path(job), checkpoints._path(context), evidence_path, *root.glob("*.json")]
    before = {path: path.read_bytes() for path in paths}
    preflight_attempt_chain(job, ledger, checkpoints, root, evidence_root)
    assert before == {path: path.read_bytes() for path in paths}
    assert ledger.progress(job).dispatched_marches == 1
    assert ledger.progress(job).verified_marches == 0
    assert not (root / "attempt-000002.result.json").exists()


@pytest.mark.parametrize("damage", [
    "missing_pending", "complete", "foreign_run", "foreign_client", "foreign_character",
    "bad_receipt", "before_frame", "dispatch_sequence", "duplicate_reservation", "skipped_reservation",
    "revoked", "expired", "original_tick", "missing_tick", "duplicate_tick", "changed_action",
    "tampered_baseline", "tampered_hash", "original_attempt_time", "missing_reservation", "last_frame",
])
def test_preflight_rejects_unproven_pending_march(tmp_path, monkeypatch, damage):
    job, ledger, checkpoints, context, evidence_root, root, evidence_path = pending_chain_for_preflight(tmp_path)
    checkpoint_path, ledger_path = checkpoints._path(context), ledger._path(job)
    cp = json.loads(checkpoint_path.read_text())
    pending = cp["checkpoint"]["pending_verification"]
    raw = json.loads(ledger_path.read_text())
    evidence = json.loads(evidence_path.read_text())
    if damage == "missing_pending":
        cp["checkpoint"]["pending_verification"] = None
    elif damage == "complete":
        cp["checkpoint"]["status"] = "complete"
    elif damage == "foreign_run":
        cp["checkpoint"]["run_id"] = "foreign-run"
    elif damage == "foreign_client":
        pending["before_snapshot"]["facts"]["window"]["pid"] += 1
    elif damage == "foreign_character":
        pending["before_snapshot"]["facts"]["character_id"] = "foreign"
    elif damage == "bad_receipt":
        pending["feedback"]["facts"]["receipt"]["target_id"] = "NEW_TROOP"
    elif damage == "before_frame":
        pending["before_snapshot"]["frame_id"] = "foreign-frame"
    elif damage == "dispatch_sequence":
        pending["feedback"]["facts"]["gather_job_dispatch_sequence"] = 2
    elif damage == "duplicate_reservation":
        raw["reservations"].append(dict(raw["reservations"][0]))
    elif damage == "skipped_reservation":
        raw["reservations"][0]["sequence"] = 2
    elif damage == "missing_reservation":
        raw["reservations"] = []
    elif damage == "revoked":
        raw["revoked"] = True
    elif damage == "expired":
        class ExpiredClock(datetime):
            @staticmethod
            def now(_):
                return job.expires_at
        monkeypatch.setattr(audit_module, "datetime", ExpiredClock)
    elif damage == "original_tick":
        evidence["engine"]["feedback"]["facts"]["receipt"]["before_frame_id"] = "other-frame"
    elif damage == "missing_tick":
        evidence_path.unlink()
    elif damage in {"duplicate_tick", "original_attempt_time"}:
        result_path = root / "attempt-000001.result.json"
        report = json.loads(result_path.read_text())
        if damage == "duplicate_tick":
            report["history"].append(dict(report["history"][0]))
            report["ticks"] = 2
        else:
            report["recorded_at"] = (job.starts_at + timedelta(seconds=1)).isoformat()
        result_path.write_text(json.dumps(report), encoding="utf-8")
        start_path = root / "attempt-000002.start.json"
        start = json.loads(start_path.read_text())
        start["previous_result_sha256"] = hashlib.sha256(result_path.read_bytes()).hexdigest()
        start_path.write_text(json.dumps(start), encoding="utf-8")
    elif damage == "changed_action":
        pending["action"]["action_id"] = "CREATE_NEW_TROOP"
    elif damage == "tampered_baseline":
        pending["before_snapshot"]["facts"]["completion_baseline"]["capacity"] = 6
    elif damage == "tampered_hash":
        pending["before_snapshot"]["facts"]["image_sha256"] = "0" * 64
    elif damage == "last_frame":
        pending["last_observed_frame_id"] = "foreign-after-frame"
        cp["checkpoint"]["last_frame_id"] = "foreign-after-frame"
    checkpoint_path.write_text(json.dumps(cp), encoding="utf-8")
    ledger_path.write_text(json.dumps(raw), encoding="utf-8")
    if damage != "missing_tick":
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises((ValueError, RuntimeError)):
        preflight_attempt_chain(job, ledger, checkpoints, root, evidence_root)


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


def diagnostic_attempt_chain(tmp_path, monkeypatch, *, diagnostic_only=False, raw_output=False, zero_progress=False,
                             execution_exception=False):
    if zero_progress:
        # These negative cases test admission shape/order, not journal writes.
        # Keep their fixture free of synthetic March publication side effects.
        now = datetime.now(timezone.utc)
        workspace = tmp_path / "workspace"
        artifact = build_artifact(job_id="diagnostic-zero", task_id="diagnostic-task", character_id="diagnostic-char",
                                  resource_type="FOOD", resource_level=5, starts_at=now - timedelta(minutes=1),
                                  expires_at=now + timedelta(minutes=30))
        path = write_artifact(workspace / "jobs" / "job.json", workspace, artifact)
        compiled = compile_mission(ROOT / "config" / "mission_flows.yaml", ROOT / "config" / "ui_states.yaml",
                                   "GATHER_RESOURCE", {"resource_type": "FOOD", "resource_level": 5})
        catalog = compiled_gather_catalog(compiled)
        job = load_gather_job_authority(path, canonical_actions=catalog.actions, expected_catalog_digest=catalog.digest)
        ledger, checkpoints = JsonGatherJobStore(workspace / "ledger"), JsonMissionStore(workspace / "checkpoints")
        evidence_root, root = workspace / "evidence", workspace / "attempts"
        root.mkdir()
        second_start = root / "attempt-000001.start.json"
        second_start.write_text(json.dumps({
            "schema_version": 1, "kind": "attempt_start", "job_id": job.job_id,
            "task_id": job.task_id, "character_id": job.character_id, "catalog_digest": job.catalog_digest,
            "attempt_sequence": 1, "startup_attestation_sha256": "a" * 64, "initial_verified": 0,
            "started_at": now.isoformat(), "previous_start_sha256": None, "previous_result_sha256": None,
        }), encoding="utf-8")
    else:
        job, ledger, checkpoints, evidence_root, root, _, second_start = partial_chain_for_preflight(tmp_path)
    start = json.loads(second_start.read_text())
    initial = start["initial_verified"]
    if raw_output:
        # Historical subprocess diagnostics remain auditable after the live
        # driver switched to a retained in-process session. Test the archived
        # envelope, not a removed execution adapter.
        diagnostic = (7, {
            "status": "failed", "error": "tick emitted no JSON result",
            "stdout": "not JSON", "stderr": ("traceback" + "x" * 5000)[-4096:],
            "stdout_truncated": False, "stderr_truncated": True,
        })
    else:
        diagnostic = (2, {"status": "failed", "error": {
            "type": "LiveObservationError", "message": "[WinError 5] Access is denied: OCR publication",
        }})
    ticks = [] if diagnostic_only else [(0, {
        "status": "running", "gather_job_id": job.job_id,
        "run_id": gather_slot_run_id(job, initial + 1), "gather_job_verified_marches": initial,
    })]
    stream = iter(ticks + [diagnostic])
    def returned_tick():
        if execution_exception:
            raise ValueError("job host preflight needs recovery evidence")
        return next(stream)
    report = drive_job(returned_tick, job_id=job.job_id, max_ticks=3, max_idle_ticks=0,
                       idle_delay_seconds=0, settle_seconds=0, sleeper=lambda _: None)
    assert report["status"] == "failed"
    recorded = datetime.fromisoformat(start["started_at"]) + timedelta(seconds=1)
    report.update(attempt_sequence=start["attempt_sequence"], initial_verified=initial,
                  start_sha256=hashlib.sha256(second_start.read_bytes()).hexdigest(),
                  recorded_at=recorded.isoformat())
    result_path = second_start.with_name(second_start.name.replace(".start.json", ".result.json"))
    result_path.write_text(json.dumps(report), encoding="utf-8")
    latest_path = root / f"attempt-{start['attempt_sequence'] + 1:06d}.start.json"
    latest = {**start, "attempt_sequence": start["attempt_sequence"] + 1, "started_at": (recorded + timedelta(seconds=1)).isoformat(),
              "previous_start_sha256": hashlib.sha256(second_start.read_bytes()).hexdigest(),
              "previous_result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest()}
    latest_path.write_text(json.dumps(latest), encoding="utf-8")
    return job, ledger, checkpoints, evidence_root, root, result_path, latest_path


def test_empty_driver_exception_preserves_chain_without_granting_progress(tmp_path, monkeypatch):
    job, ledger, checkpoints, evidence_root, root, result_path, _ = diagnostic_attempt_chain(
        tmp_path, monkeypatch, diagnostic_only=True, zero_progress=True, execution_exception=True)
    before = {path: path.read_bytes() for path in root.glob("*.json")}
    history, errors = audit_module._attempt_chain_history(
        job, ledger, checkpoints, None, root, evidence_root, [], allow_open_tail=True)
    assert history == [] and errors == []
    preflight_attempt_chain(job, ledger, checkpoints, root, evidence_root)
    assert ledger.progress(job).dispatched_marches == ledger.progress(job).verified_marches == 0
    assert before == {path: path.read_bytes() for path in before}
    assert json.loads(result_path.read_text())["verified_marches"] is None


@pytest.mark.parametrize("damage", ["progress", "closeout", "tick_count", "status", "reason",
                                    "extra_action", "extra_evidence", "initial", "start_hash"])
def test_empty_driver_exception_rejects_added_authority(tmp_path, monkeypatch, damage):
    job, ledger, checkpoints, evidence_root, root, result_path, latest_path = diagnostic_attempt_chain(
        tmp_path, monkeypatch, diagnostic_only=True, zero_progress=True, execution_exception=True)
    report = json.loads(result_path.read_text())
    if damage == "progress": report["verified_marches"] = 1
    elif damage == "closeout": report["closeout"] = [{"sequence": 1}]
    elif damage == "tick_count": report["ticks"] = True
    elif damage == "status": report["status"] = "suspended"
    elif damage == "reason": report["reason"] = "arbitrary failure"
    elif damage == "extra_action": report["action"] = "MARCH_WITH_CURRENT_SELECTION"
    elif damage == "extra_evidence": report["evidence_path"] = "invented.json"
    elif damage == "initial": report["initial_verified"] = 1
    elif damage == "start_hash": report["start_sha256"] = "b" * 64
    result_path.write_text(json.dumps(report), encoding="utf-8")
    latest = json.loads(latest_path.read_text())
    latest["previous_result_sha256"] = hashlib.sha256(result_path.read_bytes()).hexdigest()
    latest_path.write_text(json.dumps(latest), encoding="utf-8")
    with pytest.raises(ValueError, match="preflight blocked"):
        preflight_attempt_chain(job, ledger, checkpoints, root, evidence_root)


@pytest.mark.parametrize("diagnostic_only,raw_output", [(False, False), (True, False), (True, True)])
def test_preflight_accepts_exact_driver_failure_diagnostic_without_progress(tmp_path, monkeypatch, diagnostic_only, raw_output):
    job, ledger, checkpoints, evidence_root, root, result_path, latest_path = diagnostic_attempt_chain(
        tmp_path, monkeypatch, diagnostic_only=diagnostic_only, raw_output=raw_output)
    before = {path: path.read_bytes() for path in root.glob("*.json")}
    ledger_before = ledger._path(job).read_bytes()
    report = json.loads(result_path.read_text())
    assert report["verified_marches"] == (None if diagnostic_only else 2)
    history, errors = audit_module._attempt_chain_history(
        job, ledger, checkpoints, None, root, evidence_root, list(ledger.verifications(job)), allow_open_tail=True)
    assert errors == []
    assert all(tick["status"] != "failed" for tick in history)
    assert len([tick for tick in history if tick["status"] == "complete"]) == 2
    preflight_attempt_chain(job, ledger, checkpoints, root, evidence_root)
    assert before == {path: path.read_bytes() for path in before}
    assert ledger._path(job).read_bytes() == ledger_before
    assert not latest_path.with_name("attempt-000003.result.json").exists()


@pytest.mark.parametrize("damage", [
    "middle", "suspended", "complete", "code_zero", "code_bool", "missing_error", "error_not_object",
    "error_type", "error_message", "error_extra", "duplicate", "reason", "forged_progress",
    "diagnostic_run", "diagnostic_job", "diagnostic_count", "diagnostic_evidence", "diagnostic_choice",
    "stdout_oversized", "stdout_flag", "initial_verified", "only_forged_progress", "bound_foreign_run",
])
def test_preflight_rejects_forged_driver_failure_diagnostic(tmp_path, monkeypatch, damage):
    job, ledger, checkpoints, evidence_root, root, result_path, latest_path = diagnostic_attempt_chain(
        tmp_path, monkeypatch, diagnostic_only=damage == "only_forged_progress", zero_progress=True)
    report = json.loads(result_path.read_text())
    diagnostic = report["history"][-1]
    if damage == "middle":
        report["history"].reverse()
    elif damage in {"suspended", "complete"}:
        report["status"] = damage
    elif damage == "code_zero":
        diagnostic["exit_code"] = 0
    elif damage == "code_bool":
        diagnostic["exit_code"] = True
    elif damage == "missing_error":
        diagnostic.pop("error")
    elif damage == "error_not_object":
        diagnostic["error"] = "arbitrary error"
    elif damage == "error_type":
        diagnostic["error"]["type"] = None
    elif damage == "error_message":
        diagnostic["error"]["message"] = {"invented": True}
    elif damage == "error_extra":
        diagnostic["error"]["job_id"] = job.job_id
    elif damage == "duplicate":
        report["history"].append(dict(diagnostic))
        report["ticks"] += 1
    elif damage == "reason":
        report["reason"] = "tick execution failed: unrelated error"
    elif damage == "forged_progress":
        report["verified_marches"] = 3
    elif damage == "only_forged_progress":
        report["verified_marches"] = 2
    elif damage.startswith("diagnostic_"):
        key, value = {
            "diagnostic_run": ("run_id", gather_slot_run_id(job, 3)),
            "diagnostic_job": ("job_id", job.job_id),
            "diagnostic_count": ("verified_marches", 2),
            "diagnostic_evidence": ("evidence_path", "somewhere.json"),
            "diagnostic_choice": ("choice", {"action_id": "MARCH_WITH_CURRENT_SELECTION"}),
        }[damage]
        diagnostic[key] = value
    elif damage == "stdout_oversized":
        diagnostic.update(stdout="x" * 4097, stdout_truncated=True)
    elif damage == "stdout_flag":
        diagnostic.update(stdout="short", stdout_truncated="true")
    elif damage == "initial_verified":
        report["initial_verified"] = 3
    elif damage == "bound_foreign_run":
        report["history"][0]["run_id"] = "foreign"
    result_path.write_text(json.dumps(report), encoding="utf-8")
    latest = json.loads(latest_path.read_text())
    latest["previous_result_sha256"] = hashlib.sha256(result_path.read_bytes()).hexdigest()
    latest_path.write_text(json.dumps(latest), encoding="utf-8")
    with pytest.raises(ValueError, match="preflight blocked"):
        preflight_attempt_chain(job, ledger, checkpoints, root, evidence_root)


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


def test_first_measured_zero_uses_ordinal_and_passes_offline_audit(tmp_path):
    job, ledger, checkpoints, driver, evidence_root = replay(tmp_path, first_measured_zero=True)
    entry = ledger.verifications(job)[0]
    record = json.loads(Path(driver["history"][0]["evidence_path"]).read_text(encoding="utf-8"))
    assert record["engine"]["before_facts"]["march_queue_used"] == 0
    assert "counter_value" not in record["engine"]["before_facts"]["completion_baseline"]
    assert entry["before_source"] == "job_initial_slot_ordinal"
    verdict = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root, historical_replay=True)
    assert verdict["status"] == "OFFLINE_REPLAY_PASS", verdict["errors"]
    assert verdict["first_done_live_proven"] is False


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
