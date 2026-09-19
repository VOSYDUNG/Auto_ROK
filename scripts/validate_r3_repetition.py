"""Validate registered live GATHER_RESOURCE repetition evidence.

The validator is read-only.  It never captures the desktop, arms input, or
replays a mission.  Each registered occurrence must prove an occurrence-bound
approval, live arming, non-interference, and a fresh visible march-queue delta
of exactly the declared amount.  Historical or duplicate evidence is not
silently counted toward the threshold.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "config" / "r3_registered_runs.json"
DEFAULT_OUTPUT = ROOT / "workspace" / "evidence" / "gather" / "r3-repetition-latest.json"


class R3ValidationError(ValueError):
    """The registered repetition contract is malformed."""


def _load(path: Path) -> Mapping[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise R3ValidationError(f"could not read JSON: {path}: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise R3ValidationError(f"JSON root must be an object: {path}")
    return raw


def _int_fact(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _same_identity(identity: Mapping[str, Any], expected: Mapping[str, Any], run_id: str) -> list[str]:
    reasons: list[str] = []
    for key in ("mission_id", "task_id", "character_id"):
        if identity.get(key) != expected.get(key):
            reasons.append(f"identity.{key} does not match registered contract")
    if identity.get("run_id") != run_id:
        reasons.append("identity.run_id does not match registration")
    return reasons


def validate_record(
    record: Mapping[str, Any],
    registration: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a bounded, explainable result for one registered occurrence."""
    run_id = registration.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise R3ValidationError("each registered run needs a non-empty run_id")
    reasons: list[str] = []
    identity = record.get("identity")
    if not isinstance(identity, Mapping):
        reasons.append("identity is missing")
        identity = {}
    reasons.extend(_same_identity(identity, contract, run_id))

    runtime = record.get("runtime")
    if not isinstance(runtime, Mapping):
        reasons.append("runtime is missing")
        runtime = {}
    engine = record.get("engine")
    if not isinstance(engine, Mapping):
        reasons.append("engine is missing")
        engine = {}
    feedback = engine.get("feedback")
    if not isinstance(feedback, Mapping):
        reasons.append("engine.feedback is missing")
        feedback = {}
    receipt = feedback.get("facts", {}).get("receipt") if isinstance(feedback.get("facts"), Mapping) else None
    if not isinstance(receipt, Mapping):
        reasons.append("VERIFIED receipt is missing")
        receipt = {}
    before_facts = engine.get("before_facts")
    after_facts = engine.get("after_facts")
    before_used = before_facts.get("march_queue_used") if isinstance(before_facts, Mapping) else None
    after_used = after_facts.get("march_queue_used") if isinstance(after_facts, Mapping) else None
    before = _int_fact(before_used)
    after = _int_fact(after_used)
    # A durable pending-verification revision may carry the pre-dispatch
    # counter only as the immutable completion baseline.  That baseline is
    # valid provenance; never infer a value from a generic queue ratio.
    if before is None and isinstance(before_facts, Mapping):
        baseline = before_facts.get("completion_baseline")
        if isinstance(baseline, Mapping):
            before = _int_fact(baseline.get("counter_value"))
    delta = after - before if before is not None and after is not None else None
    required_delta = contract.get("required_queue_delta", 1)
    if type(required_delta) is not int or required_delta < 1:
        raise R3ValidationError("contract.required_queue_delta must be a positive integer")

    if feedback.get("code") != "VERIFIED" or feedback.get("success") is not True:
        reasons.append("feedback is not VERIFIED/success=true")
    if contract.get("require_live_armed", True) and runtime.get("live_armed") is not True:
        reasons.append("runtime.live_armed is not true")
    if contract.get("require_non_interference", True) and receipt.get("non_interference_confirmed") is not True:
        reasons.append("receipt does not prove non-interference")
    if receipt.get("character_id") != contract.get("character_id"):
        reasons.append("receipt.character_id does not match registered character")
    if delta != required_delta:
        reasons.append(f"march_queue_used delta {delta!r} != required {required_delta}")

    approval = runtime.get("policy_approval")
    if contract.get("require_occurrence_bound_approval", True):
        if not isinstance(approval, Mapping) or approval.get("approved") is not True:
            reasons.append("occurrence-bound policy approval is missing")
        else:
            if approval.get("bound_to_occurrence") is not True:
                reasons.append("policy approval is not occurrence-bound")
            for key in ("mission_id", "task_id", "character_id", "run_id"):
                if approval.get(key) != (contract.get(key) if key != "run_id" else run_id):
                    reasons.append(f"policy_approval.{key} does not match occurrence")

    isolation = runtime.get("host_input_isolation")
    if isinstance(isolation, Mapping):
        if isolation.get("ready") is not True:
            reasons.append("host input-isolation evidence is not ready")
        if isolation.get("unexpected_input_events") != 0:
            reasons.append("host input-isolation trace does not prove zero unexpected input events")
    else:
        reasons.append("host input-isolation evidence is missing")

    return {
        "run_id": run_id,
        "evidence_path": registration.get("evidence_path"),
        "status": "pass" if not reasons else "fail",
        "reasons": reasons,
        "identity": dict(identity),
        "feedback_code": feedback.get("code"),
        "live_armed": runtime.get("live_armed"),
        "non_interference_confirmed": receipt.get("non_interference_confirmed"),
        "queue_before": before,
        "queue_after": after,
        "queue_delta": delta,
        "input_emitted": False,
    }


def validate_manifest(manifest: Mapping[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    if manifest.get("schema_version") != 1:
        raise R3ValidationError("manifest must use schema_version=1")
    contract = manifest.get("contract")
    registrations = manifest.get("runs")
    if not isinstance(contract, Mapping) or not isinstance(registrations, list):
        raise R3ValidationError("manifest contract and runs are required")
    required = contract.get("required_runs")
    minimum = contract.get("minimum_successes")
    if type(required) is not int or required < 1 or type(minimum) is not int or not 1 <= minimum <= required:
        raise R3ValidationError("required_runs/minimum_successes are invalid")
    expected_ids: set[str] = set()
    results: list[dict[str, Any]] = []
    for registration in registrations:
        if not isinstance(registration, Mapping):
            raise R3ValidationError("each run registration must be an object")
        run_id = registration.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            raise R3ValidationError("each run registration needs run_id")
        if run_id in expected_ids:
            results.append({"run_id": run_id, "status": "fail", "reasons": ["duplicate registered run_id"], "input_emitted": False})
            continue
        expected_ids.add(run_id)
        raw_path = registration.get("evidence_path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            results.append({"run_id": run_id, "status": "fail", "reasons": ["evidence_path is missing"], "input_emitted": False})
            continue
        evidence = (root / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path).resolve()
        if not evidence.is_relative_to(root.resolve()):
            results.append({"run_id": run_id, "status": "fail", "reasons": ["evidence_path escapes repository root"], "input_emitted": False})
            continue
        try:
            record = _load(evidence)
            result = validate_record(record, {**registration, "evidence_path": str(evidence)}, contract)
        except R3ValidationError as exc:
            result = {"run_id": run_id, "evidence_path": str(evidence), "status": "fail", "reasons": [str(exc)], "input_emitted": False}
        results.append(result)

    passed = sum(1 for result in results if result.get("status") == "pass")
    reasons: list[str] = []
    if len(registrations) < required:
        reasons.append(f"registered runs {len(registrations)} < required {required}")
    if passed < minimum:
        reasons.append(f"successful runs {passed} < minimum {minimum}")
    if len(expected_ids) != len(registrations):
        reasons.append("registered run ids are not unique")
    return {
        "schema_version": 1,
        "status": "pass" if not reasons else "blocked",
        "measurement_class": "r3_live_gather_repetition",
        "contract": dict(contract),
        "counts": {"registered": len(registrations), "required": required, "passed": passed, "minimum_successes": minimum},
        "reasons": reasons,
        "results": results,
        "input_emitted_any": any(result.get("input_emitted") is True for result in results),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args(argv)
    manifest_path = Path(args.manifest).resolve()
    output = Path(args.output).resolve()
    if not output.is_relative_to((ROOT / "workspace" / "evidence").resolve()):
        raise SystemExit("output must stay under workspace/evidence")
    try:
        report = validate_manifest(_load(manifest_path))
    except R3ValidationError as exc:
        report = {"schema_version": 1, "status": "blocked", "measurement_class": "r3_live_gather_repetition", "reasons": [str(exc)], "input_emitted_any": False, "generated_at": datetime.now(timezone.utc).isoformat()}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    printed = dict(report)
    printed["evidence_path"] = str(output)
    print(json.dumps(printed, ensure_ascii=False))
    return 0 if report.get("status") == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())
