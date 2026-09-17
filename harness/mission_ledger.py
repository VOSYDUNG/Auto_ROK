"""Deterministic daily occurrence ledger with explicit evidence and verification."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class LedgerError(ValueError):
    pass


TERMINAL = {"VERIFIED", "CANCELLED", "FAILED"}


def parse_time(value: str) -> datetime:
    if not isinstance(value, str):
        raise LedgerError("time must be ISO-8601 text")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LedgerError("invalid ISO-8601 time") from exc
    if result.tzinfo is None:
        raise LedgerError("time requires timezone")
    return result


def fixed_timezone(value: str) -> timezone:
    if not isinstance(value, str) or len(value) != 6 or value[0] not in "+-" or value[3] != ":":
        raise LedgerError("timezone must be a fixed offset such as +07:00")
    try:
        hours, minutes = int(value[1:3]), int(value[4:6])
    except ValueError as exc:
        raise LedgerError("invalid timezone offset") from exc
    if hours > 14 or minutes > 59:
        raise LedgerError("invalid timezone offset")
    delta = timedelta(hours=hours, minutes=minutes)
    if value[0] == "-": delta = -delta
    return timezone(delta)


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict) or plan.get("schema_version") != 1:
        raise LedgerError("plan schema_version must be 1")
    for key in ("mission_id", "timezone", "due_local"):
        if not isinstance(plan.get(key), str) or not plan[key]:
            raise LedgerError(f"plan {key} is required")
    fixed_timezone(plan["timezone"])
    try:
        datetime.strptime(plan["due_local"], "%H:%M")
    except ValueError as exc:
        raise LedgerError("due_local must be HH:MM") from exc
    if type(plan.get("max_attempts")) is not int or not 1 <= plan["max_attempts"] <= 3:
        raise LedgerError("max_attempts must be 1..3")
    backoff = plan.get("retry_backoff_seconds")
    if not isinstance(backoff, list) or len(backoff) < plan["max_attempts"] or any(type(x) is not int or not 1 <= x <= 86400 for x in backoff):
        raise LedgerError("retry_backoff_seconds must cover every attempt")
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        raise LedgerError("plan requires steps")
    seen = set()
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("id"), str) or step["id"] in seen:
            raise LedgerError("step ids must be unique strings")
        seen.add(step["id"])
        if set(step) != {"id", "target_id", "proposal", "preconditions", "postconditions"}:
            raise LedgerError("step fields are invalid")
        if not isinstance(step["target_id"], str) or not step["target_id"]:
            raise LedgerError("step target_id is required")
        if not isinstance(step["proposal"], dict) or not isinstance(step["preconditions"], list) or not isinstance(step["postconditions"], list):
            raise LedgerError("step contract is invalid")
    return plan


def occurrence(plan: dict[str, Any], now: datetime) -> tuple[str, str, str]:
    local = now.astimezone(fixed_timezone(plan["timezone"]))
    day = local.date().isoformat()
    due_local = datetime.strptime(day + "T" + plan["due_local"], "%Y-%m-%dT%H:%M").replace(tzinfo=local.tzinfo)
    return f"{plan['mission_id']}:{day}", day, due_local.astimezone(timezone.utc).isoformat()


def new_ledger(plan: dict[str, Any], now: datetime) -> dict[str, Any]:
    occurrence_id, day, due_at = occurrence(plan, now)
    return {"schema_version": 1, "mission_id": plan["mission_id"], "occurrence_id": occurrence_id,
            "local_date": day, "timezone": plan["timezone"], "due_at": due_at, "status": "PENDING",
            "step_index": 0, "attempts": 0, "next_retry_at": None, "pending_proposal": None,
            "events": [], "outcome": None}


def validate_ledger(plan: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(ledger, dict) or ledger.get("schema_version") != 1 or ledger.get("mission_id") != plan["mission_id"]:
        raise LedgerError("checkpoint does not match plan")
    if ledger.get("status") not in {"PENDING", "WAITING", "PROPOSED", "NEEDS_DECISION", *TERMINAL}:
        raise LedgerError("checkpoint status is invalid")
    if type(ledger.get("step_index")) is not int or not 0 <= ledger["step_index"] < len(plan["steps"]):
        raise LedgerError("checkpoint step_index is invalid")
    if type(ledger.get("attempts")) is not int or not 0 <= ledger["attempts"] <= plan["max_attempts"]:
        raise LedgerError("checkpoint attempts are invalid")
    if not isinstance(ledger.get("events"), list):
        raise LedgerError("checkpoint events must be a list")
    if ledger["status"] == "PROPOSED" and not isinstance(ledger.get("pending_proposal"), dict):
        raise LedgerError("proposed checkpoint lacks pending proposal")
    if ledger["status"] == "VERIFIED":
        outcome, pending = ledger.get("outcome"), ledger.get("pending_proposal")
        receipt = outcome.get("receipt") if isinstance(outcome, dict) else None
        verified_events = [event for event in ledger["events"] if event.get("type") == "VERIFIED"]
        if (not isinstance(receipt, dict) or outcome.get("status") != "verified" or not isinstance(pending, dict)
                or receipt.get("before_frame") != pending.get("observation") or len(verified_events) != 1):
            raise LedgerError("verified checkpoint lacks matching receipt evidence")
        after = receipt.get("after_frame")
        if not isinstance(after, dict) or after.get("frame_id") == pending["observation"].get("frame_id") or after.get("image_sha256") == pending["observation"].get("image_sha256"):
            raise LedgerError("verified checkpoint after-frame is invalid")
    if ledger["status"] == "FAILED" and (ledger["attempts"] != plan["max_attempts"] or not isinstance(ledger.get("outcome"), dict)):
        raise LedgerError("failed checkpoint lacks exhausted outcome")
    return ledger


def scene_ref(scene: dict[str, Any], path: str) -> dict[str, str]:
    if not isinstance(scene, dict) or scene.get("status") != "READY" or not isinstance(scene.get("scene"), dict):
        raise LedgerError("observation scene is not READY")
    body = scene["scene"]
    frame = body.get("frame_id")
    image_hash = body.get("facts", {}).get("image_sha256")
    if not isinstance(frame, str) or not isinstance(image_hash, str) or len(image_hash) != 64:
        raise LedgerError("scene lacks frame/hash evidence")
    return {"scene_path": path, "frame_id": frame, "image_sha256": image_hash}


def append_event(ledger: dict[str, Any], kind: str, at: datetime, data: dict[str, Any], key: str) -> None:
    if any(event.get("key") == key for event in ledger["events"]):
        return
    ledger["events"].append({"seq": len(ledger["events"]) + 1, "key": key, "type": kind,
                             "at": at.astimezone(timezone.utc).isoformat(), "data": data})


def _target(scene: dict[str, Any], target_id: str) -> dict[str, Any] | None:
    matches = [x for x in scene["scene"].get("targets", []) if isinstance(x, dict) and x.get("target_id") == target_id]
    return matches[0] if len(matches) == 1 else None


def verify_receipt(plan: dict[str, Any], ledger: dict[str, Any], receipt: dict[str, Any], at: datetime,
                   evidence: dict[str, dict[str, Any]] | None) -> None:
    pending = ledger.get("pending_proposal")
    if ledger["status"] != "PROPOSED" or not isinstance(pending, dict):
        raise LedgerError("verification requires a pending proposal")
    required = {"schema_version", "mission_id", "occurrence_id", "step_id", "outcome", "before_frame", "after_frame", "verified_at"}
    if not isinstance(receipt, dict) or set(receipt) != required or receipt["schema_version"] != 1:
        raise LedgerError("verification receipt schema is invalid")
    if (receipt["mission_id"], receipt["occurrence_id"], receipt["step_id"], receipt["outcome"]) != (ledger["mission_id"], ledger["occurrence_id"], pending["step_id"], "verified"):
        raise LedgerError("verification receipt does not match occurrence")
    if receipt["before_frame"] != pending["observation"]:
        raise LedgerError("verification before-frame does not match proposal")
    after = receipt["after_frame"]
    if not isinstance(after, dict) or set(after) != {"scene_path", "frame_id", "image_sha256"} or after["frame_id"] == pending["observation"]["frame_id"] or after["image_sha256"] == pending["observation"]["image_sha256"]:
        raise LedgerError("verification requires distinct matching after-frame references")
    if not isinstance(evidence, dict):
        raise LedgerError("verification requires referenced scene evidence")
    for reference in (receipt["before_frame"], after):
        path = reference["scene_path"]
        if path not in evidence or scene_ref(evidence[path], path) != reference:
            raise LedgerError("verification frame reference does not match scene evidence")
    if parse_time(receipt["verified_at"]) > at + timedelta(seconds=5):
        raise LedgerError("verification receipt is future-dated")
    final = ledger["step_index"] == len(plan["steps"]) - 1
    append_event(ledger, "VERIFIED" if final else "VERIFIED_STEP", at, {"step_id": pending["step_id"], "after_frame": after}, "verified:" + pending["proposal_id"])
    if final:
        ledger["status"] = "VERIFIED"; ledger["outcome"] = {"status": "verified", "receipt": receipt}
    else:
        ledger["step_index"] += 1; ledger["status"] = "PENDING"; ledger["attempts"] = 0; ledger["next_retry_at"] = None; ledger["pending_proposal"] = None


def validate_verified_evidence(ledger: dict[str, Any], evidence: dict[str, dict[str, Any]] | None) -> None:
    receipt = ledger["outcome"]["receipt"]
    if not isinstance(evidence, dict):
        raise LedgerError("verified restart requires referenced scene evidence")
    for reference in (receipt["before_frame"], receipt["after_frame"]):
        path = reference["scene_path"]
        if path not in evidence or scene_ref(evidence[path], path) != reference:
            raise LedgerError("verified restart scene evidence is missing or changed")


def tick(plan: dict[str, Any], scene: dict[str, Any] | None, scene_path: str | None, ledger: dict[str, Any] | None,
         now: datetime, *, cancel: bool = False, receipt: dict[str, Any] | None = None,
         receipt_evidence: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    validate_plan(plan); current_id, _, _ = occurrence(plan, now)
    ledger = new_ledger(plan, now) if ledger is None else validate_ledger(plan, ledger)
    if ledger["status"] == "VERIFIED":
        validate_verified_evidence(ledger, receipt_evidence)
    if ledger["occurrence_id"] != current_id:
        if ledger["status"] not in TERMINAL:
            raise LedgerError("previous daily occurrence is unfinished")
        ledger = new_ledger(plan, now)
    if ledger["status"] in TERMINAL:
        return ledger
    if cancel:
        ledger["status"] = "CANCELLED"; ledger["outcome"] = {"status": "cancelled"}
        append_event(ledger, "CANCELLED", now, {}, "cancel:" + ledger["occurrence_id"]); return ledger
    if receipt is not None:
        verify_receipt(plan, ledger, receipt, now, receipt_evidence); return ledger
    if now < parse_time(ledger["due_at"]):
        ledger["status"] = "WAITING"; append_event(ledger, "WAITING", now, {"due_at": ledger["due_at"]}, "wait:" + ledger["occurrence_id"]); return ledger
    if ledger["status"] == "PROPOSED":
        return ledger
    if ledger["next_retry_at"] and now < parse_time(ledger["next_retry_at"]):
        return ledger
    if scene is None or scene_path is None:
        reason, ref, target = "observation evidence missing", None, None
    else:
        ref = scene_ref(scene, scene_path); target = _target(scene, plan["steps"][ledger["step_index"]]["target_id"])
        reason = None if target else "required target absent or ambiguous"
    if reason:
        ledger["attempts"] += 1
        if ledger["attempts"] >= plan["max_attempts"]:
            ledger["status"] = "FAILED"; ledger["outcome"] = {"status": "failed", "reason": reason}
        else:
            ledger["status"] = "NEEDS_DECISION"; ledger["next_retry_at"] = (now + timedelta(seconds=plan["retry_backoff_seconds"][ledger["attempts"] - 1])).isoformat()
        append_event(ledger, ledger["status"], now, {"reason": reason, "observation": ref, "attempt": ledger["attempts"]}, f"{ledger['status']}:{ledger['attempts']}:{ref}")
        return ledger
    step = plan["steps"][ledger["step_index"]]
    proposal_id = hashlib.sha256(json.dumps({"occurrence": ledger["occurrence_id"], "step": step["id"], "observation": ref}, sort_keys=True).encode()).hexdigest()[:20]
    ledger["pending_proposal"] = {"proposal_id": proposal_id, "step_id": step["id"], "target": target,
                                   "proposal": step["proposal"], "observation": ref, "issued": False}
    ledger["status"] = "PROPOSED"; ledger["next_retry_at"] = None
    append_event(ledger, "PROPOSED", now, ledger["pending_proposal"], "proposal:" + proposal_id)
    return ledger


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, path)
