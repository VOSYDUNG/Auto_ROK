from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.audit_goal_readiness import (
    _endurance_authorization_reasons,
    _r1a_report_ready,
    audit,
)


def test_r1a_audit_accepts_only_evaluator_ready_enum() -> None:
    assert _r1a_report_ready({"acceptance": {"prd_r1a": "ready"}}) is True
    assert _r1a_report_ready({"acceptance": {"prd_r1a": "pass"}}) is False
    assert _r1a_report_ready({"acceptance": {"prd_r1a": "not_ready"}}) is False
    assert _r1a_report_ready(None) is False


def test_endurance_authorization_fails_closed_when_missing_or_mismatched() -> None:
    assert _endurance_authorization_reasons(None, required_additional_runs=8)
    reasons = _endurance_authorization_reasons(
        {
            "schema_version": 1,
            "scope": "other",
            "approved": True,
            "mission_id": "OTHER",
            "task_id": "one-character",
            "character_id": "char-direct-01",
            "approved_by": "operator",
            "approved_at": "2026-09-19T01:00:00+00:00",
            "max_additional_runs": 1,
        },
        required_additional_runs=8,
    )
    assert any("scope" in item for item in reasons)
    assert any("mission_id" in item for item in reasons)
    assert any("max_additional_runs" in item for item in reasons)


def test_endurance_authorization_accepts_exact_bounded_contract() -> None:
    assert _endurance_authorization_reasons(
        {
            "schema_version": 1,
            "scope": "r3_live_gather_repetition",
            "approved": True,
            "mission_id": "GATHER_RESOURCE",
            "task_id": "one-character",
            "character_id": "char-direct-01",
            "approved_by": "operator",
            "approved_at": "2026-09-19T01:00:00+00:00",
            "max_additional_runs": 8,
        },
        required_additional_runs=8,
    ) == []


def test_full_audit_can_release_g6_only_with_complete_r3_and_authorization() -> None:
    r3 = {
        "status": "pass",
        "counts": {"registered": 10, "required": 10, "passed": 9, "minimum_successes": 9},
    }
    authorization = {
        "schema_version": 1,
        "scope": "r3_live_gather_repetition",
        "approved": True,
        "mission_id": "GATHER_RESOURCE",
        "task_id": "one-character",
        "character_id": "char-direct-01",
        "approved_by": "operator",
        "approved_at": "2026-09-19T01:00:00+00:00",
        "max_additional_runs": 8,
    }
    with patch(
        "scripts.audit_goal_readiness._latest_r3_repetition_report",
        return_value=(Path("r3.json"), r3),
    ), patch(
        "scripts.audit_goal_readiness._endurance_authorization",
        return_value=(Path("authorization.json"), authorization),
    ):
        report = audit()
    gates = {gate["gate"]: gate for gate in report["gates"]}
    assert gates["G6_ENDURANCE"]["status"] == "pass"
    assert gates["G6_ENDURANCE"]["reasons"] == []
