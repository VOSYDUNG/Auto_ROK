"""Durable runtime evidence for the one-character GATHER_RESOURCE vertical slice.

This module records what the canonical runtime actually observed/selected/
dispatched/verified.  It does not replay clicks and it does not promote a
DISPATCHED receipt to success.  A live replay is accepted only from the fresh
post-action evidence already verified by MissionEngine.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import time
from typing import Any, Mapping, Sequence

from harness.mission_runner import MissionTickResult
from harness.mission_runtime import MissionContext, ToolSnapshot


SCHEMA_VERSION = 1
_REPLAY_FACT_KEYS = (
    "character_id",
    "character_id_source",
    "march_queue_used",
    "march_queue_capacity",
    "march_queue_source",
    "selected_search_level",
    "selected_search_level_source",
    "precondition_evidence_source",
)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return repr(value)


def _snapshot_facts(snapshot: ToolSnapshot | None) -> dict[str, Any]:
    if snapshot is None:
        return {}
    result: dict[str, Any] = {}
    for key in _REPLAY_FACT_KEYS:
        if key in snapshot.facts:
            result[key] = _json_safe(snapshot.facts[key])
    evidence = snapshot.facts.get("precondition_evidence")
    if isinstance(evidence, Mapping):
        result["precondition_evidence"] = _json_safe(evidence)
    return result


def build_gather_tick_evidence(
    *,
    context: MissionContext,
    character_id: str,
    result: MissionTickResult,
    live_armed: bool,
    policy_approval: Mapping[str, Any] | None,
    main_view_profile_trained: bool,
    resource_level_profile_trained: bool,
) -> dict[str, Any]:
    """Convert one canonical MissionRunner tick into a durable evidence record."""
    selection: dict[str, Any] | None = None
    if result.selection is not None:
        selection = {
            "decision": result.selection.decision.value,
            "reason": result.selection.reason,
            "candidate_count": len(result.selection.candidates),
        }
        if result.selection.choice is not None:
            selection["choice"] = {
                "action_id": result.selection.choice.action_id,
                "target_id": result.selection.choice.target_id,
                "arguments": _json_safe(dict(result.selection.choice.arguments)),
            }

    engine: dict[str, Any] | None = None
    if result.engine_result is not None:
        step = result.engine_result
        engine = {
            "decision": step.decision.value,
            "reason": step.reason,
            "before_frame_id": step.snapshot.frame_id,
            "before_state": step.snapshot.state,
            "before_facts": _snapshot_facts(step.snapshot),
            "after_frame_id": step.after_snapshot.frame_id if step.after_snapshot is not None else None,
            "after_state": step.after_snapshot.state if step.after_snapshot is not None else None,
            "after_facts": _snapshot_facts(step.after_snapshot),
            "choice": None,
            "feedback": None,
        }
        if step.choice is not None:
            engine["choice"] = {
                "action_id": step.choice.action_id,
                "target_id": step.choice.target_id,
                "arguments": _json_safe(dict(step.choice.arguments)),
            }
        if step.feedback is not None:
            engine["feedback"] = {
                "success": step.feedback.success,
                "code": step.feedback.code,
                "completed": step.feedback.completed,
                "reobserve_required": step.feedback.reobserve_required,
                "facts": _json_safe(dict(step.feedback.facts)),
                "message": step.feedback.message,
            }

    return {
        "schema_version": SCHEMA_VERSION,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "identity": {
            "mission_id": context.mission_id,
            "task_id": context.task_id,
            "run_id": context.run_id,
            "attempt": context.attempt,
            "character_id": character_id,
        },
        "runtime": {
            "live_armed": bool(live_armed),
            "main_view_profile_trained": bool(main_view_profile_trained),
            "resource_level_profile_trained": bool(resource_level_profile_trained),
            "policy_approval": _json_safe(dict(policy_approval or {})),
        },
        "checkpoint": {
            "status": result.status.value,
            "revision": result.checkpoint.revision,
            "frame_id": result.checkpoint.last_frame_id,
            "state": result.checkpoint.last_state,
            "decision": result.checkpoint.last_decision,
            "reason": result.checkpoint.last_reason,
            "updated_at": result.checkpoint.updated_at,
        },
        "selection": selection,
        "engine": engine,
        "runner_reason": result.reason,
    }


def save_gather_tick_evidence(root: str | Path, record: Mapping[str, Any]) -> Path:
    """Atomically persist one tick without overwriting earlier evidence."""
    identity = record.get("identity")
    checkpoint = record.get("checkpoint")
    if not isinstance(identity, Mapping) or not isinstance(checkpoint, Mapping):
        raise ValueError("gather evidence record requires identity and checkpoint mappings")
    run_id = identity.get("run_id")
    revision = checkpoint.get("revision")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("gather evidence record requires run_id")
    if type(revision) is not int or revision < 0:
        raise ValueError("gather evidence record requires non-negative checkpoint revision")

    directory = Path(root) / run_id
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.time_ns()
    path = directory / f"revision-{revision:06d}-{stamp}.json"
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    payload = json.dumps(_json_safe(dict(record)), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return path


def load_gather_replay_records(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    files = sorted(source.glob("*.json")) if source.is_dir() else [source]
    records: list[dict[str, Any]] = []
    for file in files:
        try:
            value = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read gather replay evidence {file}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"gather replay evidence {file} must contain an object")
        records.append(value)
    return records


def validate_gather_replay(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Validate a real one-character GATHER completion evidence set fail-closed."""
    errors: list[str] = []
    if not records:
        return {"status": "FAIL", "errors": ["no gather replay evidence records supplied"]}

    identities: set[tuple[Any, ...]] = set()
    revisions: list[int] = []
    completion_candidates: list[Mapping[str, Any]] = []

    for index, record in enumerate(records):
        if record.get("schema_version") != SCHEMA_VERSION:
            errors.append(f"record {index} has unsupported schema_version")
            continue
        identity = record.get("identity")
        checkpoint = record.get("checkpoint")
        if not isinstance(identity, Mapping) or not isinstance(checkpoint, Mapping):
            errors.append(f"record {index} is missing identity/checkpoint")
            continue
        identities.add(
            (
                identity.get("mission_id"),
                identity.get("task_id"),
                identity.get("run_id"),
                identity.get("attempt"),
                identity.get("character_id"),
            )
        )
        revision = checkpoint.get("revision")
        if type(revision) is not int or revision < 0:
            errors.append(f"record {index} has invalid checkpoint revision")
        else:
            revisions.append(revision)
        if checkpoint.get("status") == "complete" and isinstance(record.get("engine"), Mapping):
            completion_candidates.append(record)

    if len(identities) != 1:
        errors.append("replay evidence spans more than one mission/task/run/attempt/character identity")
    else:
        identity = next(iter(identities))
        if identity[0] != "GATHER_RESOURCE":
            errors.append("replay evidence is not for GATHER_RESOURCE")
        if not isinstance(identity[4], str) or not identity[4]:
            errors.append("replay evidence lacks a character_id")

    if revisions and revisions != sorted(revisions):
        errors.append("checkpoint revisions are not monotonic")

    if not completion_candidates:
        errors.append("no COMPLETE record contains engine verification evidence")
    else:
        final = completion_candidates[-1]
        runtime = final.get("runtime")
        engine = final.get("engine")
        identity = final.get("identity")
        if not isinstance(runtime, Mapping) or not isinstance(engine, Mapping) or not isinstance(identity, Mapping):
            errors.append("completion record is malformed")
        else:
            if runtime.get("live_armed") is not True:
                errors.append("completion was not produced with live input armed")
            if runtime.get("main_view_profile_trained") is not True:
                errors.append("completion lacks trained main-view profile evidence")
            if runtime.get("resource_level_profile_trained") is not True:
                errors.append("completion lacks trained resource-level profile evidence")
            approval = runtime.get("policy_approval")
            if not isinstance(approval, Mapping) or approval.get("bound_to_occurrence") is not True:
                errors.append("completion lacks occurrence-bound troop selection approval")

            if engine.get("decision") != "complete":
                errors.append("completion checkpoint was not produced by EngineDecision.COMPLETE")
            before_frame = engine.get("before_frame_id")
            after_frame = engine.get("after_frame_id")
            if not isinstance(before_frame, str) or not before_frame:
                errors.append("completion lacks before_frame_id")
            if not isinstance(after_frame, str) or not after_frame:
                errors.append("completion lacks after_frame_id")
            if before_frame == after_frame:
                errors.append("completion before/after frames are not fresh")

            feedback = engine.get("feedback")
            if not isinstance(feedback, Mapping) or feedback.get("code") != "VERIFIED":
                errors.append("completion lacks VERIFIED feedback")
            else:
                feedback_facts = feedback.get("facts")
                receipt = feedback_facts.get("receipt") if isinstance(feedback_facts, Mapping) else None
                if not isinstance(receipt, Mapping):
                    errors.append("completion lacks dispatch receipt")
                else:
                    if receipt.get("before_frame_id") != before_frame:
                        errors.append("receipt before_frame_id does not match completion evidence")
                    if receipt.get("after_frame_id") != after_frame:
                        errors.append("receipt after_frame_id does not match completion evidence")
                    if receipt.get("non_interference_confirmed") is not True:
                        errors.append("receipt lacks non-interference confirmation")
                    if receipt.get("character_id") != identity.get("character_id"):
                        errors.append("receipt character_id does not match replay identity")

            before_facts = engine.get("before_facts")
            after_facts = engine.get("after_facts")
            if not isinstance(before_facts, Mapping) or not isinstance(after_facts, Mapping):
                errors.append("completion lacks before/after fact snapshots")
            else:
                before_used = before_facts.get("march_queue_used")
                after_used = after_facts.get("march_queue_used")
                if type(before_used) is not int or type(after_used) is not int or after_used <= before_used:
                    errors.append("march_queue_used did not increase on the completion transition")
                if before_facts.get("character_id") != identity.get("character_id"):
                    errors.append("before snapshot character_id does not match replay identity")
                if after_facts.get("character_id") != identity.get("character_id"):
                    errors.append("after snapshot character_id does not match replay identity")

    return {
        "status": "PASS" if not errors else "FAIL",
        "record_count": len(records),
        "completion_records": len(completion_candidates),
        "identity_count": len(identities),
        "errors": errors,
    }
