"""Compare deterministic and bounded local-LLM choices on a fixed replay.

This runner consumes an already completed, frame-disjoint local-LLM holdout.
It does not contact the model, capture the desktop, or construct an input
actuator.  H0 represents the deterministic fast path: it chooses only when
the replay exposes zero or one eligible candidate and otherwise abstains.
H1 reuses the recorded bounded semantic choice, preserving the same cases,
frames, candidate order and acceptance oracle.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from math import ceil
from pathlib import Path
import time
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOLDOUT = ROOT / "workspace" / "evidence" / "local_llm" / "needs-decision-gpt-oss-holdout-20260918.json"
DEFAULT_MATRIX = ROOT / "config" / "harness_benchmark_matrix.json"
DEFAULT_OUTPUT = ROOT / "workspace" / "evidence" / "local_llm" / "harness-tax-benchmark-latest.json"


class HarnessTaxError(ValueError):
    """The fixed replay or comparison contract is invalid."""


def _read(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), strict=False)
    except (OSError, json.JSONDecodeError) as exc:
        raise HarnessTaxError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise HarnessTaxError(f"{label} must be a JSON object")
    return value


def _p95(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(float(item) for item in values)
    return ordered[min(len(ordered) - 1, max(0, ceil(len(ordered) * 0.95) - 1))]


def _choice_key(choice: Any) -> tuple[str | None, str | None] | None:
    if not isinstance(choice, Mapping):
        return None
    action_id = choice.get("action_id")
    target_id = choice.get("target_id")
    if action_id is not None and not isinstance(action_id, str):
        return None
    if target_id is not None and not isinstance(target_id, str):
        return None
    return action_id, target_id


def _valid_candidate_keys(row: Mapping[str, Any]) -> set[tuple[str | None, str | None]]:
    snapshot = row.get("snapshot")
    raw = snapshot.get("candidates") if isinstance(snapshot, Mapping) else None
    keys: set[tuple[str | None, str | None]] = set()
    if isinstance(raw, list):
        for candidate in raw:
            key = _choice_key(candidate)
            if key is not None:
                keys.add(key)
        return keys
    # The persisted holdout aggregate intentionally stores the compact
    # snapshot (allowed action ids + grounded target ids), not a second copy
    # of the provider payload.  Reconstruct only the semantic candidate keys;
    # never invent coordinates or arbitrary actions.
    if isinstance(snapshot, Mapping):
        actions = snapshot.get("allowed_action_ids")
        targets = snapshot.get("target_ids")
        if isinstance(actions, list) and isinstance(targets, list):
            target_ids = {item for item in targets if isinstance(item, str)}
            if "SELECT_RESOURCE_TYPE" in actions:
                keys.update(
                    ("SELECT_RESOURCE_TYPE", target)
                    for target in target_ids
                    if target.startswith("SEARCH_CATEGORY_")
                )
            if "SEARCH_RESOURCE_NODE" in actions and "SEARCH_EXECUTE" in target_ids:
                keys.add(("SEARCH_RESOURCE_NODE", "SEARCH_EXECUTE"))
    return keys


def _h0_choice(row: Mapping[str, Any]) -> tuple[tuple[str | None, str | None] | None, float]:
    started = time.perf_counter()
    candidates = _valid_candidate_keys(row)
    if len(candidates) != 1:
        choice = None
    else:
        choice = next(iter(candidates))
    return choice, (time.perf_counter() - started) * 1000.0


def _variant_summary(
    variant_id: str,
    rows: Sequence[Mapping[str, Any]],
    choices: Sequence[tuple[tuple[str | None, str | None] | None, float]],
    *,
    model_usage: bool = False,
) -> dict[str, Any]:
    if len(rows) != len(choices):
        raise HarnessTaxError("variant choices must align with holdout rows")
    correct = 0
    abstained = 0
    invalid = 0
    latencies: list[float] = []
    prompt_tokens: list[float] = []
    completion_tokens: list[float] = []
    total_tokens: list[float] = []
    request_bytes: list[float] = []
    request_digests = 0
    for row, (choice, elapsed_ms) in zip(rows, choices):
        latencies.append(float(elapsed_ms))
        expected = ("SELECT_RESOURCE_TYPE", row.get("expected_target_id"))
        if choice is None:
            abstained += 1
        elif choice not in _valid_candidate_keys(row):
            invalid += 1
        elif choice == expected:
            correct += 1
        else:
            invalid += 1
        if model_usage:
            model = row.get("model")
            if isinstance(model, Mapping):
                usage = model.get("usage")
                if isinstance(usage, Mapping):
                    for key, target in (("prompt_tokens", prompt_tokens), ("completion_tokens", completion_tokens), ("total_tokens", total_tokens)):
                        value = usage.get(key)
                        if type(value) in (int, float):
                            target.append(float(value))
                value = model.get("request_bytes")
                if type(value) in (int, float):
                    request_bytes.append(float(value))
                if isinstance(model.get("request_sha256"), str) and model.get("request_sha256"):
                    request_digests += 1
    total = len(rows)
    safe_abstentions = sum(
        1
        for row, (choice, _elapsed) in zip(rows, choices)
        if choice is None and len(_valid_candidate_keys(row)) != 1
    )
    return {
        "id": variant_id,
        "case_count": total,
        "bounded_choice_accuracy": correct / total if total else None,
        "correct_bounded_choices": correct,
        "safe_abstention_rate": safe_abstentions / total if total else None,
        "safe_abstentions": safe_abstentions,
        "invalid_choice_rate": invalid / total if total else None,
        "invalid_or_invented_choices": invalid,
        "verified_completion_rate": None,
        "input_emitted_any": False,
        "model_latency_ms_p50": (sorted(latencies)[len(latencies) // 2] if latencies else None),
        "model_latency_ms_p95": _p95(latencies),
        "harness_latency_ms_p50": (sorted(latencies)[len(latencies) // 2] if latencies else None),
        "harness_latency_ms_p95": _p95(latencies),
        "request_prompt_tokens": sum(prompt_tokens) if prompt_tokens else None,
        "request_completion_tokens": sum(completion_tokens) if completion_tokens else None,
        "request_total_tokens": sum(total_tokens) if total_tokens else None,
        "request_bytes": sum(request_bytes) if request_bytes else None,
        "request_fingerprint_count": request_digests if model_usage else None,
        "cpu_time_ms": None,
        "peak_rss_mb": None,
        "replay_determinism": True if variant_id == "h0_deterministic_fast_path" else None,
        "telemetry_unavailable": ["cpu_time_ms", "peak_rss_mb", "verified_completion_rate"]
        + (["request_bytes", "request_fingerprint"] if model_usage and not request_bytes else []),
    }


def build_comparison(holdout: Mapping[str, Any], matrix: Mapping[str, Any]) -> dict[str, Any]:
    if holdout.get("measurement_class") != "holdout_multi_frame_real_replay":
        raise HarnessTaxError("holdout must be the frame-disjoint real replay measurement")
    rows = holdout.get("results")
    if not isinstance(rows, list) or not rows:
        raise HarnessTaxError("holdout results must be a non-empty list")
    constraints = matrix.get("constraints")
    if not isinstance(constraints, Mapping) or constraints.get("processing_device") != "cpu":
        raise HarnessTaxError("benchmark matrix must be CPU-only")
    case_source = matrix.get("case_source")
    if not isinstance(case_source, Mapping) or case_source.get("live_input_allowed") is not False:
        raise HarnessTaxError("benchmark matrix must prohibit live input")
    if constraints.get("model_can_emit_input") is not False:
        raise HarnessTaxError("benchmark matrix must prohibit live/model input")
    h0_choices = [_h0_choice(row) for row in rows if isinstance(row, Mapping)]
    if len(h0_choices) != len(rows):
        raise HarnessTaxError("every holdout result must be an object")
    h1_choices: list[tuple[tuple[str | None, str | None] | None, float]] = []
    for row in rows:
        model = row.get("model")
        choice = _choice_key(model.get("choice")) if isinstance(model, Mapping) else None
        elapsed = model.get("elapsed_ms") if isinstance(model, Mapping) else None
        h1_choices.append((choice, float(elapsed) if type(elapsed) in (int, float) else 0.0))
    variants = [
        _variant_summary("h0_deterministic_fast_path", rows, h0_choices),
        _variant_summary("h1_bounded_semantic_choice", rows, h1_choices, model_usage=True),
    ]
    return {
        "schema_version": 1,
        "status": "screening_only",
        "measurement_class": "harness_tax_comparison",
        "benchmark_id": matrix.get("id"),
        "constraints": dict(constraints),
        "source": {
            "holdout_measurement_class": holdout.get("measurement_class"),
            "batch_id": holdout.get("batch_id"),
            "case_count": len(rows),
            "distinct_frame_count": holdout.get("distinct_frame_count"),
        },
        "variants": variants,
        "comparison": {
            "h1_accuracy_minus_h0_accuracy": variants[1]["bounded_choice_accuracy"] - variants[0]["bounded_choice_accuracy"],
            "h0_abstention_is_safe_for_ambiguous_cases": variants[0]["safe_abstention_rate"] == 1.0,
            "offline_input_emitted_any": False,
            "promotion": "pending_independent_review",
        },
        "input_emitted_any": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdout", default=str(DEFAULT_HOLDOUT))
    parser.add_argument("--matrix", default=str(DEFAULT_MATRIX))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args(argv)
    try:
        report = build_comparison(_read(Path(args.holdout).resolve(), "holdout"), _read(Path(args.matrix).resolve(), "benchmark matrix"))
    except HarnessTaxError as exc:
        report = {"schema_version": 1, "status": "blocked", "measurement_class": "harness_tax_comparison", "reasons": [str(exc)], "input_emitted_any": False, "generated_at": datetime.now(timezone.utc).isoformat()}
    output = Path(args.output).resolve()
    if not output.is_relative_to((ROOT / "workspace" / "evidence").resolve()):
        raise SystemExit("output must stay under workspace/evidence")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    printed = dict(report)
    printed["evidence_path"] = str(output)
    print(json.dumps(printed, ensure_ascii=False))
    return 0 if report.get("status") == "screening_only" else 3


if __name__ == "__main__":
    raise SystemExit(main())
