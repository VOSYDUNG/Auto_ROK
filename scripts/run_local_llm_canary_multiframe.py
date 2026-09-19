"""Aggregate bounded local-LLM choices over distinct real ROK replay frames.

The default mode reuses already persisted canary evidence so a report can be
recomputed without sending another request.  Without ``--reuse-evidence`` the
same case manifest is executed through ``run_local_llm_canary.py``.  Both modes
are observation-only and never construct an input actuator.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import subprocess
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).with_name("run_local_llm_canary.py")
_RESOURCE_TYPES = ("FOOD", "WOOD", "STONE", "GOLD")


def _read_json(path: Path, label: str) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), strict=False)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {path}: {exc}") from exc
    return value


def _repo_run_file(value: str, label: str) -> Path:
    path = Path(value).resolve()
    runs = (ROOT / "workspace" / "runs").resolve()
    if not path.is_file() or not path.is_relative_to(runs):
        raise ValueError(f"{label} must be an existing file under workspace/runs")
    return path


def _load_cases(path: Path) -> list[dict[str, Any]]:
    raw = _read_json(path, "case manifest")
    if not isinstance(raw, Mapping) or not isinstance(raw.get("cases"), list) or not raw["cases"]:
        raise ValueError("case manifest must contain a non-empty cases list")
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw["cases"]:
        if not isinstance(item, Mapping):
            raise ValueError("case entries must be objects")
        case_id = item.get("id")
        resource_type = item.get("resource_type")
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ValueError(f"case ids must be non-empty and unique: {case_id!r}")
        if resource_type not in _RESOURCE_TYPES:
            raise ValueError(f"invalid resource_type for case {case_id!r}")
        seen.add(case_id)
        cases.append({
            "id": case_id,
            "capture_meta": str(_repo_run_file(str(item.get("capture_meta", "")), "capture metadata")),
            "ocr": str(_repo_run_file(str(item.get("ocr", "")), "OCR evidence")),
            "image": str(_repo_run_file(str(item.get("image", "")), "frame image")),
            "resource_type": resource_type,
            "expected_target_id": str(item.get("expected_target_id", f"SEARCH_CATEGORY_{resource_type}")),
        })
    return cases


def _manifest_split(path: Path) -> str | None:
    """Return the declared split so a real holdout cannot be mislabeled as screening."""
    raw = _read_json(path, "case manifest")
    split = raw.get("split") if isinstance(raw, Mapping) else None
    return split if isinstance(split, str) else None


def _result_from_stdout(stdout: str) -> Mapping[str, Any]:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping) and "status" in value:
            return value
    raise ValueError("canary produced no JSON result")


def _write_result(root: Path, batch_id: str, payload: Mapping[str, Any]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{batch_id}.json"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--cases", default=str(ROOT / "config" / "local_llm_multiframe_cases.json"))
    parser.add_argument("--local-llm-config", required=True)
    parser.add_argument("--evidence-root", default=str(ROOT / "workspace" / "evidence" / "local_llm"))
    parser.add_argument(
        "--reuse-evidence",
        action="store_true",
        help="load per-case evidence already written by run_local_llm_canary.py",
    )
    parser.add_argument(
        "--hide-resource-intent",
        action="store_true",
        help="omit the requested resource fact and measure bounded abstention",
    )
    parser.add_argument(
        "--reverse-candidates",
        action="store_true",
        help="reverse bounded candidates to probe position bias",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence_root = Path(args.evidence_root).resolve()
    if not evidence_root.is_relative_to((ROOT / "workspace" / "evidence").resolve()):
        raise SystemExit("evidence-root must stay under workspace/evidence")
    case_manifest_path = Path(args.cases).resolve()
    cases = _load_cases(case_manifest_path)
    manifest_split = _manifest_split(case_manifest_path)
    is_holdout = manifest_split == "holdout"
    _repo_run_file(args.local_llm_config, "local LLM config")
    started_at = datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        run_id = f"{args.batch_id}-{case['id']}"
        if args.reuse_evidence:
            path = evidence_root / f"{run_id}.json"
            item = dict(_read_json(path, f"case evidence {case['id']}"))
            item.setdefault("evidence_path", str(path))
        else:
            command = [
                sys.executable, str(SCRIPT), "--run-id", run_id,
                "--capture-meta", case["capture_meta"], "--ocr", case["ocr"],
                "--image", case["image"], "--resource-type", case["resource_type"],
                "--local-llm-config", str(Path(args.local_llm_config).resolve()),
            ]
            if args.hide_resource_intent:
                command.append("--hide-resource-intent")
            if args.reverse_candidates:
                command.append("--reverse-candidates")
            completed = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True, check=False)
            try:
                item = dict(_result_from_stdout(completed.stdout))
            except ValueError as exc:
                item = {"status": "runner_error", "error": {"type": type(exc).__name__, "message": str(exc)}}
            item["process_exit_code"] = completed.returncode
        item["batch_index"] = index
        item["case_id"] = case["id"]
        item["resource_type"] = case["resource_type"]
        item["expected_target_id"] = case["expected_target_id"]
        item["input_emitted"] = bool(item.get("input_emitted", False))
        results.append(item)

    if args.hide_resource_intent:
        passes = [
            item for item in results
            if item.get("status") == "pass"
            and isinstance(item.get("model"), Mapping)
            and item["model"].get("choice") is None
        ]
    else:
        passes = [
            item for item in results
            if item.get("status") == "pass"
            and isinstance(item.get("model"), Mapping)
            and isinstance(item["model"].get("choice"), Mapping)
            and item["model"]["choice"].get("target_id") == item.get("expected_target_id")
        ]
    latencies = [
        float(item["model"]["elapsed_ms"])
        for item in results
        if isinstance(item.get("model"), Mapping)
        and isinstance(item["model"].get("elapsed_ms"), (int, float))
    ]
    usage_totals: dict[str, int | float] = {}
    for item in results:
        usage = item.get("model", {}).get("usage") if isinstance(item.get("model"), Mapping) else None
        if isinstance(usage, Mapping):
            for key, value in usage.items():
                if isinstance(key, str) and type(value) in (int, float):
                    usage_totals[key] = usage_totals.get(key, 0) + value
    usage_telemetry_complete = bool(results) and all(
        isinstance(item.get("model"), Mapping)
        and isinstance(item["model"].get("usage"), Mapping)
        and bool(item["model"].get("usage"))
        for item in results
    )
    frame_ids = sorted({
        str(item.get("mission", {}).get("frame_id"))
        for item in results
        if isinstance(item.get("mission"), Mapping) and item["mission"].get("frame_id")
    })
    holdout_measurement_complete = bool(
        is_holdout
        and results
        and len(passes) == len(results)
        and not any(bool(item.get("input_emitted")) for item in results)
        and usage_telemetry_complete
    )
    if holdout_measurement_complete:
        acceptance = {
            "prd_r1b": "measured_pending_reviewer",
            "reason": (
                "frame-disjoint real replay holdout achieved complete bounded choices, "
                "zero input and usage telemetry; independent reviewer and live postcondition "
                "are still required for PRD promotion"
            ),
        }
    elif is_holdout:
        acceptance = {
            "prd_r1b": "not_evaluated",
            "reason": (
                "holdout manifest was selected but the complete bounded measurement contract "
                "was not satisfied"
            ),
        }
    else:
        acceptance = {
            "prd_r1b": "not_evaluated",
            "reason": (
                "bounded real-frame screening is not the independent holdout gate"
                if not args.hide_resource_intent
                else "bounded abstention screening is not the independent holdout gate"
            ),
        }
    payload: dict[str, Any] = {
        "schema_version": 1,
        "batch_id": args.batch_id,
        "status": "pass" if results and len(passes) == len(results) else "incomplete",
        "measurement_class": (
            (
                "holdout_multi_frame_real_replay_abstention"
                if args.hide_resource_intent
                else "holdout_multi_frame_real_replay"
            )
            if is_holdout
            else (
                "screening_multi_frame_real_replay_abstention"
                if args.hide_resource_intent
                else "screening_multi_frame_real_replay"
            )
        ),
        "intent_visibility": "hidden" if args.hide_resource_intent else "visible_semantic_fact",
        "candidate_order": "reverse" if args.reverse_candidates else "native",
        "acceptance": acceptance,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "source": {"case_manifest": str(case_manifest_path), "local_llm_config": str(Path(args.local_llm_config).resolve())},
        "manifest_split": manifest_split,
        "usage_telemetry_complete": usage_telemetry_complete,
        "sample_count": len(results),
        "pass_count": len(passes),
        "accuracy": len(passes) / len(results) if results else None,
        "distinct_frame_count": len(frame_ids),
        "latency_ms": {
            "count": len(latencies),
            "median": statistics.median(latencies) if latencies else None,
            "p95": sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)] if latencies else None,
        },
        "usage_totals": usage_totals or None,
        "input_emitted_any": any(bool(item.get("input_emitted")) for item in results),
        "results": results,
    }
    path = _write_result(evidence_root, args.batch_id, payload)
    output = dict(payload)
    output["evidence_path"] = str(path)
    print(json.dumps(output, ensure_ascii=False))
    return 0 if payload["status"] == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())
