"""Non-actuating audit of one five-march GATHER job's durable evidence.

A passing structural audit is not a live FIRST DONE claim. Native frame and
operator-interference provenance still require a separately scoped live pass.
The command reads job artifacts and writes only one append-only verdict file.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.gather_job_authority import GatherJobAuthority, compiled_gather_catalog  # noqa: E402
from harness.gather_job_coordinator import gather_slot_run_id  # noqa: E402
from harness.gather_job_store import GatherClientBinding, GatherJobStoreError, JsonGatherJobStore, load_gather_job_authority  # noqa: E402
from harness.gather_job_verification import record_verified_gather_tick  # noqa: E402
from harness.gather_replay_evidence import build_gather_tick_evidence  # noqa: E402
from harness.mission_loader import compile_mission  # noqa: E402
from harness.mission_runner import MissionTickResult, restore_verified_transition  # noqa: E402
from harness.mission_runtime import MissionContext  # noqa: E402
from harness.mission_store import CheckpointStatus, JsonMissionStore  # noqa: E402
from scripts.run_gather_tick import GATHER_JOB_MAX_FRAME_AGE_SECONDS  # noqa: E402


_FORMATION_SOURCE = "same_frame_new_troop_ocr_and_pixels_1366x768"


def _load_evidence(path: object, root: Path) -> Mapping[str, Any] | None:
    if not isinstance(path, str) or not path:
        return None
    source = Path(path).resolve()
    if not source.is_relative_to(root.resolve()):
        return None
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _valid_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(ch in "0123456789abcdef" for ch in value.lower()))


def _evidence_matches(entry: Mapping[str, Any], record: Mapping[str, Any],
                      job: GatherJobAuthority, expected_engine: Mapping[str, Any]) -> bool:
    identity = record.get("identity")
    runtime = record.get("runtime")
    engine = record.get("engine")
    if not all(isinstance(value, Mapping) for value in (identity, runtime, engine)):
        return False
    # The journal stores the compact transition, while the checkpoint stores
    # the complete Engine proof. Bind every projected fact in this artifact to
    # that proof; the non-semantic prose reason may differ after restoration.
    if ({key: value for key, value in engine.items() if key != "reason"}
            != {key: value for key, value in expected_engine.items() if key != "reason"}):
        return False
    job_runtime = runtime.get("gather_job")
    before, after = engine.get("before_facts"), engine.get("after_facts")
    feedback = engine.get("feedback")
    if not all(isinstance(value, Mapping) for value in (job_runtime, before, after, feedback)):
        return False
    baseline = before.get("completion_baseline")
    receipt = feedback.get("facts", {}).get("receipt") if isinstance(feedback.get("facts"), Mapping) else None
    choice = engine.get("choice")
    image_hash = before.get("image_sha256")
    after_hash = after.get("image_sha256")
    if not all(isinstance(value, Mapping) for value in (baseline, receipt, choice)):
        return False
    try:
        before_client = GatherClientBinding.from_window(before.get("window")).to_json()
        after_client = GatherClientBinding.from_window(after.get("window")).to_json()
    except (GatherJobStoreError, ValueError, TypeError):
        return False
    if (not _valid_sha256(image_hash) or not _valid_sha256(after_hash)
            or after_hash == image_hash):
        return False
    baseline_at = baseline.get("source_timestamp")
    before_at = engine.get("before_observed_at")
    if (not isinstance(baseline_at, (int, float)) or isinstance(baseline_at, bool)
            or not isinstance(before_at, (int, float)) or isinstance(before_at, bool)
            or not math.isfinite(baseline_at) or not math.isfinite(before_at)
            or not 0 <= before_at - baseline_at <= GATHER_JOB_MAX_FRAME_AGE_SECONDS):
        return False
    return (
        (identity.get("mission_id"), identity.get("task_id"), identity.get("run_id"),
         identity.get("character_id"))
        == (job.mission_id, job.task_id, entry["run_id"], job.character_id)
        and job_runtime.get("job_id") == job.job_id
        and job_runtime.get("verified_marches") == entry["sequence"]
        and job_runtime.get("journaled_this_tick") is True
        and engine.get("decision") == "complete"
        and feedback.get("success") is True and feedback.get("code") == "VERIFIED"
        and choice.get("action_id") == "MARCH_WITH_CURRENT_SELECTION"
        and choice.get("target_id") == "TROOP_MARCH"
        and engine.get("before_frame_id") == entry["before_frame_id"]
        and engine.get("after_frame_id") == entry["after_frame_id"]
        and engine.get("before_observed_at") == entry["before_observed_at"]
        and engine.get("after_observed_at") == entry["after_observed_at"]
        and before.get("new_troop_formation_ready") is True
        and before.get("new_troop_formation_source") == _FORMATION_SOURCE
        and before.get("new_troop_formation_frame_id") == entry["before_frame_id"]
        and before.get("new_troop_formation_image_sha256") == image_hash
        and before_client == entry["client_binding"]
        and after_client == entry["client_binding"]
        and baseline.get("source_frame_id") == entry["baseline_frame_id"]
        and baseline.get("counter_value") == entry["before_count"]
        and baseline.get("capacity") == 5
        and baseline.get("source") == entry["before_source"]
        and baseline.get("character_id") == job.character_id
        and after.get("march_queue_used") == entry["after_count"]
        and after.get("march_queue_capacity") == 5
        and after.get("march_queue_source") == entry["after_source"]
        and after.get("character_id") == job.character_id
        and all(receipt.get(key) == value for key, value in entry["receipt"].items())
    )


def _history_matches_job(job: GatherJobAuthority, history: list[object]) -> bool:
    """Require one ordered attempt that contains all five verified slots."""
    if len(history) < job.max_marches:
        return False
    verified = 0
    for item in history:
        if not isinstance(item, Mapping) or verified >= job.max_marches:
            return False
        status, count = item.get("status"), item.get("verified_marches")
        if (status not in {"running", "waiting", "reobserve", "complete"}
                or type(count) is not int
                or item.get("run_id") != gather_slot_run_id(job, verified + 1)):
            return False
        if status == "complete":
            if count != verified + 1:
                return False
            verified += 1
        elif count != verified:
            return False
    return verified == job.max_marches and history[-1].get("status") == "complete"


class _ProofJournalProjection:
    """Run the canonical verifier against a read-only capture of its output."""

    def __init__(self, ledger: JsonGatherJobStore) -> None:
        self.ledger = ledger
        self.entry: dict[str, Any] | None = None

    def require_client(self, job: GatherJobAuthority, window: Any) -> GatherClientBinding:
        return self.ledger.require_client(job, window)

    def record_verified(self, job: GatherJobAuthority, entry: Mapping[str, Any]) -> None:
        self.entry = dict(entry)


def _proof_matches_journal(
    job: GatherJobAuthority, context: MissionContext, checkpoint: Any,
    proof: Any, ledger: JsonGatherJobStore, entry: Mapping[str, Any],
) -> bool:
    projected = _ProofJournalProjection(ledger)
    try:
        record_verified_gather_tick(
            job, context,
            MissionTickResult(CheckpointStatus.COMPLETE, checkpoint, proof.snapshot,
                              engine_result=proof),
            projected,
        )
    except (GatherJobStoreError, ValueError, TypeError, KeyError):
        return False
    return (projected.entry is not None
            and {key: value for key, value in projected.entry.items() if key != "verified_at"}
            == {key: value for key, value in entry.items() if key != "verified_at"})


def audit_first_done_job(
    job: GatherJobAuthority, ledger: JsonGatherJobStore,
    checkpoints: JsonMissionStore, driver_report: Mapping[str, Any],
    evidence_root: Path,
) -> dict[str, Any]:
    """Validate one structural closeout without promoting it to live proof."""
    errors: list[str] = []
    progress = ledger.progress(job)
    journal = ledger.verifications(job)
    reservations = ledger.reservations(job)
    history = driver_report.get("history")
    if (driver_report.get("job_id") != job.job_id
            or driver_report.get("status") != "complete"
            or driver_report.get("verified_marches") != 5
            or driver_report.get("closeout") != list(journal)
            or type(driver_report.get("ticks")) is not int
            or not isinstance(history, list)
            or driver_report.get("ticks") != len(history)
            or not _history_matches_job(job, history)):
        errors.append("driver attempt has no matching complete five-entry closeout")
        history = []
    if (progress.revoked or progress.verified_marches != 5 or progress.dispatched_marches != 5
            or len(journal) != 5 or len(reservations) != 5):
        errors.append("job is revoked or lacks five durable VERIFIED reservations")
    checked_paths: list[str] = []
    prior_after_at: float | None = None
    for sequence in range(1, min(len(journal), 5) + 1):
        entry = journal[sequence - 1]
        if (not job.starts_at.timestamp() <= entry["before_observed_at"] < job.expires_at.timestamp()
                or (prior_after_at is not None and entry["before_observed_at"] <= prior_after_at)):
            errors.append(f"slot {sequence} observation is stale or outside job time scope")
        prior_after_at = entry["after_observed_at"]
        run_id = gather_slot_run_id(job, sequence)
        context = MissionContext(job.mission_id, job.task_id, run_id)
        checkpoint = checkpoints.load(context)
        if (entry["run_id"] != run_id
                or reservations[sequence - 1].run_id != run_id
                or checkpoint is None or checkpoint.status is not CheckpointStatus.COMPLETE):
            errors.append(f"slot {sequence} identity or COMPLETE checkpoint mismatch")
            continue
        try:
            proof = restore_verified_transition(checkpoint, context)
        except (ValueError, TypeError, KeyError):
            errors.append(f"slot {sequence} has no durable Engine VERIFIED proof")
            continue
        if not _proof_matches_journal(job, context, checkpoint, proof, ledger, entry):
            errors.append(f"slot {sequence} checkpoint proof differs from journal")
            continue
        expected_engine = build_gather_tick_evidence(
            context=context, character_id=job.character_id,
            result=MissionTickResult(CheckpointStatus.COMPLETE, checkpoint, proof.snapshot,
                                     engine_result=proof),
            live_armed=False, policy_approval=None,
            main_view_profile_trained=False, resource_level_profile_trained=False,
        )["engine"]
        candidates = []
        for item in history:
            if (not isinstance(item, Mapping) or item.get("run_id") != run_id
                    or item.get("status") != "complete"):
                continue
            record = _load_evidence(item.get("evidence_path"), evidence_root)
            if record is not None and _evidence_matches(entry, record, job, expected_engine):
                candidates.append(str(Path(item["evidence_path"]).resolve()))
        if len(set(candidates)) != 1:
            errors.append(f"slot {sequence} lacks one matching per-tick frame/receipt artifact")
        else:
            checked_paths.append(candidates[0])
    return {
        "schema_version": 1,
        "status": "OFFLINE_REPLAY_PASS" if not errors else "BLOCKED",
        "highest_proven_status": "IMPLEMENTED",
        "first_done_live_proven": False,
        "job_id": job.job_id,
        "verified_marches": progress.verified_marches,
        "mining_return_estimate": None,
        "checked_evidence_paths": checked_paths,
        "errors": errors,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


def write_verdict(path: Path, workspace_root: Path, verdict: Mapping[str, Any]) -> Path:
    destination = path.resolve()
    if not destination.is_relative_to(workspace_root.resolve()):
        raise ValueError("FIRST DONE closeout must stay under workspace")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(dict(verdict), handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gather-job", required=True, type=Path)
    parser.add_argument("--resource-type", required=True, choices=("FOOD", "WOOD", "STONE", "GOLD"))
    parser.add_argument("--resource-level", type=int)
    parser.add_argument("--driver-report", required=True, type=Path)
    parser.add_argument("--ledger-root", type=Path,
                        default=ROOT / "workspace" / "checkpoints" / "gather-jobs")
    parser.add_argument("--checkpoint-root", type=Path,
                        default=ROOT / "workspace" / "checkpoints")
    parser.add_argument("--evidence-root", type=Path,
                        default=ROOT / "workspace" / "evidence" / "gather")
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        workspace = (ROOT / "workspace").resolve()
        for path in (args.gather_job, args.driver_report, args.ledger_root,
                     args.checkpoint_root, args.evidence_root, args.output):
            if not path.resolve().is_relative_to(workspace):
                raise ValueError("FIRST DONE audit paths must stay under workspace")
        compiled = compile_mission(
            ROOT / "config" / "mission_flows.yaml", ROOT / "config" / "ui_states.yaml",
            "GATHER_RESOURCE",
            {"resource_type": args.resource_type, "resource_level": args.resource_level},
        )
        catalog = compiled_gather_catalog(compiled)
        job = load_gather_job_authority(
            args.gather_job, canonical_actions=catalog.actions,
            expected_catalog_digest=catalog.digest,
        )
        report = json.loads(args.driver_report.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError("driver report is not an object")
        verdict = audit_first_done_job(
            job, JsonGatherJobStore(args.ledger_root), JsonMissionStore(args.checkpoint_root),
            report, args.evidence_root,
        )
        destination = write_verdict(args.output, workspace, verdict)
        print(json.dumps({**verdict, "report_path": str(destination)}, ensure_ascii=False))
        return 0 if verdict["status"] == "OFFLINE_REPLAY_PASS" else 3
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
