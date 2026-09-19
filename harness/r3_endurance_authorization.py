"""Bounded authorization and reservation for live R3 repetition.

The readiness audit answers whether an operator has authorized the remaining
R3 repetitions.  This module is the execution-side authority: a live helper
must reserve one unique run before it can dispatch input.  Reservations are
append-only and conservative.  A failed or interrupted attempt still consumes
one authorized slot; it can never be silently retried under the same budget.

This module does not capture the desktop, start ROK, or emit input.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping


R3_SCOPE = "r3_live_gather_repetition"
R3_MEASUREMENT_CLASS = "r3_live_gather_repetition"
ACTIVE_R3_CONTRACT = {
    "mission_id": "GATHER_RESOURCE",
    "task_id": "one-character",
    "character_id": "char-direct-01",
}
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,96}$")


class R3AuthorizationError(ValueError):
    """The bounded R3 authorization or reservation contract is invalid."""


def _iso8601(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    # A local timestamp would make operator authorization ambiguous across
    # machines.  Require an explicit UTC offset while keeping ISO-8601 forms.
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def authorization_reasons(
    authorization: Mapping[str, Any] | None,
    *,
    required_additional_runs: int,
    expected_contract: Mapping[str, Any] = ACTIVE_R3_CONTRACT,
) -> list[str]:
    """Return all reasons an authorization cannot release bounded R3 runs."""
    if authorization is None:
        return ["explicit endurance authorization is missing"]
    reasons: list[str] = []
    if authorization.get("schema_version") != 1:
        reasons.append("endurance authorization schema_version is unsupported")
    if authorization.get("scope") != R3_SCOPE:
        reasons.append("endurance authorization scope is not bounded R3 repetition")
    if authorization.get("approved") is not True:
        reasons.append("endurance authorization is not approved")
    for field in ("mission_id", "task_id", "character_id"):
        expected = expected_contract.get(field)
        if authorization.get(field) != expected:
            reasons.append(f"endurance authorization {field} does not match the active contract")
    approved_by = authorization.get("approved_by")
    if not isinstance(approved_by, str) or not approved_by.strip():
        reasons.append("endurance authorization approved_by is missing")
    approved_at = authorization.get("approved_at")
    if not isinstance(approved_at, str) or not approved_at.strip():
        reasons.append("endurance authorization approved_at is missing")
    elif not _iso8601(approved_at):
        reasons.append("endurance authorization approved_at is not ISO 8601")
    max_runs = authorization.get("max_additional_runs")
    if type(max_runs) is not int or max_runs < required_additional_runs:
        reasons.append(
            f"endurance authorization max_additional_runs is below the required {required_additional_runs}"
        )
    return reasons


def load_json_object(path: Path) -> Mapping[str, Any]:
    """Load one JSON object, failing closed on malformed or non-object data."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise R3AuthorizationError(f"could not read JSON: {path}: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise R3AuthorizationError(f"JSON root must be an object: {path}")
    return raw


def manifest_contract(manifest: Mapping[str, Any]) -> tuple[dict[str, Any], set[str], int]:
    """Return the active contract, registered IDs, and required run count."""
    if manifest.get("schema_version") != 1:
        raise R3AuthorizationError("R3 manifest must use schema_version=1")
    contract = manifest.get("contract")
    runs = manifest.get("runs")
    if not isinstance(contract, Mapping) or not isinstance(runs, list):
        raise R3AuthorizationError("R3 manifest contract and runs are required")
    required_runs = contract.get("required_runs")
    if type(required_runs) is not int or required_runs < 1:
        raise R3AuthorizationError("R3 manifest contract.required_runs must be positive")
    identity = {field: contract.get(field) for field in ACTIVE_R3_CONTRACT}
    if any(not isinstance(value, str) or not value for value in identity.values()):
        raise R3AuthorizationError("R3 manifest contract identity is incomplete")
    for field, expected in ACTIVE_R3_CONTRACT.items():
        if identity[field] != expected:
            raise R3AuthorizationError(
                f"R3 manifest contract {field} does not match the active one-character contract"
            )
    registered: set[str] = set()
    for registration in runs:
        if not isinstance(registration, Mapping):
            raise R3AuthorizationError("each R3 registration must be an object")
        run_id = registration.get("run_id")
        if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
            raise R3AuthorizationError("each R3 registration needs a bounded run_id")
        if run_id in registered:
            raise R3AuthorizationError(f"duplicate registered R3 run_id: {run_id}")
        registered.add(run_id)
    return dict(contract), registered, required_runs


def _read_reservations(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise R3AuthorizationError(f"could not read R3 reservation ledger: {path}: {exc}") from exc
    reservations: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise R3AuthorizationError(
                f"R3 reservation ledger line {line_number} is not JSON"
            ) from exc
        if not isinstance(raw, Mapping):
            raise R3AuthorizationError(f"R3 reservation ledger line {line_number} is not an object")
        if raw.get("schema_version") != 1 or raw.get("scope") != R3_SCOPE:
            raise R3AuthorizationError(f"R3 reservation ledger line {line_number} has unsupported schema")
        run_id = raw.get("run_id")
        if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
            raise R3AuthorizationError(f"R3 reservation ledger line {line_number} has invalid run_id")
        for field in ("mission_id", "task_id", "character_id", "reserved_at"):
            if not isinstance(raw.get(field), str) or not raw.get(field):
                raise R3AuthorizationError(
                    f"R3 reservation ledger line {line_number} is missing {field}"
                )
        reservations.append(dict(raw))
    return reservations


def _authorization_digest(authorization: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(authorization), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def reserve_run(
    authorization: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    run_id: str,
    ledger_path: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Reserve one R3 attempt and append an immutable ticket to the ledger.

    The ticket is written immediately before dispatch by the live helper.  It
    is intentionally never removed or rewritten, including when the eventual
    desktop attempt fails.  This makes the authorization a hard upper bound on
    attempts rather than a best-effort success counter.
    """
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
        raise R3AuthorizationError("run-id must be a bounded ASCII identifier")
    contract, registered, required_runs = manifest_contract(manifest)
    remaining_required = max(0, required_runs - len(registered))
    reasons = authorization_reasons(
        authorization,
        required_additional_runs=remaining_required,
        expected_contract=contract,
    )
    if reasons:
        raise R3AuthorizationError("; ".join(reasons))
    if remaining_required <= 0:
        raise R3AuthorizationError("R3 manifest already satisfies required_runs")

    reservations = _read_reservations(ledger_path)
    known_ids = set(registered)
    for reservation in reservations:
        identity_matches = all(
            reservation.get(field) == contract.get(field)
            for field in ("mission_id", "task_id", "character_id")
        )
        if identity_matches:
            known_ids.add(str(reservation["run_id"]))
    if run_id in known_ids:
        raise R3AuthorizationError(f"R3 run_id is already registered or reserved: {run_id}")

    max_additional = authorization.get("max_additional_runs")
    assert type(max_additional) is int  # authorization_reasons checked it
    identity_reservations = [
        reservation
        for reservation in reservations
        if all(reservation.get(field) == contract.get(field) for field in ACTIVE_R3_CONTRACT)
    ]
    if len(identity_reservations) >= max_additional:
        raise R3AuthorizationError("R3 endurance authorization attempt budget is exhausted")
    if len(known_ids) >= required_runs:
        raise R3AuthorizationError("R3 repetition threshold has no unreserved attempt remaining")

    stamp = (now or datetime.now(timezone.utc))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise R3AuthorizationError("reservation timestamp must include an ISO-8601 offset")
    ticket = {
        "schema_version": 1,
        "measurement_class": R3_MEASUREMENT_CLASS,
        "scope": R3_SCOPE,
        "run_id": run_id,
        "mission_id": contract["mission_id"],
        "task_id": contract["task_id"],
        "character_id": contract["character_id"],
        "reserved_at": stamp.isoformat(),
        "authorization_sha256": _authorization_digest(authorization),
        "attempt_index": len(known_ids) + 1,
        "input_emitted": False,
        "status": "reserved",
    }
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(ticket, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    try:
        descriptor = os.open(str(ledger_path), os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise R3AuthorizationError(f"could not append R3 reservation ledger: {ledger_path}: {exc}") from exc
    return ticket


def load_reserved_ticket(
    ledger_path: Path,
    *,
    run_id: str,
    expected_contract: Mapping[str, Any] = ACTIVE_R3_CONTRACT,
) -> dict[str, Any]:
    """Load exactly one still-reserved ticket for a live R3 dispatch."""
    reservations = _read_reservations(ledger_path)
    matches = [
        reservation
        for reservation in reservations
        if reservation.get("run_id") == run_id
        and all(reservation.get(field) == expected_contract.get(field) for field in ACTIVE_R3_CONTRACT)
    ]
    if len(matches) != 1:
        raise R3AuthorizationError(
            f"R3 reservation for {run_id!r} must have exactly one matching ticket"
        )
    ticket = matches[0]
    if ticket.get("status") != "reserved" or ticket.get("input_emitted") is not False:
        raise R3AuthorizationError("R3 reservation ticket is not a fresh non-input reservation")
    return ticket
