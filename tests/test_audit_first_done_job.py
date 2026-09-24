"""Audit a real five-slot runner replay without promoting synthetic proof live."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from harness.gather_job_authority import compiled_gather_catalog
from harness.gather_job_coordinator import GatherJobCoordinator
from harness.gather_job_store import JsonGatherJobStore, load_gather_job_authority
from harness.gather_replay_evidence import build_gather_tick_evidence, save_gather_tick_evidence
from harness.mission_loader import compile_mission
from harness.mission_runner import MissionRunner
from harness.mission_runtime import AllowedAction, MissionContext, ToolFeedback, ToolSnapshot
from harness.mission_store import CheckpointStatus, JsonMissionStore
from scripts.audit_first_done_job import audit_first_done_job, write_verdict
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


def replay(tmp_path):
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

    report = drive_job(synthetic_tick, job_id=job.job_id, max_ticks=5,
                       max_idle_ticks=0, idle_delay_seconds=0, settle_seconds=0,
                       sleeper=lambda _: None)
    assert report["status"] == "complete" and report["ticks"] == 5
    return job, ledger, checkpoints, report, evidence_root


def test_five_verified_journal_entries_and_frame_facts_pass_only_offline(tmp_path):
    job, ledger, checkpoints, driver, evidence_root = replay(tmp_path)
    verdict = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root)
    assert verdict["status"] == "OFFLINE_REPLAY_PASS", verdict["errors"]
    assert verdict["highest_proven_status"] == "IMPLEMENTED"
    assert verdict["first_done_live_proven"] is False
    assert verdict["mining_return_estimate"] is None
    assert len(verdict["checked_evidence_paths"]) == 5


def test_missing_or_forged_formation_or_driver_closeout_blocks(tmp_path):
    job, ledger, checkpoints, driver, evidence_root = replay(tmp_path)
    driver["history"].pop(2)
    verdict = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root)
    assert verdict["status"] == "BLOCKED"
    assert any("slot 3" in error for error in verdict["errors"])

    job, ledger, checkpoints, driver, evidence_root = replay(tmp_path / "second")
    path = Path(driver["history"][0]["evidence_path"])
    record = json.loads(path.read_text(encoding="utf-8"))
    record["engine"]["before_facts"]["new_troop_formation_ready"] = False
    path.write_text(json.dumps(record), encoding="utf-8")
    verdict = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root)
    assert verdict["status"] == "BLOCKED"
    assert any("slot 1" in error for error in verdict["errors"])

    driver["closeout"] = driver["closeout"][:-1]
    verdict = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root)
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
    verdict = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root)
    assert verdict["status"] == "BLOCKED"
    assert any("slot 2" in error for error in verdict["errors"])

    job, ledger, checkpoints, driver, evidence_root = replay(tmp_path / "client")
    path = Path(driver["history"][3]["evidence_path"])
    record = json.loads(path.read_text(encoding="utf-8"))
    record["engine"]["after_facts"]["window"]["pid"] += 1
    path.write_text(json.dumps(record), encoding="utf-8")
    verdict = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root)
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
    verdict = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root)
    assert verdict["status"] == "BLOCKED"
    assert any("slot 1 checkpoint proof" in error for error in verdict["errors"])


def test_driver_attempt_order_count_and_revocation_are_required(tmp_path):
    job, ledger, checkpoints, driver, evidence_root = replay(tmp_path)
    driver["ticks"] -= 1
    verdict = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root)
    assert verdict["status"] == "BLOCKED"
    assert any("driver attempt" in error for error in verdict["errors"])

    driver["ticks"] += 1
    driver["history"][0], driver["history"][1] = driver["history"][1], driver["history"][0]
    verdict = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root)
    assert verdict["status"] == "BLOCKED"
    assert any("driver attempt" in error for error in verdict["errors"])

    driver["history"].sort(key=lambda item: item["verified_marches"])
    ledger.revoke(job)
    verdict = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root)
    assert verdict["status"] == "BLOCKED"
    assert any("revoked" in error for error in verdict["errors"])


def test_unsupported_formation_source_cannot_pass_offline_audit(tmp_path):
    job, ledger, checkpoints, driver, evidence_root = replay(tmp_path)
    path = Path(driver["history"][0]["evidence_path"])
    record = json.loads(path.read_text(encoding="utf-8"))
    record["engine"]["before_facts"]["new_troop_formation_source"] = "untrusted_source"
    path.write_text(json.dumps(record), encoding="utf-8")
    verdict = audit_first_done_job(job, ledger, checkpoints, driver, evidence_root)
    assert verdict["status"] == "BLOCKED"
    assert any("slot 1" in error for error in verdict["errors"])
