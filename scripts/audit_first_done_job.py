"""Non-actuating audit of one five-march GATHER job's durable evidence.

A passing structural audit is not a live FIRST DONE claim. Native frame and
operator-interference provenance still require a separately scoped live pass.
The command reads job artifacts and writes only one append-only verdict file.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.gather_job_authority import GatherJobAuthority, compiled_gather_catalog, validate_schedule_catalog  # noqa: E402
from harness.gather_job_coordinator import gather_slot_run_id  # noqa: E402
from harness.gather_job_store import GatherClientBinding, GatherJobStoreError, JsonGatherJobStore, load_gather_job_authority  # noqa: E402
from harness.gather_job_verification import record_verified_gather_tick, first_slot_queue_is_absent_or_measured_zero  # noqa: E402
from harness.gather_replay_evidence import _run_directory, _snapshot_facts, build_gather_tick_evidence  # noqa: E402
from harness.mission_loader import compile_mission  # noqa: E402
from harness.mission_runner import (  # noqa: E402
    MissionTickResult, restore_verified_transition, _snapshot_from_pending,
    _choice_from_pending, _feedback_from_pending,
)
from harness.mission_runtime import MissionContext, ToolSnapshot  # noqa: E402
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
                      job: GatherJobAuthority, expected_engine: Mapping[str, Any],
                      *, recovery: bool = False) -> bool:
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
    first_slot = entry["sequence"] == 1
    if first_slot:
        baseline_matches = (
            baseline.get("predicate_id") == "first_march_queue_appeared_at_one"
            and baseline.get("source") == "job_initial_slot_ordinal"
            and baseline.get("job_id") == job.job_id
            and "counter_value" not in baseline
            and baseline.get("source_frame_id") == entry["before_frame_id"]
            and baseline_at == before_at
            and first_slot_queue_is_absent_or_measured_zero(
                ToolSnapshot(job.mission_id, job.task_id, engine.get("before_frame_id"),
                             engine.get("before_state"), facts=before, observed_at=before_at),
                job, GatherClientBinding.from_window(before.get("window")),
            )
        )
    else:
        baseline_matches = (
            baseline.get("predicate_id") == "march_queue_used_increased"
            and baseline.get("counter_value") == entry["before_count"]
            and baseline.get("source") in {
                "visible_ocr_queue_anchor", "visible_ocr_march_queue_region"
            }
        )
    return (
        (identity.get("mission_id"), identity.get("task_id"), identity.get("run_id"),
         identity.get("character_id"))
        == (job.mission_id, job.task_id, entry["run_id"], job.character_id)
        and job_runtime.get("job_id") == job.job_id
        and job_runtime.get("verified_marches") == entry["sequence"] - int(recovery)
        and job_runtime.get("journaled_this_tick") is (not recovery)
        and (not recovery or (
            job_runtime.get("reserved_marches") == entry["sequence"]
            and isinstance(job_runtime.get("verification_error"), str)
            and job_runtime["verification_error"].startswith(("PermissionError:", "OSError:"))
        ))
        and (job.schema_version != 2 or (
            job_runtime.get("resource_type") == job.resource_for_slot(entry["sequence"])
            and job_runtime.get("slot_catalog_digest") == job.catalog_for_slot(entry["sequence"])
            and job_runtime.get("schedule_digest") == job.schedule_digest
        ))
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
        and baseline_matches
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
    """Require one ordered stream containing all five verified slots."""
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


def _record_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        instant = datetime.fromisoformat(value)
    except ValueError:
        return None
    return instant if instant.tzinfo is not None and instant.utcoffset() is not None else None


def _verified_in_window(entry: Mapping[str, Any], start: datetime, end: datetime,
                        evidence_root: Path | None = None, job: GatherJobAuthority | None = None) -> bool:
    verified_at = _record_time(entry.get("verified_at"))
    if evidence_root is not None and job is not None:
        receipt = _load_evidence(str(_recovery_path(evidence_root, job, entry["sequence"])), evidence_root)
        if receipt is not None and receipt.get("journal_entry") == entry:
            source = _load_evidence(receipt.get("source_path"), evidence_root)
            verified_at = _record_time(source.get("recorded_at")) if source else None
    return verified_at is not None and start <= verified_at < end


def _recovery_path(root: Path, job: GatherJobAuthority, sequence: int) -> Path:
    return root / "journal-recovery" / hashlib.sha256(job.job_id.encode()).hexdigest() / f"slot-{sequence}.commit.json"


def _recovery_origin(attempt_root: Path, record: Mapping[str, Any], job: GatherJobAuthority,
                     source: Path, slot: int, expected_start: Path | None = None) -> tuple[Path, Mapping[str, Any], str | None]:
    observed = _record_time(record.get("recorded_at"))
    if observed is None:
        raise ValueError("recovery source lacks recorded time")
    owners = []
    previous_start = None
    previous_result = None
    pinned = None
    for index, path in enumerate(sorted(attempt_root.glob("attempt-*.start.json")), 1):
        start = json.loads(path.read_text())
        instant = _record_time(start.get("started_at"))
        if (path.name != f"attempt-{index:06d}.start.json"
                or start.get("schema_version") != 1 or start.get("kind") != "attempt_start"
                or start.get("attempt_sequence") != index
                or start.get("job_id") != job.job_id or start.get("task_id") != job.task_id
                or start.get("character_id") != job.character_id or start.get("catalog_digest") != job.catalog_digest
                or start.get("previous_start_sha256") != previous_start
                or start.get("previous_result_sha256") != previous_result
                or not _valid_sha256(start.get("startup_attestation_sha256"))
                or (pinned is not None and start.get("startup_attestation_sha256") != pinned)
                or type(start.get("initial_verified")) is not int or not 0 <= start["initial_verified"] <= 5
                or instant is None or not job.starts_at <= instant < job.expires_at):
            raise ValueError("recovery originating attempt chain scope/hash differs")
        pinned = start["startup_attestation_sha256"]
        previous_start = hashlib.sha256(path.read_bytes()).hexdigest()
        previous_report = path.with_name(path.name.replace(".start.json", ".result.json"))
        previous_result = hashlib.sha256(previous_report.read_bytes()).hexdigest() if previous_report.exists() else None
        if instant <= observed:
            owners.append((instant, path, start))
    if not owners:
        raise ValueError("recovery has no originating attempt")
    _, path, start = max(owners, key=lambda item: item[0])
    if start["initial_verified"] > slot - 1:
        raise ValueError("recovery originating attempt started after this slot")
    if expected_start is not None and path.resolve() != expected_start.resolve():
        raise ValueError("recovery cites a different originating attempt")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result_path = path.with_name(path.name.replace(".start.json", ".result.json"))
    result_digest = None
    if result_path.exists():
        report = json.loads(result_path.read_text())
        ticks = report.get("history")
        if (report.get("job_id") != job.job_id or report.get("attempt_sequence") != start.get("attempt_sequence")
                or report.get("start_sha256") != digest or report.get("initial_verified") != start.get("initial_verified")
                or report.get("status") != "failed" or report.get("reason") != "job verification failed"
                or not isinstance(ticks, list) or not ticks
                or ticks[-1].get("status") != "complete" or ticks[-1].get("run_id") != gather_slot_run_id(job, slot)
                or ticks[-1].get("verified_marches") != slot - 1
                or Path(ticks[-1].get("evidence_path", "")).resolve() != source.resolve()
                or _record_time(report.get("recorded_at")) is None
                or _record_time(report.get("recorded_at")) < observed):
            raise ValueError("recovery does not match exact failed result tail")
        result_digest = hashlib.sha256(result_path.read_bytes()).hexdigest()
    return path.resolve(), start, result_digest


def _recovery_matches(entry: Mapping[str, Any], source: Path, job: GatherJobAuthority,
                      engine: Mapping[str, Any], ledger: JsonGatherJobStore,
                      checkpoints: JsonMissionStore, root: Path,
                      attempt_root: Path | None = None, expected_start: Path | None = None) -> bool:
    receipt_path = _recovery_path(root, job, entry["sequence"])
    receipt = _load_evidence(str(receipt_path), root)
    record = _load_evidence(str(source), root)
    if receipt is None or record is None:
        return False
    try:
        intent_path = receipt_path.with_name(f"slot-{entry['sequence']}.intent.json")
        intent = _load_evidence(str(intent_path), root)
        context = MissionContext(job.mission_id, job.task_id, entry["run_id"])
        reservation = ledger.reservations(job)[entry["sequence"] - 1]
        start_path = Path(receipt["attempt_start_path"]).resolve()
        if attempt_root is None or start_path.parent != attempt_root.resolve():
            return False
        start = json.loads(start_path.read_text())
        owner, _, result_digest = _recovery_origin(attempt_root, record, job, source, entry["sequence"], expected_start)
        if owner != start_path:
            return False
        common = {"schema_version": 1, "job_id": job.job_id, "sequence": entry["sequence"],
                  "source_path": str(source.resolve()), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                  "checkpoint_sha256": hashlib.sha256(checkpoints._path(context).read_bytes()).hexdigest(),
                  "reservation": {"run_id": reservation.run_id, "frame_id": reservation.frame_id,
                                  "sequence": reservation.sequence, "action": reservation.action},
                  "attempt_start_path": str(start_path), "attempt_start_sha256": hashlib.sha256(start_path.read_bytes()).hexdigest(),
                  "attempt_result_sha256": result_digest,
                  "startup_attestation_sha256": start["startup_attestation_sha256"]}
        adopted = _record_time(entry["verified_at"])
        committed = _record_time(receipt["committed_at"])
        begun = _record_time(intent["created_at"]) if intent else None
        observed = _record_time(record["recorded_at"])
        started = _record_time(start["started_at"])
        return (frozenset(receipt) == frozenset(common) | {"kind", "journal_entry", "intent_sha256", "committed_at"}
                and frozenset(intent) == frozenset(common) | {"kind", "proof_entry", "created_at"}
                and all(receipt.get(k) == v and intent.get(k) == v for k, v in common.items())
                and intent.get("kind") == "journal_recovery_intent"
                and intent.get("proof_entry") == {k: v for k, v in entry.items() if k != "verified_at"}
                and receipt.get("kind") == "journal_recovery_commit" and receipt.get("journal_entry") == entry
                and receipt.get("intent_sha256") == hashlib.sha256(intent_path.read_bytes()).hexdigest()
                and all(t is not None for t in (adopted, committed, begun, observed, started))
                and job.starts_at <= started <= observed <= begun <= adopted <= committed < job.expires_at
                and start.get("job_id") == job.job_id and start.get("task_id") == job.task_id
                and start.get("character_id") == job.character_id and start.get("catalog_digest") == job.catalog_digest
                and record["runtime"]["gather_job"].get("startup_attestation_sha256") == start["startup_attestation_sha256"]
                and reservation.run_id == entry["run_id"] and reservation.frame_id == entry["before_frame_id"]
                and _evidence_matches(entry, record, job, engine, recovery=True))
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        return False


def _bridge_artifacts(
    job: GatherJobAuthority, sequence: int, journal: list[dict[str, Any]],
    ledger: JsonGatherJobStore, checkpoints: JsonMissionStore, evidence_root: Path,
    attempt_root: Path | None = None,
    expected_start: Path | None = None,
) -> list[str]:
    """Find exact persisted canonical tick proof for one unreported VERIFIED slot."""
    if not 1 <= sequence <= len(journal):
        return []
    entry = journal[sequence - 1]
    context = MissionContext(job.mission_id, job.task_id, gather_slot_run_id(job, sequence))
    checkpoint = checkpoints.load(context)
    if checkpoint is None or checkpoint.status is not CheckpointStatus.COMPLETE:
        return []
    try:
        proof = restore_verified_transition(checkpoint, context)
    except (ValueError, TypeError, KeyError):
        return []
    if not _proof_matches_journal(job, context, checkpoint, proof, ledger, entry):
        return []
    expected_engine = build_gather_tick_evidence(
        context=context, character_id=job.character_id,
        result=MissionTickResult(CheckpointStatus.COMPLETE, checkpoint, proof.snapshot,
                                 engine_result=proof),
        live_armed=False, policy_approval=None,
        main_view_profile_trained=False, resource_level_profile_trained=False,
    )["engine"]
    directory = evidence_root / _run_directory({
        "mission_id": job.mission_id, "task_id": job.task_id,
        "run_id": context.run_id, "attempt": context.attempt,
        "character_id": job.character_id,
    })
    matches: list[str] = []
    for path in directory.glob("*.json"):
        record = _load_evidence(str(path), evidence_root)
        if record is not None and (_evidence_matches(entry, record, job, expected_engine)
                                   or _recovery_matches(entry, path, job, expected_engine, ledger, checkpoints, evidence_root, attempt_root, expected_start)):
            matches.append(str(path.resolve()))
    return matches


def _failed_tick_diagnostic(tick: Mapping[str, Any], reason: object) -> bool:
    """Validate the driver's zero-authority fatal-error envelope exactly."""
    required = {"status", "exit_code", "error"}
    optional = {"stdout", "stderr", "stdout_truncated", "stderr_truncated"}
    if (not required <= set(tick) or not set(tick) <= required | optional
            or tick.get("status") != "failed" or type(tick.get("exit_code")) is not int
            or tick["exit_code"] == 0):
        return False
    error = tick["error"]
    if isinstance(error, Mapping):
        if (set(error) != {"type", "message"} or not isinstance(error["type"], str)
                or re.fullmatch(r"[A-Za-z_]\w*", error["type"]) is None
                or not isinstance(error["message"], str)):
            return False
        detail = f"{error['type']}: {error['message']}"
    elif error == "tick emitted no JSON result":
        detail = error
        if not optional <= set(tick):
            return False
    else:
        return False
    for stream in ("stdout", "stderr"):
        flag = stream + "_truncated"
        if (stream in tick) != (flag in tick):
            return False
        if stream in tick and (
            not isinstance(tick[stream], str) or len(tick[stream]) > 4096
            or type(tick[flag]) is not bool
            or (tick[flag] and len(tick[stream]) != 4096)
        ):
            return False
    return reason == f"tick execution failed (exit code {tick['exit_code']}): {detail}"


def _empty_execution_failure(report: Mapping[str, Any], initial_verified: int) -> bool:
    """A driver exception before any returned tick carries no progress authority.

    The callback may have had side effects before raising. This shape therefore
    proves neither zero input nor success; pending reservations and durable
    proofs still have to pass the ordinary ledger/checkpoint admission below.
    """
    return (
        set(report) == {"status", "reason", "job_id", "ticks", "verified_marches",
                        "history", "closeout", "recorded_at", "attempt_sequence",
                        "initial_verified", "start_sha256"}
        and report.get("status") == "failed"
        and type(report.get("ticks")) is int and report["ticks"] == 0
        and report.get("history") == [] and report.get("closeout") is None
        and report.get("verified_marches") is None
        and report.get("initial_verified") == initial_verified
        and isinstance(report.get("reason"), str)
        and re.fullmatch(
            r"tick execution failed: (?:OSError|PermissionError|FileNotFoundError|"
            r"TimeoutExpired|ValueError): [\s\S]+", report["reason"]
        ) is not None
    )


def _attempt_chain_history(
    job: GatherJobAuthority, ledger: JsonGatherJobStore,
    checkpoints: JsonMissionStore, terminal: Mapping[str, Any] | None,
    attempt_root: Path, evidence_root: Path, journal: list[dict[str, Any]],
    *, allow_open_tail: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    history: list[dict[str, Any]] = []
    files = sorted(attempt_root.glob("attempt-*.json"))
    starts: dict[int, Path] = {}
    results: dict[int, Path] = {}
    pattern = re.compile(r"attempt-(\d{6})\.(start|result)\.json\Z")
    for path in files:
        match = pattern.fullmatch(path.name)
        if match is None:
            errors.append("unexpected attempt record")
            continue
        sequence = int(match.group(1))
        target = starts if match.group(2) == "start" else results
        if sequence in target:
            errors.append("duplicate attempt record")
        target[sequence] = path
    if not starts or sorted(starts) != list(range(1, len(starts) + 1)):
        errors.append("attempt-start chain is missing or unordered")
    if any(sequence not in starts for sequence in results):
        errors.append("attempt result lacks its start")
    if errors:
        return [], errors
    verified = 0
    previous_start_hash: str | None = None
    previous_result_hash: str | None = None
    pinned_attestation_hash: str | None = None
    previous_time: datetime | None = None
    prior_orphan_bridged_to_five = False
    for sequence in range(1, len(starts) + 1):
        start_path = starts[sequence]
        try:
            start = json.loads(start_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            errors.append(f"attempt {sequence} start is unreadable")
            break
        started = _record_time(start.get("started_at")) if isinstance(start, dict) else None
        if (not isinstance(start, dict)
                or frozenset(start) != {"schema_version", "kind", "job_id", "task_id",
                                            "character_id", "catalog_digest", "attempt_sequence",
                                            "initial_verified", "started_at", "previous_start_sha256",
                                            "previous_result_sha256", "startup_attestation_sha256"}
                or start.get("schema_version") != 1 or start.get("kind") != "attempt_start"
                or (start.get("job_id"), start.get("task_id"), start.get("character_id"),
                    start.get("catalog_digest")) != (job.job_id, job.task_id,
                                                     job.character_id, job.catalog_digest)
                or start.get("attempt_sequence") != sequence
                or type(start.get("initial_verified")) is not int
                or start.get("initial_verified") != verified
                or start.get("previous_start_sha256") != previous_start_hash
                or start.get("previous_result_sha256") != previous_result_hash
                or not isinstance(start.get("startup_attestation_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", start["startup_attestation_sha256"]) is None
                or (pinned_attestation_hash is not None
                    and start["startup_attestation_sha256"] != pinned_attestation_hash)
                or started is None or not job.starts_at <= started < job.expires_at
                or (previous_time is not None and started <= previous_time)):
            errors.append(f"attempt {sequence} start scope, order or hash differs")
            break
        start_hash = hashlib.sha256(start_path.read_bytes()).hexdigest()
        pinned_attestation_hash = start["startup_attestation_sha256"]
        result_path = results.get(sequence)
        if result_path is None:
            if sequence == len(starts):
                if allow_open_tail:
                    previous_start_hash = start_hash
                    previous_time = started
                    continue
                errors.append(f"attempt {sequence} has no result or subsequent recovery start")
                break
            try:
                next_start = json.loads(starts[sequence + 1].read_text(encoding="utf-8"))
                target = next_start.get("initial_verified")
                next_started = _record_time(next_start.get("started_at"))
            except (OSError, ValueError, AttributeError):
                target = None
                next_started = None
            if (type(target) is not int or not verified < target <= 5
                    or next_started is None or next_started <= started):
                errors.append(f"attempt {sequence} stopped before persisted VERIFIED tick")
                break
            for slot in range(verified + 1, target + 1):
                if slot > len(journal) or not _verified_in_window(journal[slot - 1], started, next_started, evidence_root, job):
                    errors.append(f"attempt {sequence} slot {slot} VERIFIED outside orphan attempt")
                    break
                matches = _bridge_artifacts(job, slot, journal, ledger, checkpoints, evidence_root, attempt_root, start_path)
                if len(matches) != 1:
                    errors.append(f"attempt {sequence} slot {slot} has no unique durable per-tick bridge")
                    break
                history.append({"status": "complete", "run_id": gather_slot_run_id(job, slot),
                                "verified_marches": slot, "evidence_path": matches[0]})
            if errors:
                break
            verified = target
            prior_orphan_bridged_to_five = target == 5
            previous_result_hash = None
            previous_time = started
        else:
            try:
                report = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                errors.append(f"attempt {sequence} result is unreadable")
                break
            recorded = _record_time(report.get("recorded_at")) if isinstance(report, dict) else None
            ticks = report.get("history") if isinstance(report, dict) else None
            if (not isinstance(report, dict) or report.get("job_id") != job.job_id
                    or report.get("attempt_sequence") != sequence
                    or report.get("initial_verified") != verified
                    or report.get("start_sha256") != start_hash
                    or report.get("status") not in {"suspended", "complete", "failed"}
                    or not isinstance(ticks, list) or type(report.get("ticks")) is not int
                    or report["ticks"] != len(ticks) or recorded is None or recorded < started
                    or (sequence < len(starts) and report.get("status") not in {"suspended", "failed"})
                    or (terminal is not None and sequence == len(starts) and report != terminal)):
                errors.append(f"attempt {sequence} result scope, status or digest differs")
                break
            recovered_tail = False
            diagnostic_tail = False
            for tick in ticks:
                if not isinstance(tick, dict):
                    errors.append(f"attempt {sequence} tick is malformed")
                    break
                status, count = tick.get("status"), tick.get("verified_marches")
                recovered_tail = False
                if (report.get("status") == "failed" and tick is ticks[-1]
                        and _failed_tick_diagnostic(tick, report.get("reason"))):
                    diagnostic_tail = True
                    # This envelope proves no identity, action, artifact or progress.
                    # Leave the bound tick stream and VERIFIED accumulator intact.
                    continue
                if (report.get("status") == "failed" and report.get("reason") == "job verification failed"
                        and tick is ticks[-1] and status == "complete" and count == verified
                        and verified < len(journal)):
                    matches = _bridge_artifacts(job, verified + 1, journal, ledger, checkpoints, evidence_root, attempt_root, start_path)
                    if (len(matches) == 1 and isinstance(tick.get("evidence_path"), str)
                            and Path(matches[0]) == Path(tick["evidence_path"]).resolve()
                            and _recovery_path(evidence_root, job, verified + 1).is_file()):
                        tick = {**tick, "verified_marches": verified + 1}
                        count = verified + 1
                        recovered_tail = True
                if (status == "complete" and tick.get("run_id") is None
                        and count == 5 and verified == 5 and sequence == len(starts)
                        and prior_orphan_bridged_to_five
                        and report.get("reason") == "durable five-march closeout recovered"):
                    continue
                if (status not in {"running", "waiting", "reobserve", "complete"}
                        or type(count) is not int
                        or tick.get("run_id") != gather_slot_run_id(job, verified + 1)
                        or (status == "complete" and count != verified + 1)
                        or (status != "complete" and count != verified)):
                    errors.append(f"attempt {sequence} tick order or VERIFIED progress differs")
                    break
                if status == "complete" and (
                    verified >= len(journal)
                    or not _verified_in_window(journal[verified], started, recorded, evidence_root, job)
                ):
                    errors.append(f"attempt {sequence} tick VERIFIED outside result attempt")
                    break
                history.append(tick)
                if status == "complete":
                    verified += 1
            empty_failure = _empty_execution_failure(report, start["initial_verified"])
            diagnostic_only_null = ((diagnostic_tail and len(ticks) == 1 or empty_failure)
                                    and report.get("verified_marches") is None
                                    and verified == start["initial_verified"])
            diagnostic_progress_valid = (
                diagnostic_only_null or (diagnostic_tail and len(ticks) > 1
                    and type(report.get("verified_marches")) is int
                    and report["verified_marches"] == verified)
            )
            if (errors or (report.get("status") == "failed" and not (recovered_tail or diagnostic_tail or empty_failure))
                    or (diagnostic_tail and not diagnostic_progress_valid)
                    or (report.get("verified_marches") != verified
                          and not (report.get("status") == "failed" and ticks and recovered_tail
                                   and report.get("verified_marches") in {verified - 1, None})
                          and not diagnostic_only_null)
                    or (report.get("status") == "suspended" and verified == 5)):
                errors.append(f"attempt {sequence} result progress differs")
                break
            previous_result_hash = hashlib.sha256(result_path.read_bytes()).hexdigest()
            previous_time = recorded
            prior_orphan_bridged_to_five = recovered_tail and verified == 5
        previous_start_hash = start_hash
    if not errors and terminal is not None and len(starts) != terminal.get("attempt_sequence"):
        errors.append("terminal attempt chain is incomplete")
    return history, errors


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


def _pending_march_is_bound(
    job: GatherJobAuthority, ledger: JsonGatherJobStore, checkpoints: JsonMissionStore,
    history: list[dict[str, Any]], attempt_root: Path, evidence_root: Path,
) -> bool:
    """Permit observation of one already emitted March, never a new dispatch."""
    try:
        progress = ledger.progress(job)
        slot = progress.verified_marches + 1
        reservations = ledger.reservations(job)
        if (progress.revoked or not job.starts_at <= datetime.now(timezone.utc) < job.expires_at
                or progress.dispatched_marches != slot or not 1 <= slot <= job.max_marches
                or len(reservations) != slot):
            return False
        reservation = reservations[-1]
        context = MissionContext(job.mission_id, job.task_id, gather_slot_run_id(job, slot))
        checkpoint = checkpoints.load(context)
        if (checkpoint is None or checkpoint.status is not CheckpointStatus.REOBSERVE
                or checkpoint.verified_transition is not None
                or reservation.run_id != context.run_id or reservation.sequence != slot
                or reservation.action != "MARCH_WITH_CURRENT_SELECTION"):
            return False
        pending = checkpoint.pending_verification
        if not isinstance(pending, Mapping) or pending.get("schema_version") != 1:
            return False
        before = _snapshot_from_pending(pending, context)
        choice = _choice_from_pending(pending)
        feedback = _feedback_from_pending(pending)
        receipt = feedback.facts.get("receipt")
        client = ledger.require_client(job, before.facts.get("window"))
        baseline = before.facts.get("completion_baseline")
        if (choice.action_id != "MARCH_WITH_CURRENT_SELECTION" or choice.target_id != "TROOP_MARCH"
                or dict(choice.arguments) != {} or before.state != "NEW_TROOP_SETUP"
                or before.frame_id != reservation.frame_id
                or before.facts.get("character_id") != job.character_id
                or not _valid_sha256(before.facts.get("image_sha256"))
                or before.facts.get("new_troop_formation_ready") is not True
                or before.facts.get("new_troop_formation_source") != _FORMATION_SOURCE
                or before.facts.get("new_troop_formation_frame_id") != before.frame_id
                or before.facts.get("new_troop_formation_image_sha256") != before.facts.get("image_sha256")
                or not feedback.success or feedback.code not in {"DISPATCHED", "VERIFIED"}
                or feedback.completed or feedback.facts.get("gather_job_id") != job.job_id
                or type(feedback.facts.get("gather_job_dispatch_sequence")) is not int
                or feedback.facts.get("gather_job_dispatch_sequence") != slot
                or not isinstance(receipt, Mapping)
                or receipt.get("action_id") != choice.action_id or receipt.get("target_id") != choice.target_id
                or receipt.get("before_frame_id") != before.frame_id
                or receipt.get("bounded_arguments") != {} or receipt.get("character_id") != job.character_id
                or receipt.get("non_interference_confirmed") is not True
                or not isinstance(baseline, Mapping) or baseline != checkpoint.completion_baseline
                or baseline.get("character_id") != job.character_id or baseline.get("capacity") != 5
                or not isinstance(pending.get("last_observed_frame_id"), str)
                or pending.get("last_observed_frame_id") != checkpoint.last_frame_id):
            return False
        if slot == 1:
            if (baseline.get("predicate_id") != "first_march_queue_appeared_at_one"
                    or baseline.get("source") != "job_initial_slot_ordinal"
                    or baseline.get("job_id") != job.job_id or "counter_value" in baseline
                    or baseline.get("source_frame_id") != before.frame_id
                    or baseline.get("source_timestamp") != before.observed_at
                    or not first_slot_queue_is_absent_or_measured_zero(before, job, client)):
                return False
        elif (baseline.get("predicate_id") != "march_queue_used_increased"
              or type(baseline.get("counter_value")) is not int
              or baseline.get("counter_value") != slot - 1
              or baseline.get("source") not in {"visible_ocr_queue_anchor", "visible_ocr_march_queue_region"}):
            return False
        pending_ticks = [tick for tick in history if tick.get("run_id") == context.run_id]
        if not pending_ticks:
            return False
        latest = _load_evidence(pending_ticks[-1].get("evidence_path"), evidence_root)
        if not isinstance(latest, Mapping):
            return False
        latest_checkpoint = latest.get("checkpoint", {})
        latest_engine = latest.get("engine", {})
        if (latest_checkpoint.get("status") != "reobserve"
                or latest_checkpoint.get("revision") != checkpoint.revision
                or latest_checkpoint.get("frame_id") != checkpoint.last_frame_id
                or latest_engine.get("after_frame_id") != pending["last_observed_frame_id"]
                or latest_engine.get("feedback") != {k: v for k, v in pending["feedback"].items() if k != "state"}):
            return False
        matches = []
        for tick in history:
            if (tick.get("run_id") != context.run_id or tick.get("status") != "reobserve"
                    or tick.get("verified_marches") != slot - 1):
                continue
            record = _load_evidence(tick.get("evidence_path"), evidence_root)
            if record is None:
                continue
            identity, engine = record.get("identity"), record.get("engine")
            selection = record.get("selection")
            if not isinstance(selection, Mapping) or selection.get("choice") != pending["action"]:
                continue  # later observation-only ticks are not originating dispatches
            if not isinstance(identity, Mapping) or not isinstance(engine, Mapping):
                return False
            runtime = record.get("runtime", {}).get("gather_job", {})
            original_feedback = dict(engine.get("feedback") or {})
            expected_feedback = {k: v for k, v in pending["feedback"].items() if k != "state"}
            # The resumed verifier updates only the receipt's last after frame.
            for value in (original_feedback, expected_feedback):
                value["facts"] = dict(value.get("facts") or {})
                value["facts"]["receipt"] = dict(value["facts"].get("receipt") or {})
                value["facts"]["receipt"].pop("after_frame_id", None)
            observed = _record_time(record.get("recorded_at"))
            reserved = _record_time(ledger._load(job)["reservations"][-1]["reserved_at"])
            if ((identity.get("mission_id"), identity.get("task_id"), identity.get("run_id"), identity.get("character_id"))
                    != (job.mission_id, job.task_id, context.run_id, job.character_id)
                    or Path(tick["evidence_path"]).resolve().parent != (evidence_root / _run_directory(identity)).resolve()
                    or record.get("checkpoint", {}).get("status") != "reobserve"
                    or engine.get("decision") != "reobserve" or engine.get("choice") != pending["action"]
                    or engine.get("before_frame_id") != before.frame_id
                    or engine.get("before_state") != before.state
                    or engine.get("before_observed_at") != before.observed_at
                    or engine.get("before_facts") != _snapshot_facts(before)
                    or original_feedback != expected_feedback
                    or runtime.get("job_id") != job.job_id or runtime.get("verified_marches") != slot - 1
                    or runtime.get("reserved_marches") != slot or runtime.get("journaled_this_tick") is not False
                    or (job.schema_version == 2 and (
                        runtime.get("resource_type") != job.resource_for_slot(slot)
                        or runtime.get("slot_catalog_digest") != job.catalog_for_slot(slot)
                        or runtime.get("schedule_digest") != job.schedule_digest))
                    or observed is None or reserved is None or not job.starts_at <= reserved <= observed < job.expires_at
                    or not isinstance(before.observed_at, (int, float)) or isinstance(before.observed_at, bool)
                    or not math.isfinite(before.observed_at)
                    or not 0 <= reserved.timestamp() - before.observed_at <= GATHER_JOB_MAX_FRAME_AGE_SECONDS):
                return False
            owners = []
            for path in sorted(attempt_root.glob("attempt-*.result.json")):
                report = json.loads(path.read_text(encoding="utf-8"))
                start = json.loads(path.with_name(path.name.replace(".result.json", ".start.json")).read_text(encoding="utf-8"))
                if tick in report.get("history", []):
                    started, ended = _record_time(start.get("started_at")), _record_time(report.get("recorded_at"))
                    if (started is not None and ended is not None and started <= reserved <= observed <= ended
                            and (job.schema_version != 2 or runtime.get("startup_attestation_sha256") == start.get("startup_attestation_sha256"))):
                        owners.append(path)
            if len(owners) != 1:
                return False
            matches.append(tick["evidence_path"])
        return len(matches) == 1
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, AttributeError):
        return False


def preflight_attempt_chain(
    job: GatherJobAuthority, ledger: JsonGatherJobStore,
    checkpoints: JsonMissionStore, attempt_root: Path, evidence_root: Path,
) -> None:
    """Reject an unaccounted prior attempt before the driver launches another tick."""
    progress = ledger.progress(job)
    journal = list(ledger.verifications(job))
    if progress.revoked:
        raise ValueError("GATHER job has revoked or unverified dispatch progress")
    history, errors = _attempt_chain_history(
        job, ledger, checkpoints, None, attempt_root, evidence_root, journal,
        allow_open_tail=True,
    )
    complete = [item for item in history if item.get("status") == "complete"]
    if progress.dispatched_marches == progress.verified_marches < job.max_marches:
        context = MissionContext(job.mission_id, job.task_id, gather_slot_run_id(job, progress.verified_marches + 1))
        checkpoint = checkpoints.load(context)
        pending = checkpoint.pending_verification if checkpoint is not None else None
        if (isinstance(pending, Mapping) and isinstance(pending.get("action"), Mapping)
                and pending["action"].get("action_id") == "MARCH_WITH_CURRENT_SELECTION"):
            errors.append("pending March lacks its durable dispatch reservation")
    if (progress.dispatched_marches != progress.verified_marches
            and (errors or not _pending_march_is_bound(job, ledger, checkpoints, history, attempt_root, evidence_root))):
        errors.append("unverified dispatch lacks exact bound pending March proof")
    if len(complete) != progress.verified_marches:
        errors.append("attempt chain does not account for durable VERIFIED progress")
    for item in complete:
        slot = item["verified_marches"]
        if type(slot) is not int or not 1 <= slot <= len(journal):
            errors.append("attempt chain has an invalid VERIFIED slot")
            continue
        verified_at = _record_time(journal[slot - 1].get("verified_at"))
        if verified_at is None or not job.starts_at <= verified_at < job.expires_at:
            errors.append(f"slot {slot} VERIFIED outside job time scope")
        matches = _bridge_artifacts(job, slot, journal, ledger, checkpoints, evidence_root, attempt_root)
        if (len(matches) != 1 or not isinstance(item.get("evidence_path"), str)
                or Path(item["evidence_path"]).resolve() != Path(matches[0]).resolve()):
            errors.append(f"slot {slot} lacks one matching durable per-tick artifact")
    if errors:
        raise ValueError("GATHER attempt chain preflight blocked: " + "; ".join(errors))


def audit_first_done_job(
    job: GatherJobAuthority, ledger: JsonGatherJobStore,
    checkpoints: JsonMissionStore, driver_report: Mapping[str, Any],
    evidence_root: Path,
    *, attempt_root: Path | None = None, historical_replay: bool = False,
) -> dict[str, Any]:
    """Validate one structural closeout without promoting it to live proof."""
    errors: list[str] = []
    progress = ledger.progress(job)
    journal = ledger.verifications(job)
    reservations = ledger.reservations(job)
    if historical_replay and attempt_root is None and "attempt_sequence" not in driver_report:
        history = driver_report.get("history")
    elif attempt_root is None or "attempt_sequence" not in driver_report:
        errors.append("authoritative closeout needs a durable attempt chain")
        history = []
    else:
        history, chain_errors = _attempt_chain_history(
            job, ledger, checkpoints, driver_report,
            attempt_root, evidence_root, journal,
        )
        errors.extend(chain_errors)
    if (driver_report.get("job_id") != job.job_id
            or driver_report.get("status") != "complete"
            or driver_report.get("verified_marches") != 5
            or driver_report.get("closeout") != list(journal)
            or type(driver_report.get("ticks")) is not int
            or not isinstance(history, list)
            or (historical_replay
                and driver_report.get("ticks") != len(history))
            or not _history_matches_job(job, history)):
        errors.append("driver attempt chain has no matching complete five-entry closeout")
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
            if record is not None and (_evidence_matches(entry, record, job, expected_engine)
                    or _recovery_matches(entry, Path(item["evidence_path"]), job, expected_engine, ledger, checkpoints, evidence_root, attempt_root)):
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
        "audit_scope": "historical_replay_only" if historical_replay else "authoritative_attempt_chain",
        "closeout_authoritative": not historical_replay and not errors,
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
    parser.add_argument("--resource-type", choices=("FOOD", "WOOD", "STONE", "GOLD"),
                        help="legacy single-resource job only")
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
        artifact = json.loads(args.gather_job.read_text(encoding="utf-8"))
        if artifact.get("schema_version") == 2:
            if args.resource_type is not None or args.resource_level is not None:
                raise ValueError("mixed GATHER audit uses authority schedule and level")
            resource_type = artifact["resource_schedule"][0]
            resource_level = artifact["resource_level"]
        else:
            resource_type, resource_level = args.resource_type, args.resource_level
        compiled = compile_mission(
            ROOT / "config" / "mission_flows.yaml", ROOT / "config" / "ui_states.yaml",
            "GATHER_RESOURCE",
            {"resource_type": resource_type, "resource_level": resource_level},
        )
        catalog = compiled_gather_catalog(compiled)
        job = load_gather_job_authority(
            args.gather_job, canonical_actions=catalog.actions,
            expected_catalog_digest=catalog.digest,
        )
        validate_schedule_catalog(job, ROOT / "config" / "mission_flows.yaml",
                                  ROOT / "config" / "ui_states.yaml")
        report = json.loads(args.driver_report.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError("driver report is not an object")
        verdict = audit_first_done_job(
            job, JsonGatherJobStore(args.ledger_root), JsonMissionStore(args.checkpoint_root),
            report, args.evidence_root, attempt_root=args.driver_report.parent,
        )
        destination = write_verdict(args.output, workspace, verdict)
        print(json.dumps({**verdict, "report_path": str(destination)}, ensure_ascii=False))
        return 0 if verdict["status"] == "OFFLINE_REPLAY_PASS" else 3
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
