"""Audit the Auto_ROK goal gates from durable evidence only.

This command is observation-only: it reads persisted artifacts and never
activates ROK, starts a model, or emits keyboard/mouse input.  A gate is
reported as passed only when the artifact proves the exact requirement; a
screening or historical replay cannot silently promote a live gate.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.r3_endurance_authorization import authorization_reasons  # noqa: E402

EVIDENCE_ROOT = (ROOT / "workspace" / "evidence").resolve()
ENDURANCE_AUTHORIZATION_PATH = EVIDENCE_ROOT / "gather" / "R3_ENDURANCE_AUTHORIZATION.json"


def _read(path: Path) -> Mapping[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), strict=False)
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _path(relative: str) -> Path:
    return (ROOT / relative).resolve()


def _latest_ready_host_trace() -> tuple[Path | None, Mapping[str, Any] | None]:
    """Select the newest ready direct-host trace instead of a stale filename."""
    root = EVIDENCE_ROOT / "host"
    candidates: list[tuple[str, Path, Mapping[str, Any]]] = []
    if root.is_dir():
        for path in root.glob("*.json"):
            raw = _read(path)
            if not raw or raw.get("environment") != "windows_host_direct":
                continue
            assessment = raw.get("assessment")
            if not isinstance(assessment, Mapping) or assessment.get("ready") is not True:
                continue
            ended = raw.get("ended_at")
            candidates.append((str(ended or ""), path, raw))
    if not candidates:
        return None, None
    _, path, raw = max(candidates, key=lambda item: (item[0], str(item[1])))
    return path, raw


def _latest_preflight() -> tuple[Path | None, Mapping[str, Any] | None]:
    """Use the newest persisted R3 occurrence instead of a stale filename."""
    root = EVIDENCE_ROOT / "gather"
    candidates: list[tuple[str, Path, Mapping[str, Any]]] = []
    if root.is_dir():
        for path in root.glob("R3_PREFLIGHT-*.json"):
            raw = _read(path)
            if not raw:
                continue
            candidates.append((str(raw.get("checked_at") or ""), path, raw))
    if not candidates:
        return None, None
    _, path, raw = max(candidates, key=lambda item: (item[0], str(item[1])))
    return path, raw


def _latest_cpu_benchmark() -> tuple[Path | None, Mapping[str, Any] | None]:
    """Select the newest complete CPU-only benchmark, not a dated filename."""
    root = EVIDENCE_ROOT / "cpu"
    candidates: list[tuple[int, Path, Mapping[str, Any]]] = []
    if root.is_dir():
        for path in root.glob("*.json"):
            raw = _read(path)
            if not raw:
                continue
            if (
                raw.get("status") != "pass"
                or raw.get("processing_device") != "cpu"
                or raw.get("opencl_enabled") is not False
                or raw.get("cuda_devices_visible") != 0
            ):
                continue
            try:
                mtime = path.stat().st_mtime_ns
            except OSError:
                continue
            candidates.append((mtime, path, raw))
    if not candidates:
        return None, None
    _, path, raw = max(candidates, key=lambda item: (item[0], str(item[1])))
    return path, raw


def _latest_ocr_quality_report() -> tuple[Path | None, Mapping[str, Any] | None]:
    """Select the newest critical-field OCR report by its persisted timestamp."""
    root = EVIDENCE_ROOT / "corpus"
    candidates: list[tuple[str, int, Path, Mapping[str, Any]]] = []
    if root.is_dir():
        for path in root.glob("ocr-quality-*.json"):
            raw = _read(path)
            if not raw or raw.get("measurement_class") != "critical_field_ocr_screening":
                continue
            try:
                mtime = path.stat().st_mtime_ns
            except OSError:
                continue
            candidates.append((str(raw.get("generated_at") or ""), mtime, path, raw))
    if not candidates:
        return None, None
    _, _, path, raw = max(candidates, key=lambda item: (item[0], item[1], str(item[2])))
    return path, raw


def _latest_rapidocr_screening() -> tuple[Path | None, Mapping[str, Any] | None]:
    """Select the newest fixed-ROI RapidOCR screen as supplementary evidence."""
    root = EVIDENCE_ROOT / "corpus"
    candidates: list[tuple[int, Path, Mapping[str, Any]]] = []
    if root.is_dir():
        for path in root.glob("rapidocr-corpus-experiment-*.json"):
            raw = _read(path)
            if not raw or raw.get("measurement_class") != "rapidocr_cpu_fixed_roi_recognition_corpus_screening":
                continue
            try:
                mtime = path.stat().st_mtime_ns
            except OSError:
                continue
            candidates.append((mtime, path, raw))
    if not candidates:
        return None, None
    _, path, raw = max(candidates, key=lambda item: (item[0], str(item[1])))
    return path, raw


def _latest_rapidocr_observation_screening() -> tuple[Path | None, Mapping[str, Any] | None]:
    """Select the newest observation-bridge replay using the derived OCR overlay."""
    root = EVIDENCE_ROOT / "corpus"
    candidates: list[tuple[int, Path, Mapping[str, Any]]] = []
    if root.is_dir():
        for path in root.glob("cpu-observation-corpus-rapidocr-overlay-*.json"):
            raw = _read(path)
            if not raw or raw.get("measurement_class") != "real_rok_capture_corpus_screening":
                continue
            try:
                mtime = path.stat().st_mtime_ns
            except OSError:
                continue
            candidates.append((mtime, path, raw))
    if not candidates:
        return None, None
    _, path, raw = max(candidates, key=lambda item: (item[0], str(item[1])))
    return path, raw


def _latest_r3_repetition_report() -> tuple[Path | None, Mapping[str, Any] | None]:
    """Select the newest read-only R3 repetition validation report."""
    root = EVIDENCE_ROOT / "gather"
    candidates: list[tuple[str, int, Path, Mapping[str, Any]]] = []
    if root.is_dir():
        for path in root.glob("r3-repetition-*.json"):
            raw = _read(path)
            if not raw or raw.get("measurement_class") != "r3_live_gather_repetition":
                continue
            try:
                mtime = path.stat().st_mtime_ns
            except OSError:
                continue
            candidates.append((str(raw.get("generated_at") or ""), mtime, path, raw))
    if not candidates:
        return None, None
    _, _, path, raw = max(candidates, key=lambda item: (item[0], item[1], str(item[2])))
    return path, raw


def _endurance_authorization() -> tuple[Path, Mapping[str, Any] | None]:
    """Load the explicit operator authorization for bounded R3 live repeats."""
    return ENDURANCE_AUTHORIZATION_PATH, _read(ENDURANCE_AUTHORIZATION_PATH)


def _endurance_authorization_reasons(
    authorization: Mapping[str, Any] | None,
    *,
    required_additional_runs: int,
) -> list[str]:
    """Validate authorization without inferring it from any other artifact."""
    return authorization_reasons(
        authorization,
        required_additional_runs=required_additional_runs,
    )


def _gate(
    gate_id: str,
    status: str,
    reasons: list[str],
    evidence: list[str],
    **facts: Any,
) -> dict[str, Any]:
    return {
        "gate": gate_id,
        "status": status,
        "reasons": reasons,
        "evidence": evidence,
        **facts,
    }


def _r1a_report_ready(report: Mapping[str, Any] | None) -> bool:
    """Accept only the positive enum emitted by ``evaluate_ocr_quality``."""
    if not isinstance(report, Mapping):
        return False
    acceptance = report.get("acceptance")
    return isinstance(acceptance, Mapping) and acceptance.get("prd_r1a") == "ready"


def audit() -> dict[str, Any]:
    host_trace_path, host_trace = _latest_ready_host_trace()
    host_assessment_path = (
        host_trace_path.with_name(host_trace_path.stem + "-assessment.json")
        if host_trace_path is not None
        else None
    )
    host_assessment = _read(host_assessment_path) if host_assessment_path else None
    host_reasons: list[str] = []
    if host_trace is None:
        host_reasons.append("no ready direct-host trace is available")
    else:
        assessment = host_trace.get("assessment")
        if not isinstance(assessment, Mapping) or assessment.get("ready") is not True:
            if isinstance(assessment, Mapping):
                host_reasons.extend(str(item) for item in assessment.get("reasons", []))
            if not host_reasons:
                host_reasons.append("direct-host trace assessment is not ready")
        if host_trace.get("input_emitted") is not False:
            host_reasons.append("direct-host trace does not prove zero input")
    host_gate = _gate(
        "G1_HOST_INPUT_ISOLATION",
        "pass" if not host_reasons else "blocked",
        host_reasons,
        [str(item) for item in (host_trace_path, host_assessment_path) if item is not None],
        input_emitted=False if host_trace else None,
    )

    cpu_path, cpu = _latest_cpu_benchmark()
    ocr_path, ocr = _latest_ocr_quality_report()
    rapidocr_path, rapidocr = _latest_rapidocr_screening()
    rapidocr_observation_path, rapidocr_observation = _latest_rapidocr_observation_screening()
    corpus_reasons: list[str] = []
    if cpu is None or cpu_path is None:
        corpus_reasons.append("CPU benchmark is missing/invalid")
    else:
        if cpu.get("processing_device") != "cpu":
            corpus_reasons.append("CPU benchmark does not prove processing_device=cpu")
        if cpu.get("opencl_enabled") is not False or cpu.get("cuda_devices_visible") != 0:
            corpus_reasons.append("CPU benchmark does not prove GPU/OpenCL are disabled")
    if ocr is None or ocr_path is None:
        corpus_reasons.append("OCR quality report is missing/invalid")
    else:
        # ``evaluate_ocr_quality.py`` is the authority for the R1a report and
        # emits ``ready``/``not_ready``.  Accept only its positive value here;
        # do not silently treat screening or a missing field as a pass.
        if not _r1a_report_ready(ocr):
            corpus_reasons.append("OCR/state corpus has not passed the PRD R1a gate")
    corpus_gate = _gate(
        "G2_CPU_OCR_STATE",
        "pass" if not corpus_reasons else "blocked",
        corpus_reasons,
        [
            str(item)
            for item in (cpu_path, ocr_path, rapidocr_path, rapidocr_observation_path)
            if item is not None
        ],
        processing_device=cpu.get("processing_device") if cpu else None,
        ocr_acceptance=ocr.get("acceptance", {}).get("prd_r1a") if ocr else None,
        rapidocr_screening={
            "status": rapidocr.get("status") if rapidocr else None,
            "sample_count": rapidocr.get("sample_count") if rapidocr else None,
            "exact_count": rapidocr.get("exact_count") if rapidocr else None,
            "exact_rate": rapidocr.get("exact_rate") if rapidocr else None,
            "capture_binding": (
                all(
                    item.get("capture_binding_verified") is True
                    for item in rapidocr.get("results", [])
                    if isinstance(item, Mapping) and "exact" in item
                )
                if rapidocr
                else None
            ),
        },
        rapidocr_observation={
            "status": rapidocr_observation.get("status") if rapidocr_observation else None,
            "projection_ok": rapidocr_observation.get("counts", {}).get("projection_ok")
            if rapidocr_observation
            else None,
            "state_exact_matches": rapidocr_observation.get("counts", {}).get("state_exact_matches")
            if rapidocr_observation
            else None,
            "input_emitted_any": rapidocr_observation.get("input_emitted_any")
            if rapidocr_observation
            else None,
        },
    )

    llm_path = _path(
        "workspace/evidence/local_llm/needs-decision-gpt-oss-holdout-20260918.json"
    )
    llm = _read(llm_path)
    llm_reasons: list[str] = []
    if llm is None:
        llm_reasons.append("local-LLM holdout result is missing/invalid")
    else:
        if llm.get("measurement_class") != "holdout_multi_frame_real_replay":
            llm_reasons.append("result is not classified as a frame-disjoint holdout")
        if llm.get("sample_count") != 12 or llm.get("pass_count") != 12:
            llm_reasons.append("holdout is not complete at 12/12")
        if llm.get("input_emitted_any") is not False:
            llm_reasons.append("holdout does not prove zero input")
        if llm.get("usage_telemetry_complete") is not True:
            llm_reasons.append("holdout usage telemetry is incomplete")
    llm_gate = _gate(
        "G3_LOCAL_LLM_HOLDOUT",
        "pass" if not llm_reasons else "blocked",
        llm_reasons,
        [str(llm_path)],
        sample_count=llm.get("sample_count") if llm else None,
        accuracy=llm.get("accuracy") if llm else None,
        prd_promotion=llm.get("acceptance", {}).get("prd_r1b") if llm else None,
    )

    b003_path, current_preflight = _latest_preflight()
    b003 = current_preflight.get("b003_approval") if current_preflight else None
    b003_reasons: list[str] = []
    if b003 is None:
        b003_reasons.append("current-occurrence B003 review is missing/invalid")
    elif b003.get("bound_to_occurrence") is not True:
        b003_reasons.append("no occurrence-bound current B003 approval")
    b003_gate = _gate(
        "G4_B003_OCCURRENCE_APPROVAL",
        "pass" if not b003_reasons else "blocked",
        b003_reasons,
        [str(b003_path)] if b003_path is not None else [],
        bound_to_occurrence=(b003 or {}).get("bound_to_occurrence") if b003 else None,
    )

    # Do not infer a live success from historical replay evidence.  Search only
    # receipts bound to the current preflight occurrence and require the typed
    # queue delta, live arming and non-interference receipt facts together.
    preflight_path, preflight = _latest_preflight()
    occurrence = preflight.get("occurrence") if preflight else None
    live_matches: list[str] = []
    gather_root = EVIDENCE_ROOT / "gather"
    if isinstance(occurrence, Mapping) and gather_root.is_dir():
        for candidate_path in gather_root.rglob("*.json"):
            candidate = _read(candidate_path)
            identity = candidate.get("identity") if candidate else None
            if not isinstance(identity, Mapping):
                continue
            if any(identity.get(key) != occurrence.get(key) for key in ("mission_id", "task_id", "run_id", "character_id")):
                continue
            engine = candidate.get("engine")
            runtime = candidate.get("runtime")
            feedback = engine.get("feedback") if isinstance(engine, Mapping) else None
            before_facts = engine.get("before_facts") if isinstance(engine, Mapping) else None
            after_facts = engine.get("after_facts") if isinstance(engine, Mapping) else None
            receipt = feedback.get("facts", {}).get("receipt") if isinstance(feedback, Mapping) else None
            before_used = before_facts.get("march_queue_used") if isinstance(before_facts, Mapping) else None
            after_used = after_facts.get("march_queue_used") if isinstance(after_facts, Mapping) else None
            if type(before_used) is not int and isinstance(before_facts, Mapping):
                baseline = before_facts.get("completion_baseline")
                if isinstance(baseline, Mapping):
                    before_used = baseline.get("counter_value")
            if (
                isinstance(feedback, Mapping)
                and feedback.get("code") == "VERIFIED"
                and feedback.get("success") is True
                and isinstance(runtime, Mapping)
                and runtime.get("live_armed") is True
                and isinstance(receipt, Mapping)
                and receipt.get("non_interference_confirmed") is True
                and type(before_used) is int
                and type(after_used) is int
                and after_used == before_used + 1
            ):
                live_matches.append(str(candidate_path))
    live_reasons = [] if live_matches else [
        "no fresh current-occurrence VERIFIED GATHER receipt proving Queue used +1"
    ]
    live_gate = _gate(
        "G5_LIVE_GATHER_POSTCONDITION",
        "pass" if live_matches else "blocked",
        live_reasons,
        (([str(preflight_path)] if preflight_path is not None else []) + live_matches),
        input_emitted=False,
        matching_receipts=live_matches,
    )
    r3_path, r3 = _latest_r3_repetition_report()
    r3_ready = isinstance(r3, Mapping) and r3.get("status") == "pass"
    endurance_reasons: list[str] = []
    if not r3_ready:
        if r3 is None:
            endurance_reasons.append("R3 repetition validation report is missing")
        else:
            endurance_reasons.extend(str(reason) for reason in r3.get("reasons", []))
    r3_counts = r3.get("counts") if isinstance(r3, Mapping) else None
    registered = r3_counts.get("registered") if isinstance(r3_counts, Mapping) else 0
    required = r3_counts.get("required") if isinstance(r3_counts, Mapping) else 10
    required_additional_runs = max(0, int(required) - int(registered)) if type(required) is int and type(registered) is int else 10
    authorization_path, authorization = _endurance_authorization()
    authorization_reasons = _endurance_authorization_reasons(
        authorization,
        required_additional_runs=required_additional_runs,
    )
    endurance_reasons.extend(authorization_reasons)
    endurance_evidence = [str(r3_path)] if r3_path is not None else []
    if authorization_path.exists():
        endurance_evidence.append(str(authorization_path))
    endurance_gate = _gate(
        "G6_ENDURANCE",
        "pass" if r3_ready and not endurance_reasons else "blocked",
        endurance_reasons,
        endurance_evidence,
        prerequisites_complete=all(
            gate["status"] == "pass"
            for gate in (host_gate, corpus_gate, llm_gate, b003_gate, live_gate)
        ),
        r3_counts=r3_counts,
        endurance_authorization={
            "path": str(authorization_path),
            "present": authorization is not None,
            "approved": authorization.get("approved") if authorization else None,
            "max_additional_runs": authorization.get("max_additional_runs") if authorization else None,
        },
    )

    gates = [host_gate, corpus_gate, llm_gate, b003_gate, live_gate, endurance_gate]
    return {
        "schema_version": 1,
        "status": "pass" if all(gate["status"] == "pass" for gate in gates) else "blocked",
        "measurement_class": "goal_readiness_audit",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "input_emitted": False,
        "gates": gates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(EVIDENCE_ROOT / "audit" / "goal-readiness-latest.json"),
    )
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if not output.is_relative_to(EVIDENCE_ROOT) or output == EVIDENCE_ROOT:
        raise SystemExit("output must stay under workspace/evidence")
    report = audit()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    printed = dict(report)
    printed["evidence_path"] = str(output)
    print(json.dumps(printed, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())
