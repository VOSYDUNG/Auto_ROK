from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import scripts.audit_goal_readiness as goal_audit
from scripts.audit_goal_readiness import (
    _endurance_authorization_reasons,
    _r1a_report_ready,
    audit,
)


GATE_IDS = (
    "G1_HOST_INPUT_ISOLATION",
    "G2_CPU_OCR_STATE",
    "G3_LOCAL_LLM_HOLDOUT",
    "G4_B003_OCCURRENCE_APPROVAL",
    "G5_LIVE_GATHER_POSTCONDITION",
)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _run_synthetic_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    blocked_gate: str | None = None,
    r3_ready: bool = True,
    authorization: dict[str, Any] | None = None,
    include_assessment_sidecar: bool = False,
) -> dict[str, Any]:
    evidence_root = tmp_path / "evidence"
    monkeypatch.setattr(goal_audit, "EVIDENCE_ROOT", evidence_root)

    host_path = evidence_root / "host" / "direct-host.json"
    host = {
        "assessment": {
            "ready": blocked_gate != "G1_HOST_INPUT_ISOLATION",
            "reasons": ["synthetic G1 failure"] if blocked_gate == "G1_HOST_INPUT_ISOLATION" else [],
        },
        "input_emitted": blocked_gate == "G1_HOST_INPUT_ISOLATION",
    }
    _write_json(host_path, host)
    if include_assessment_sidecar:
        _write_json(
            host_path.with_name(host_path.stem + "-assessment.json"),
            {"ready": True},
        )
    monkeypatch.setattr(goal_audit, "_latest_ready_host_trace", lambda: (host_path, host))

    cpu_path = evidence_root / "cpu" / "benchmark.json"
    cpu = {
        "status": "pass",
        "processing_device": "gpu" if blocked_gate == "G2_CPU_OCR_STATE" else "cpu",
        "opencl_enabled": False,
        "cuda_devices_visible": 0,
    }
    _write_json(cpu_path, cpu)
    monkeypatch.setattr(goal_audit, "_latest_cpu_benchmark", lambda: (cpu_path, cpu))

    ocr_path = evidence_root / "corpus" / "ocr-quality.json"
    ocr = {"acceptance": {"prd_r1a": "ready"}}
    _write_json(ocr_path, ocr)
    monkeypatch.setattr(goal_audit, "_latest_ocr_quality_report", lambda: (ocr_path, ocr))
    monkeypatch.setattr(goal_audit, "_latest_rapidocr_screening", lambda: (None, None))
    monkeypatch.setattr(
        goal_audit,
        "_latest_rapidocr_observation_screening",
        lambda: (None, None),
    )

    llm_path = evidence_root / "local_llm" / "holdout.json"
    llm = {
        "measurement_class": "holdout_multi_frame_real_replay",
        "sample_count": 12,
        "pass_count": 11 if blocked_gate == "G3_LOCAL_LLM_HOLDOUT" else 12,
        "input_emitted_any": False,
        "usage_telemetry_complete": True,
        "accuracy": 1.0,
        "acceptance": {"prd_r1b": "measured_pending_reviewer"},
    }
    _write_json(llm_path, llm)
    monkeypatch.setattr(goal_audit, "_path", lambda _relative: llm_path)

    occurrence = {
        "mission_id": "GATHER_RESOURCE",
        "task_id": "one-character",
        "run_id": "synthetic-run",
        "character_id": "char-direct-01",
    }
    preflight_path = evidence_root / "gather" / "R3_PREFLIGHT-synthetic.json"
    preflight = {
        "b003_approval": {
            "bound_to_occurrence": blocked_gate != "G4_B003_OCCURRENCE_APPROVAL"
        },
        "occurrence": occurrence,
    }
    _write_json(preflight_path, preflight)
    monkeypatch.setattr(goal_audit, "_latest_preflight", lambda: (preflight_path, preflight))

    if blocked_gate != "G5_LIVE_GATHER_POSTCONDITION":
        _write_json(
            evidence_root / "gather" / "receipt.json",
            {
                "identity": occurrence,
                "runtime": {"live_armed": True},
                "engine": {
                    "feedback": {
                        "code": "VERIFIED",
                        "success": True,
                        "facts": {"receipt": {"non_interference_confirmed": True}},
                    },
                    "before_facts": {"march_queue_used": 1},
                    "after_facts": {"march_queue_used": 2},
                },
            },
        )

    r3_path = evidence_root / "gather" / "r3-repetition.json"
    r3 = {
        "status": "pass" if r3_ready else "blocked",
        "reasons": [] if r3_ready else ["synthetic R3 incomplete"],
        "counts": {
            "registered": 10 if r3_ready else 2,
            "required": 10,
            "passed": 9 if r3_ready else 2,
            "minimum_successes": 9,
        },
    }
    _write_json(r3_path, r3)
    monkeypatch.setattr(goal_audit, "_latest_r3_repetition_report", lambda: (r3_path, r3))

    if authorization is None:
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
    authorization_path = evidence_root / "gather" / "authorization.json"
    if authorization:
        _write_json(authorization_path, authorization)
    monkeypatch.setattr(
        goal_audit,
        "_endurance_authorization",
        lambda: (authorization_path, authorization or None),
    )
    return audit()


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


@pytest.mark.parametrize("blocked_gate", GATE_IDS)
def test_each_blocked_prerequisite_blocks_g6_with_explicit_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    blocked_gate: str,
) -> None:
    report = _run_synthetic_audit(
        tmp_path,
        monkeypatch,
        blocked_gate=blocked_gate,
    )
    gates = {gate["gate"]: gate for gate in report["gates"]}
    assert gates[blocked_gate]["status"] == "blocked"
    assert gates["G6_ENDURANCE"]["status"] == "blocked"
    assert gates["G6_ENDURANCE"]["prerequisites_complete"] is False
    assert f"prerequisite gate {blocked_gate} is blocked" in gates["G6_ENDURANCE"]["reasons"]
    if blocked_gate == "G1_HOST_INPUT_ISOLATION":
        assert gates[blocked_gate]["input_emitted"] is True


def test_full_audit_can_release_g6_only_with_all_synthetic_inputs_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _run_synthetic_audit(tmp_path, monkeypatch)
    gates = {gate["gate"]: gate for gate in report["gates"]}
    assert gates["G6_ENDURANCE"]["status"] == "pass"
    assert gates["G6_ENDURANCE"]["reasons"] == []
    assert gates["G6_ENDURANCE"]["prerequisites_complete"] is True


@pytest.mark.parametrize(
    ("r3_ready", "authorization", "reason_fragment"),
    [
        (False, None, "synthetic R3 incomplete"),
        (True, {}, "explicit endurance authorization is missing"),
        (
            True,
            {
                "schema_version": 1,
                "scope": "other",
                "approved": True,
                "mission_id": "GATHER_RESOURCE",
                "task_id": "one-character",
                "character_id": "char-direct-01",
                "approved_by": "operator",
                "approved_at": "2026-09-19T01:00:00+00:00",
                "max_additional_runs": 8,
            },
            "scope",
        ),
    ],
)
def test_g6_still_blocks_for_r3_or_authorization_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    r3_ready: bool,
    authorization: dict[str, Any] | None,
    reason_fragment: str,
) -> None:
    report = _run_synthetic_audit(
        tmp_path,
        monkeypatch,
        r3_ready=r3_ready,
        authorization=authorization,
    )
    gate = next(gate for gate in report["gates"] if gate["gate"] == "G6_ENDURANCE")
    assert gate["status"] == "blocked"
    assert any(reason_fragment in reason for reason in gate["reasons"])


def test_g1_evidence_uses_inline_assessment_without_missing_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _run_synthetic_audit(tmp_path, monkeypatch)
    gate = next(gate for gate in report["gates"] if gate["gate"] == "G1_HOST_INPUT_ISOLATION")
    assert gate["status"] == "pass"
    assert gate["input_emitted"] is False
    assert gate["evidence"] == [str(tmp_path / "evidence" / "host" / "direct-host.json")]


def test_g1_evidence_includes_existing_assessment_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _run_synthetic_audit(
        tmp_path,
        monkeypatch,
        include_assessment_sidecar=True,
    )
    gate = next(gate for gate in report["gates"] if gate["gate"] == "G1_HOST_INPUT_ISOLATION")
    assert gate["status"] == "pass"
    assert gate["evidence"] == [
        str(tmp_path / "evidence" / "host" / "direct-host.json"),
        str(tmp_path / "evidence" / "host" / "direct-host-assessment.json"),
    ]
