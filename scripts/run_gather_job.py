"""Bounded caller of the canonical one-tick GATHER job CLI.

This driver adds no perception, action selection or input authority. An explicit
live arm reaches only the canonical guarded one-tick CLI after job preflight.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.gather_job_authority import GatherJobAuthority, compiled_gather_catalog, validate_schedule_catalog  # noqa: E402
from harness.gather_job_coordinator import GatherJobCoordinator  # noqa: E402
from harness.gather_job_startup_attestation import (  # noqa: E402
    canonical_startup_attestation_path, validate_canonical_startup_attestation,
)
from harness.gather_job_store import (  # noqa: E402
    GatherClientBinding, GatherJobStoreError, JsonGatherJobStore, load_gather_job_authority,
)
from harness.host_input_isolation import (  # noqa: E402
    HostInputIsolationEvidenceError, validate_gather_job_host_trace,
)
from harness.mission_loader import compile_mission  # noqa: E402
from harness.mission_store import JsonMissionStore  # noqa: E402

GATHER_JOB_STORE_ROOT = ROOT / "workspace" / "checkpoints" / "gather-jobs"
GATHER_CHECKPOINT_ROOT = ROOT / "workspace" / "checkpoints"
GATHER_EVIDENCE_ROOT = ROOT / "workspace" / "evidence" / "gather"


def _valid_closeout(value: object, job_id: str) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 5:
        return False
    seen_runs: set[str] = set()
    for sequence, entry in enumerate(value, 1):
        if not isinstance(entry, Mapping):
            return False
        run_id = entry.get("run_id")
        receipt = entry.get("receipt")
        if (entry.get("job_id") != job_id or entry.get("sequence") != sequence
                or entry.get("before_count") != sequence - 1
                or entry.get("after_count") != sequence
                or entry.get("capacity") != 5
                or not isinstance(run_id, str) or not run_id or run_id in seen_runs
                or not isinstance(receipt, Mapping)
                or receipt.get("action_id") != "MARCH_WITH_CURRENT_SELECTION"
                or receipt.get("target_id") != "TROOP_MARCH"):
            return False
        seen_runs.add(run_id)
    return True


def drive_job(
    tick: Callable[[], tuple[int, Mapping[str, Any]]], *,
    job_id: str, max_ticks: int, max_idle_ticks: int,
    idle_delay_seconds: float, settle_seconds: float,
    sleeper: Callable[[float], None] = time.sleep,
    validate_closed: Callable[[Mapping[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    """Advance bounded fresh ticks; never infer success from a receipt alone."""
    if (not isinstance(job_id, str) or not job_id
            or type(max_ticks) is not int or max_ticks < 1
            or type(max_idle_ticks) is not int or max_idle_ticks < 0
            or not isinstance(idle_delay_seconds, (int, float))
            or not math.isfinite(idle_delay_seconds) or idle_delay_seconds < 0
            or not isinstance(settle_seconds, (int, float))
            or not math.isfinite(settle_seconds) or settle_seconds < 0):
        raise ValueError("invalid GATHER job driver bounds")
    last_verified: int | None = None
    active_run: str | None = None
    idle = 0
    history: list[dict[str, Any]] = []

    def outcome(status: str, reason: str, *, closeout: object = None) -> dict[str, Any]:
        return {
            "status": status, "reason": reason, "job_id": job_id,
            "ticks": len(history), "verified_marches": last_verified,
            "history": history, "closeout": closeout,
        }

    for _ in range(max_ticks):
        try:
            code, payload = tick()
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            return outcome("failed", f"tick execution failed: {type(exc).__name__}: {exc}")
        if not isinstance(payload, Mapping):
            return outcome("failed", "tick output is not a JSON object")
        # CLI exceptions are diagnostic envelopes, not job-bound tick evidence.
        # Preserve the cause without trusting any progress or run fields in them.
        error = payload.get("error")
        if (payload.get("gather_job_id") is None
                and payload.get("status") == "failed" and error):
            diagnostic = {"status": "failed", "exit_code": code, "error": error}
            for key in ("stdout", "stderr", "stdout_truncated", "stderr_truncated"):
                if key in payload:
                    diagnostic[key] = payload[key]
            history.append(diagnostic)
            detail = (f"{error.get('type', 'Error')}: {error.get('message', '')}"
                      if isinstance(error, Mapping) else str(error))
            return outcome("failed", f"tick execution failed (exit code {code}): {detail}")
        status = payload.get("status")
        verified = payload.get("gather_job_verified_marches")
        run_id = payload.get("run_id")
        history.append({
            "status": status, "exit_code": code, "error": error,
            "run_id": run_id, "verified_marches": verified,
            "evidence_path": payload.get("evidence_path"),
            "resource_type": payload.get("gather_job_resource_type"),
            "slot_catalog_digest": payload.get("gather_job_slot_catalog_digest"),
        })
        if payload.get("gather_job_id") != job_id:
            return outcome("failed", "tick job identity changed")
        if type(verified) is not int or not 0 <= verified <= 5:
            return outcome("failed", "tick lacks bounded VERIFIED progress")
        if (last_verified is not None and
                (verified < last_verified or verified > last_verified + 1)):
            return outcome("failed", "VERIFIED progress skipped or regressed")
        if payload.get("gather_job_verification_error"):
            return outcome("failed", "job verification failed")
        if payload.get("gather_job_closed_at_five") is True:
            closeout = payload.get("gather_job_closeout")
            if (code == 0 and status == "complete" and verified == 5
                    and _valid_closeout(closeout, job_id)):
                journaled = payload.get("gather_job_journaled_this_tick") is True
                if journaled and (last_verified is None or verified == last_verified + 1):
                    last_verified = verified
                    return outcome("complete", "five VERIFIED marches closed", closeout=closeout)
                if not journaled and validate_closed is not None:
                    try:
                        recovered = validate_closed(payload)
                    except (OSError, ValueError, RuntimeError, TypeError, KeyError):
                        recovered = False
                    if recovered:
                        last_verified = verified
                        return outcome("complete", "durable five-march closeout recovered", closeout=closeout)
            return outcome("failed", "5/5 flag lacks a successful journaled tick and validated closeout")
        if verified == 5:
            return outcome("failed", "five VERIFIED marches lack a closeout")
        if code not in {0, 3} or status in {"failed", "blocked", "needs_decision"}:
            return outcome("suspended", f"tick stopped: {status or code}")
        if status not in {"running", "complete", "reobserve", "waiting"}:
            return outcome("failed", "tick returned an unknown state")
        if (active_run is not None and last_verified == verified and
                run_id != active_run):
            return outcome("failed", "occurrence changed before verification")
        if status == "complete" and (
            payload.get("gather_job_journaled_this_tick") is not True
            or last_verified == verified
        ):
            return outcome("failed", "mission COMPLETE did not advance VERIFIED journal")
        advanced = last_verified is None or verified > last_verified
        last_verified = verified
        active_run = (run_id if status != "complete" and isinstance(run_id, str) and run_id
                      else None)
        if status == "complete" or advanced:
            idle = 0
        else:
            idle += 1
            if idle > max_idle_ticks:
                return outcome("suspended", "fresh observation did not advance within idle bound")
        choice = payload.get("choice")
        if isinstance(choice, Mapping) and choice.get("action_id"):
            sleeper(settle_seconds)
        elif status in {"reobserve", "waiting"} or idle:
            sleeper(idle_delay_seconds)
    return outcome("suspended", "GATHER job tick ceiling reached")


def _tick_command(
    args: argparse.Namespace, startup_attestation_sha256: str, *,
    run_id: str | None = None, host_trace_path: Path | None = None,
    resource_type: str | None = None,
) -> list[str]:
    if (run_id is None) != (host_trace_path is None):
        raise ValueError("GATHER run ID and host trace must be supplied together")
    command = [
        sys.executable, str(ROOT / "scripts" / "run_gather_tick.py"),
        "--gather-job", str(args.gather_job),
        "--task-id", args.task_id,
        "--character-id", args.character_id,
        "--resource-type", resource_type or args.resource_type,
        "--startup-attestation-sha256", startup_attestation_sha256,
    ]
    if args.resource_level is not None:
        command.extend(("--resource-level", str(args.resource_level)))
    if run_id is not None:
        command.extend(("--run-id", run_id, "--input-isolation-evidence", str(host_trace_path)))
        if args.arm_live:
            command.append("--arm-live")
    return command


def _attested_client(job: GatherJobAuthority, digest: str) -> GatherClientBinding:
    path = canonical_startup_attestation_path(job.job_id, ROOT / "workspace")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("GATHER startup attestation changed before host preflight")
    record = json.loads(data)
    capture = record.get("capture") if isinstance(record, dict) else None
    if not isinstance(capture, dict):
        raise ValueError("GATHER startup attestation lacks client binding")
    return GatherClientBinding.from_window(capture.get("client_binding"))


def _record_job_host_trace(
    args: argparse.Namespace, job: GatherJobAuthority, *, run_id: str,
    client: GatherClientBinding, attempt_sequence: int, tick_index: int,
) -> Path:
    """Capture one passive, append-only trace for this planned tick."""
    if (not args.operator_confirms_quiescent or not args.host_session_id
            or not args.recovery_evidence):
        raise ValueError("job host preflight needs one startup quiescence assertion, host session ID and recovery evidence")
    recovery = args.recovery_evidence.resolve()
    evidence_root = (ROOT / "workspace" / "evidence").resolve()
    if not recovery.is_file() or not recovery.is_relative_to(evidence_root):
        raise ValueError("job recovery evidence must be a file under workspace/evidence")
    identity = hashlib.sha256(job.job_id.encode("utf-8")).hexdigest()[:20]
    suffix = f"attempt-{attempt_sequence:06d}/tick-{tick_index:06d}"
    trace_path = evidence_root / "host" / "gather-jobs" / identity / f"{suffix}.json"
    capture_path = ROOT / "workspace" / "runs" / "host-gather-jobs" / identity / f"{suffix}.png"
    capture_meta = capture_path.with_suffix(".capture.json")
    if any(path.exists() for path in (trace_path, capture_path, capture_meta)):
        raise ValueError("job host trace path already exists; refusing to replace evidence")
    from scripts.record_host_input_isolation import record
    from harness.windows_capture_backend import WindowsCaptureError

    try:
        payload = record(
            run_id=run_id, session_id=args.host_session_id,
            output=trace_path, capture_output=capture_path,
            operator_confirms_quiescent=True, recovery_evidence=recovery,
            focus_delay_seconds=0.0,
        )
    except (OSError, ValueError, WindowsCaptureError) as exc:
        raise ValueError(f"job passive host trace recorder failed: {exc}") from exc
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    with trace_path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        validate_gather_job_host_trace(
            trace_path, expected_run_id=run_id, expected_client=client,
            workspace_root=ROOT / "workspace",
        )
    except HostInputIsolationEvidenceError as exc:
        raise ValueError(f"job host trace preflight failed: {exc}") from exc
    return trace_path


_LAUNCH_FIELDS = frozenset({
    "schema_version", "job_artifact", "job_artifact_sha256", "job_id",
    "task_id", "character_id", "catalog_digest", "resource_type", "resource_level",
})
_MIXED_LAUNCH_FIELDS = (_LAUNCH_FIELDS - {"resource_type"}) | {
    "resource_schedule", "schedule_digest",
}


def _launch_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate GATHER launch key: {key}")
        value[key] = item
    return value


def _validated_launch(args: argparse.Namespace) -> tuple[argparse.Namespace, GatherJobAuthority]:
    workspace = (ROOT / "workspace").resolve()
    if args.launch_spec is not None:
        if any((args.gather_job, args.task_id, args.character_id,
                args.resource_type, args.resource_level is not None)):
            raise ValueError("launch spec cannot be mixed with manually entered job parameters")
        spec_path = args.launch_spec.resolve()
        if not spec_path.is_relative_to(workspace):
            raise ValueError("GATHER launch spec must be under workspace")
        spec = json.loads(spec_path.read_text(encoding="utf-8"), object_pairs_hook=_launch_pairs)
        if (not isinstance(spec, dict) or frozenset(spec) != (
                _MIXED_LAUNCH_FIELDS if spec.get("schema_version") == 2 else _LAUNCH_FIELDS)
                or type(spec["schema_version"]) is not int or spec["schema_version"] not in (1, 2)
                or any(not isinstance(spec[key], str) or not spec[key].strip()
                       for key in ("job_artifact", "job_artifact_sha256", "job_id",
                                   "task_id", "character_id", "catalog_digest"))
                or (spec["schema_version"] == 1 and spec["resource_type"] not in
                    ("FOOD", "WOOD", "STONE", "GOLD"))
                or (spec["resource_level"] is not None
                    and type(spec["resource_level"]) is not int)):
            raise ValueError("invalid GATHER launch spec")
        job_path = Path(spec["job_artifact"]).resolve()
        args = argparse.Namespace(**vars(args))
        args.gather_job = job_path
        args.task_id = spec["task_id"]
        args.character_id = spec["character_id"]
        args.resource_type = (spec["resource_schedule"][0]
                              if spec["schema_version"] == 2 and isinstance(spec["resource_schedule"], list)
                              and len(spec["resource_schedule"]) == 5 else spec.get("resource_type"))
        args.resource_level = spec["resource_level"]
    else:
        if not all((args.gather_job, args.task_id, args.character_id)):
            raise ValueError("supply --launch-spec or job, task and character parameters")
        spec = None
        job_path = args.gather_job.resolve()
    if not job_path.is_relative_to(workspace):
        raise ValueError("GATHER job artifact must be under workspace")
    raw_bytes = job_path.read_bytes()
    if spec is not None and hashlib.sha256(raw_bytes).hexdigest() != spec["job_artifact_sha256"]:
        raise ValueError("GATHER launch artifact hash changed")
    artifact = json.loads(raw_bytes, object_pairs_hook=_launch_pairs)
    if artifact.get("schema_version") == 2:
        if spec is None:
            if args.resource_type is not None or args.resource_level is not None:
                raise ValueError("mixed GATHER job parameters come from authority artifact")
            args = argparse.Namespace(**vars(args))
            args.resource_type = artifact["resource_schedule"][0]
            args.resource_level = artifact["resource_level"]
        elif (spec["resource_schedule"] != artifact["resource_schedule"]
              or spec["schedule_digest"] != artifact["schedule_digest"]
              or spec["resource_level"] != artifact["resource_level"]):
            raise ValueError("GATHER launch schedule differs from authority artifact")
    elif not args.resource_type:
        raise ValueError("legacy GATHER job requires a resource type")
    compiled = compile_mission(
        ROOT / "config" / "mission_flows.yaml", ROOT / "config" / "ui_states.yaml",
        "GATHER_RESOURCE", {"resource_type": args.resource_type,
                            "resource_level": args.resource_level},
    )
    catalog = compiled_gather_catalog(compiled)
    job = load_gather_job_authority(
        job_path, canonical_actions=catalog.actions,
        expected_catalog_digest=catalog.digest,
    )
    validate_schedule_catalog(job, ROOT / "config" / "mission_flows.yaml",
                              ROOT / "config" / "ui_states.yaml")
    if job.task_id != args.task_id or job.character_id != args.character_id:
        raise ValueError("GATHER launch identity differs from authority artifact")
    if spec is not None and any((
        spec["job_id"] != job.job_id,
        spec["task_id"] != job.task_id,
        spec["character_id"] != job.character_id,
        spec["catalog_digest"] != job.catalog_digest,
    )):
        raise ValueError("GATHER launch metadata differs from authority artifact")
    return args, job


def _durably_closed(job: GatherJobAuthority, payload: Mapping[str, Any]) -> bool:
    """Accept an already-closed CLI tick only from the durable journal and closeout."""
    plan = GatherJobCoordinator(
        job, JsonGatherJobStore(GATHER_JOB_STORE_ROOT),
        JsonMissionStore(GATHER_CHECKPOINT_ROOT),
    ).plan()
    if not plan.closed or plan.closeout is None or list(plan.closeout) != payload.get("gather_job_closeout"):
        return False
    digest = hashlib.sha256(job.job_id.encode("utf-8")).hexdigest()
    expected = GATHER_EVIDENCE_ROOT / "jobs" / f"gather-job-{digest}-closeout.json"
    source = payload.get("gather_job_closeout_path")
    if not isinstance(source, str) or Path(source).resolve() != expected.resolve():
        return False
    record = json.loads(expected.read_text(encoding="utf-8"))
    return record == {
        "schema_version": 1, "job_id": job.job_id, "task_id": job.task_id,
        "character_id": job.character_id, "catalog_digest": job.catalog_digest,
        "verified_marches": job.max_marches, "transitions": list(plan.closeout),
    }


def _subprocess_tick(command: list[str]) -> tuple[int, Mapping[str, Any]]:
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=300)
    candidates = []
    for output in (completed.stdout, completed.stderr):
        for line in reversed(output.splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                candidates.append(value)
    if completed.returncode != 0:
        for value in candidates:
            if value.get("status") == "failed" and value.get("error"):
                return completed.returncode, value
    if candidates:
        return completed.returncode, candidates[0]
    limit = 4096
    return completed.returncode, {
        "status": "failed", "error": "tick emitted no JSON result",
        "stdout": completed.stdout[-limit:], "stderr": completed.stderr[-limit:],
        "stdout_truncated": len(completed.stdout) > limit,
        "stderr_truncated": len(completed.stderr) > limit,
    }


def _write_report(root: Path, result: Mapping[str, Any]) -> Path:
    if not root.resolve().is_relative_to((ROOT / "workspace").resolve()):
        raise ValueError("driver report root must be under workspace")
    job_id = str(result["job_id"])
    directory = root / hashlib.sha256(job_id.encode("utf-8")).hexdigest()[:20]
    directory.mkdir(parents=True, exist_ok=True)
    sequence = result.get("attempt_sequence")
    destination = (directory / f"attempt-{sequence:06d}.result.json"
                   if type(sequence) is int and sequence > 0
                   else directory / f"attempt-{time.time_ns()}-{os.getpid()}.json")
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(dict(result), handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return destination


def _write_attempt_start(
    root: Path, job: GatherJobAuthority, startup_attestation_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    workspace = (ROOT / "workspace").resolve()
    if not root.resolve().is_relative_to(workspace):
        raise ValueError("driver report root must be under workspace")
    directory = root / hashlib.sha256(job.job_id.encode("utf-8")).hexdigest()[:20]
    directory.mkdir(parents=True, exist_ok=True)
    if (directory / "first-done-closeout.json").exists():
        raise ValueError("GATHER job already has an immutable FIRST DONE verdict")
    starts = sorted(directory.glob("attempt-*.start.json"))
    sequence = len(starts) + 1
    if any(path.name != f"attempt-{index:06d}.start.json"
           for index, path in enumerate(starts, 1)):
        raise ValueError("GATHER attempt-start chain is not contiguous")
    previous_start = starts[-1] if starts else None
    previous_result = directory / f"attempt-{sequence - 1:06d}.result.json" if starts else None
    if previous_start is not None:
        predecessor = json.loads(previous_start.read_text(encoding="utf-8"),
                                 object_pairs_hook=_launch_pairs)
        if predecessor.get("startup_attestation_sha256") != startup_attestation_sha256:
            raise ValueError("GATHER startup attestation differs across attempts")
    progress = JsonGatherJobStore(GATHER_JOB_STORE_ROOT).progress(job)
    open_unchanged = (
        previous_start is not None and not previous_result.exists()
        and predecessor.get("initial_verified") == progress.verified_marches
        and progress.dispatched_marches == progress.verified_marches
        and progress.verified_marches < job.max_marches
    )
    if progress.dispatched_marches == progress.verified_marches + 1 or open_unchanged:
        # Admission comes from the ledger/checkpoint/validated chain, never
        # from the orphan start itself. Advanced COMPLETE-orphan recovery
        # retains its original next-start bridge path.
        if progress.revoked or not job.starts_at <= datetime.now(timezone.utc) < job.expires_at:
            raise ValueError("GATHER open attempt outside active job authority")
        from scripts.audit_first_done_job import preflight_attempt_chain
        preflight_attempt_chain(job, JsonGatherJobStore(GATHER_JOB_STORE_ROOT),
                                JsonMissionStore(GATHER_CHECKPOINT_ROOT), directory,
                                GATHER_EVIDENCE_ROOT)
        if previous_start is not None and not previous_result.exists():
            # Preserve an already open tail without manufacturing another
            # attempt. The canonical runner/guard owns subsequent eligibility.
            return previous_start, predecessor
    record: dict[str, Any] = {
        "schema_version": 1, "kind": "attempt_start", "job_id": job.job_id,
        "task_id": job.task_id, "character_id": job.character_id,
        "catalog_digest": job.catalog_digest, "attempt_sequence": sequence,
        "startup_attestation_sha256": startup_attestation_sha256,
        "initial_verified": JsonGatherJobStore(GATHER_JOB_STORE_ROOT).progress(job).verified_marches,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "previous_start_sha256": (hashlib.sha256(previous_start.read_bytes()).hexdigest()
                                  if previous_start else None),
        "previous_result_sha256": (hashlib.sha256(previous_result.read_bytes()).hexdigest()
                                   if previous_result is not None and previous_result.is_file()
                                   else None),
    }
    destination = directory / f"attempt-{sequence:06d}.start.json"
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(record, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return destination, record


def _write_recovery_record(path: Path, record: Mapping[str, Any]) -> None:
    """Atomically publish one write-once record; a partial temp grants nothing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if json.loads(path.read_text()) != record:
            raise ValueError("journal recovery record changed")
        return
    temporary = path.with_name(path.name + ".pending")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, sort_keys=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        # link publishes without overwriting an existing immutable receipt.
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _reconcile_verified_journal(job: GatherJobAuthority, report_root: Path,
                                attestation_sha256: str) -> None:
    """Adopt exact persisted proof without observation, input, or backdating."""
    if not report_root.resolve().is_relative_to((ROOT / "workspace").resolve()):
        raise ValueError("journal recovery report root must be under workspace")
    from scripts.audit_first_done_job import (
        _ProofJournalProjection, _evidence_matches, _load_evidence,
        _record_time, _recovery_path, _recovery_matches, _recovery_origin,
    )
    from harness.gather_job_coordinator import gather_slot_run_id
    from harness.gather_job_verification import record_verified_gather_tick
    from harness.gather_replay_evidence import _run_directory, build_gather_tick_evidence
    from harness.mission_runner import MissionTickResult, restore_verified_transition
    from harness.mission_runtime import MissionContext
    from harness.mission_store import CheckpointStatus

    ledger = JsonGatherJobStore(GATHER_JOB_STORE_ROOT)
    checkpoints = JsonMissionStore(GATHER_CHECKPOINT_ROOT)
    progress = ledger.progress(job)
    if progress.revoked:
        raise ValueError("journal recovery job revoked")
    # A committed ledger write with an uncommitted receipt must finish before
    # any subsequent action, even when dispatch and verification counts match.
    pending = progress.dispatched_marches == progress.verified_marches + 1
    sequence = progress.dispatched_marches
    if not sequence:
        return
    commit_path = _recovery_path(GATHER_EVIDENCE_ROOT, job, sequence)
    intent_path = commit_path.with_name(f"slot-{sequence}.intent.json")
    if not pending and not intent_path.exists():
        return
    if not job.starts_at <= datetime.now(timezone.utc) < job.expires_at:
        raise ValueError("journal recovery outside job time scope")
    context = MissionContext(job.mission_id, job.task_id, gather_slot_run_id(job, sequence))
    checkpoint = checkpoints.load(context)
    if checkpoint is None or checkpoint.status is not CheckpointStatus.COMPLETE:
        if pending:
            return  # Ordinary pending postcheck remains fail closed in preflight.
        raise ValueError("journal recovery lacks COMPLETE checkpoint")
    proof = restore_verified_transition(checkpoint, context)
    projection = _ProofJournalProjection(ledger)
    record_verified_gather_tick(job, context, MissionTickResult(
        CheckpointStatus.COMPLETE, checkpoint, proof.snapshot, engine_result=proof), projection)
    projected = projection.entry
    if projected is None:
        raise ValueError("journal recovery lacks exact VERIFIED proof")
    client = _attested_client(job, attestation_sha256)
    if ledger.client_binding(job) != client:
        raise ValueError("journal recovery attested client mismatch")
    reservation = ledger.reservations(job)[sequence - 1]
    if (reservation.run_id != context.run_id or reservation.frame_id != proof.snapshot.frame_id
            or reservation.action != "MARCH_WITH_CURRENT_SELECTION"):
        raise ValueError("journal recovery reservation mismatch")
    expected_engine = build_gather_tick_evidence(
        context=context, character_id=job.character_id,
        result=MissionTickResult(CheckpointStatus.COMPLETE, checkpoint, proof.snapshot, engine_result=proof),
        live_armed=False, policy_approval=None, main_view_profile_trained=False,
        resource_level_profile_trained=False)["engine"]
    directory = GATHER_EVIDENCE_ROOT / _run_directory({
        "mission_id": job.mission_id, "task_id": job.task_id, "run_id": context.run_id,
        "attempt": context.attempt, "character_id": job.character_id})
    sources = []
    for path in directory.glob("*.json"):
        record = _load_evidence(str(path), GATHER_EVIDENCE_ROOT)
        if record is not None and _evidence_matches(projected, record, job, expected_engine, recovery=True):
            sources.append((path.resolve(), record))
    if len(sources) != 1:
        raise ValueError("journal recovery needs one exact failed-write tick")
    source, record = sources[0]
    recorded = _record_time(record.get("recorded_at"))
    attempts = report_root / hashlib.sha256(job.job_id.encode()).hexdigest()[:20]
    start_path, start, result_digest = _recovery_origin(attempts, record, job, source, sequence)
    if (start.get("startup_attestation_sha256") != attestation_sha256
            or record["runtime"]["gather_job"].get("startup_attestation_sha256") != attestation_sha256
            or start.get("job_id") != job.job_id or start.get("task_id") != job.task_id
            or start.get("character_id") != job.character_id or start.get("catalog_digest") != job.catalog_digest
            or recorded is None or not job.starts_at <= recorded < job.expires_at):
        raise ValueError("journal recovery attempt/attestation scope mismatch")
    common = {"schema_version": 1, "job_id": job.job_id, "sequence": sequence,
              "source_path": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "checkpoint_sha256": hashlib.sha256(checkpoints._path(context).read_bytes()).hexdigest(),
              "reservation": {"run_id": reservation.run_id, "frame_id": reservation.frame_id,
                              "sequence": reservation.sequence, "action": reservation.action},
              "attempt_start_path": str(start_path.resolve()),
              "attempt_start_sha256": hashlib.sha256(start_path.read_bytes()).hexdigest(),
              "attempt_result_sha256": result_digest,
              "startup_attestation_sha256": attestation_sha256}
    intent = {**common, "kind": "journal_recovery_intent",
              "proof_entry": {k: v for k, v in projected.items() if k != "verified_at"},
              "created_at": datetime.now(timezone.utc).isoformat()}
    if intent_path.exists():
        existing = json.loads(intent_path.read_text())
        intent["created_at"] = existing.get("created_at")
    _write_recovery_record(intent_path, intent)
    if pending:
        record_verified_gather_tick(job, context, MissionTickResult(
            CheckpointStatus.COMPLETE, checkpoint, proof.snapshot, engine_result=proof), ledger)
    entry = ledger.verifications(job)[sequence - 1]
    commit = {**common, "kind": "journal_recovery_commit", "journal_entry": entry,
              "intent_sha256": hashlib.sha256(intent_path.read_bytes()).hexdigest(),
              "committed_at": datetime.now(timezone.utc).isoformat()}
    if commit_path.exists():
        commit["committed_at"] = json.loads(commit_path.read_text()).get("committed_at")
    _write_recovery_record(commit_path, commit)
    if not _recovery_matches(entry, source, job, expected_engine, ledger, checkpoints, GATHER_EVIDENCE_ROOT, attempts):
        raise ValueError("journal recovery receipt failed readback")


def _unverdict_terminal_result(root: Path, job: GatherJobAuthority) -> tuple[Path, dict[str, Any]] | None:
    """Find a completed report left behind by a crash before verdict creation."""
    if not root.resolve().is_relative_to((ROOT / "workspace").resolve()):
        raise ValueError("driver report root must be under workspace")
    directory = root / hashlib.sha256(job.job_id.encode("utf-8")).hexdigest()[:20]
    if (directory / "first-done-closeout.json").exists():
        return None
    starts = sorted(directory.glob("attempt-*.start.json"))
    if not starts:
        return None
    latest = directory / f"attempt-{len(starts):06d}.result.json"
    if not latest.exists():
        return None
    result = json.loads(latest.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError("GATHER terminal result is not an object")
    return (latest, result) if result.get("status") == "complete" else None


def _audit_closeout(job: GatherJobAuthority, result: Mapping[str, Any], report: Path) -> tuple[str, Path]:
    from scripts.audit_first_done_job import audit_first_done_job, write_verdict

    verdict = audit_first_done_job(
        job, JsonGatherJobStore(GATHER_JOB_STORE_ROOT),
        JsonMissionStore(GATHER_CHECKPOINT_ROOT), result,
        GATHER_EVIDENCE_ROOT, attempt_root=report.parent,
    )
    destination = write_verdict(
        report.parent / "first-done-closeout.json", ROOT / "workspace", verdict,
    )
    return verdict["status"], destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch-spec", type=Path, help="startup launch JSON issued with the job")
    parser.add_argument("--gather-job", type=Path)
    parser.add_argument("--task-id")
    parser.add_argument("--character-id")
    parser.add_argument("--resource-type", choices=("FOOD", "WOOD", "STONE", "GOLD"))
    parser.add_argument("--resource-level", type=int)
    parser.add_argument("--max-ticks", type=int, default=80)
    parser.add_argument("--max-idle-ticks", type=int, default=3)
    parser.add_argument("--idle-delay-seconds", type=float, default=1.2)
    parser.add_argument("--settle-seconds", type=float, default=1.2)
    parser.add_argument("--report-root", type=Path,
                        default=ROOT / "workspace" / "evidence" / "gather" / "job-drives")
    parser.add_argument("--operator-confirms-quiescent", action="store_true",
                        help="one assertion for this job drive; no per-tick prompt")
    parser.add_argument("--host-session-id",
                        help="Windows operator session identity for passive per-tick traces")
    parser.add_argument("--recovery-evidence", type=Path,
                        help="no-input recovery matrix under workspace/evidence")
    parser.add_argument("--arm-live", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args, job = _validated_launch(args)
        if args.arm_live and job.schema_version != 2:
            raise ValueError("GATHER job live arm requires a schema-v2 five-slot schedule")
        startup_attestation_sha256 = validate_canonical_startup_attestation(
            args.gather_job, job.job_id,
            resource_type=args.resource_type, resource_level=args.resource_level,
            workspace_root=ROOT / "workspace", ledger_root=GATHER_JOB_STORE_ROOT,
            mission_flows=ROOT / "config" / "mission_flows.yaml",
            ui_states=ROOT / "config" / "ui_states.yaml",
        )
        _reconcile_verified_journal(job, args.report_root, startup_attestation_sha256)
        prior_terminal = _unverdict_terminal_result(args.report_root, job)
        if prior_terminal is not None:
            report, result = prior_terminal
            sequence = result.get("attempt_sequence")
            if type(sequence) is not int or sequence < 1:
                raise ValueError("terminal result has no valid attempt sequence")
            start_path = report.with_name(f"attempt-{sequence:06d}.start.json")
            start = json.loads(start_path.read_text(encoding="utf-8"),
                               object_pairs_hook=_launch_pairs)
            if start.get("startup_attestation_sha256") != startup_attestation_sha256:
                raise ValueError("terminal attestation differs from pinned attempt")
            audit_status, verdict_path = _audit_closeout(job, result, report)
            print(json.dumps({**result, "report_path": str(report),
                              "audit_status": audit_status, "verdict_path": str(verdict_path)},
                             ensure_ascii=False))
            return 0 if audit_status == "OFFLINE_REPLAY_PASS" else 4
        start_path, start = _write_attempt_start(
            args.report_root, job, startup_attestation_sha256,
        )
        from scripts.audit_first_done_job import preflight_attempt_chain
        preflight_attempt_chain(
            job, JsonGatherJobStore(GATHER_JOB_STORE_ROOT),
            JsonMissionStore(GATHER_CHECKPOINT_ROOT), start_path.parent,
            GATHER_EVIDENCE_ROOT,
        )
        tick_index = 0

        def attested_tick() -> tuple[int, Mapping[str, Any]]:
            nonlocal tick_index
            validate_canonical_startup_attestation(
                args.gather_job, job.job_id,
                resource_type=args.resource_type, resource_level=args.resource_level,
                workspace_root=ROOT / "workspace", ledger_root=GATHER_JOB_STORE_ROOT,
                mission_flows=ROOT / "config" / "mission_flows.yaml",
                ui_states=ROOT / "config" / "ui_states.yaml",
                expected_sha256=startup_attestation_sha256,
            )
            client = _attested_client(job, startup_attestation_sha256)
            plan = GatherJobCoordinator(
                job, JsonGatherJobStore(GATHER_JOB_STORE_ROOT),
                JsonMissionStore(GATHER_CHECKPOINT_ROOT),
            ).plan()
            tick_index += 1
            if plan.closed:
                command = _tick_command(args, startup_attestation_sha256)
            else:
                if not plan.run_id:
                    raise ValueError("GATHER job plan lacks current run ID")
                trace = _record_job_host_trace(
                    args, job, run_id=plan.run_id, client=client,
                    attempt_sequence=start["attempt_sequence"], tick_index=tick_index,
                )
                command = _tick_command(
                    args, startup_attestation_sha256,
                    run_id=plan.run_id, host_trace_path=trace,
                    resource_type=job.resource_for_slot(plan.sequence)
                        if job.schema_version == 2 else None,
                )
            return _subprocess_tick(command)

        result = drive_job(
            attested_tick, job_id=job.job_id,
            max_ticks=args.max_ticks, max_idle_ticks=args.max_idle_ticks,
            idle_delay_seconds=args.idle_delay_seconds,
            settle_seconds=args.settle_seconds,
            validate_closed=lambda payload: _durably_closed(job, payload),
        )
        result["recorded_at"] = datetime.now(timezone.utc).isoformat()
        result["attempt_sequence"] = start["attempt_sequence"]
        result["initial_verified"] = start["initial_verified"]
        result["start_sha256"] = hashlib.sha256(start_path.read_bytes()).hexdigest()
        report = _write_report(args.report_root, result)
        audit_status = None
        verdict_path = None
        if result["status"] == "complete":
            audit_status, verdict_path = _audit_closeout(job, result, report)
        print(json.dumps({**result, "report_path": str(report),
                          "audit_status": audit_status,
                          "verdict_path": str(verdict_path) if verdict_path else None},
                         ensure_ascii=False))
        if audit_status == "BLOCKED":
            return 4
        return {"complete": 0, "suspended": 3, "failed": 4}[result["status"]]
    except (OSError, ValueError, json.JSONDecodeError, GatherJobStoreError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
