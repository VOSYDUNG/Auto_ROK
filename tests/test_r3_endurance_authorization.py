from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from harness.r3_endurance_authorization import (
    ACTIVE_R3_CONTRACT,
    R3AuthorizationError,
    authorization_reasons,
    load_reserved_ticket,
    manifest_contract,
    reserve_run,
)


def _authorization(*, max_additional_runs: int = 2) -> dict[str, object]:
    return {
        "schema_version": 1,
        "scope": "r3_live_gather_repetition",
        "approved": True,
        **ACTIVE_R3_CONTRACT,
        "approved_by": "operator",
        "approved_at": "2026-09-19T10:00:00+07:00",
        "max_additional_runs": max_additional_runs,
    }


def _manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "contract": {
            **ACTIVE_R3_CONTRACT,
            "required_runs": 3,
            "minimum_successes": 2,
            "required_queue_delta": 1,
        },
        "runs": [{"run_id": "run-1", "evidence_path": "x"}],
    }


def test_authorization_is_strict_about_timezone_and_scope() -> None:
    authorization = _authorization()
    assert authorization_reasons(authorization, required_additional_runs=2) == []
    authorization["approved_at"] = "2026-09-19T10:00:00"
    assert any("ISO 8601" in reason for reason in authorization_reasons(authorization, required_additional_runs=2))


def test_manifest_contract_returns_registered_identity() -> None:
    contract, registered, required = manifest_contract(_manifest())
    assert contract["mission_id"] == "GATHER_RESOURCE"
    assert registered == {"run-1"}
    assert required == 3


def test_reservation_is_append_only_and_caps_attempts(tmp_path: Path) -> None:
    ledger = tmp_path / "R3_RUN_RESERVATIONS.jsonl"
    manifest = _manifest()
    authorization = _authorization()
    first = reserve_run(
        authorization,
        manifest,
        run_id="run-2",
        ledger_path=ledger,
        now=datetime(2026, 9, 19, 3, 0, tzinfo=timezone.utc),
    )
    assert first["attempt_index"] == 2
    second = reserve_run(
        authorization,
        manifest,
        run_id="run-3",
        ledger_path=ledger,
        now=datetime(2026, 9, 19, 3, 1, tzinfo=timezone.utc),
    )
    assert second["attempt_index"] == 3
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 2
    with pytest.raises(R3AuthorizationError, match="attempt budget is exhausted"):
        reserve_run(authorization, manifest, run_id="run-4", ledger_path=ledger)


def test_duplicate_run_id_and_malformed_ledger_fail_closed(tmp_path: Path) -> None:
    ledger = tmp_path / "R3_RUN_RESERVATIONS.jsonl"
    manifest = _manifest()
    authorization = _authorization()
    reserve_run(authorization, manifest, run_id="run-2", ledger_path=ledger)
    with pytest.raises(R3AuthorizationError, match="already registered or reserved"):
        reserve_run(authorization, manifest, run_id="run-2", ledger_path=ledger)
    ledger.write_text(ledger.read_text(encoding="utf-8") + "not-json\n", encoding="utf-8")
    with pytest.raises(R3AuthorizationError, match="is not JSON"):
        reserve_run(authorization, manifest, run_id="run-3", ledger_path=ledger)


def test_reservation_ticket_never_claims_input_emitted(tmp_path: Path) -> None:
    ticket = reserve_run(_authorization(), _manifest(), run_id="run-2", ledger_path=tmp_path / "ledger.jsonl")
    assert ticket["input_emitted"] is False
    stored = json.loads((tmp_path / "ledger.jsonl").read_text(encoding="utf-8"))
    assert stored["status"] == "reserved"
    assert stored["input_emitted"] is False


def test_live_edge_requires_exact_fresh_ticket(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    reserve_run(_authorization(), _manifest(), run_id="run-2", ledger_path=ledger)
    ticket = load_reserved_ticket(ledger, run_id="run-2")
    assert ticket["status"] == "reserved"
    with pytest.raises(R3AuthorizationError, match="exactly one matching"):
        load_reserved_ticket(ledger, run_id="run-unknown")
