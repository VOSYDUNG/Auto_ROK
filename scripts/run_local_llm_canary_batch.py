"""Run repeated bounded local-LLM choices over a real ROK replay frame.

The batch is a screening measurement for the decision edge only.  It does not
emit input, and repeated questions over one frame are deliberately reported as
``screening`` rather than being promoted to the PRD's multi-frame R1b gate.
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


def _repo_run_file(value: str, label: str) -> Path:
    path = Path(value).resolve()
    runs = (ROOT / "workspace" / "runs").resolve()
    if not path.is_file() or not path.is_relative_to(runs):
        raise ValueError(f"{label} must be an existing file under workspace/runs")
    return path


def _read_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"expected JSON object: {path}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--capture-meta", required=True)
    parser.add_argument("--ocr", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--local-llm-config", required=True)
    parser.add_argument(
        "--resource-types",
        nargs="+",
        choices=_RESOURCE_TYPES,
        default=("FOOD", "WOOD", "STONE", "GOLD", "FOOD", "WOOD", "STONE", "GOLD", "FOOD", "WOOD"),
    )
    parser.add_argument(
        "--evidence-root",
        default=str(ROOT / "workspace" / "evidence" / "local_llm"),
    )
    return parser


def _result_from_stdout(stdout: str) -> Mapping[str, Any]:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence_root = Path(args.evidence_root).resolve()
    if not evidence_root.is_relative_to((ROOT / "workspace" / "evidence").resolve()):
        raise SystemExit("evidence-root must stay under workspace/evidence")
    capture = _repo_run_file(args.capture_meta, "capture metadata")
    ocr = _repo_run_file(args.ocr, "OCR evidence")
    image = _repo_run_file(args.image, "frame image")
    llm_config = _repo_run_file(args.local_llm_config, "local LLM config")
    started_at = datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []
    for index, resource_type in enumerate(args.resource_types, start=1):
        run_id = f"{args.batch_id}-{index:02d}-{resource_type.lower()}"
        command = [
            sys.executable,
            str(SCRIPT),
            "--run-id",
            run_id,
            "--capture-meta",
            str(capture),
            "--ocr",
            str(ocr),
            "--image",
            str(image),
            "--resource-type",
            resource_type,
            "--local-llm-config",
            str(llm_config),
        ]
        completed = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True, check=False)
        try:
            item = dict(_result_from_stdout(completed.stdout))
        except ValueError as exc:
            item = {
                "status": "runner_error",
                "error": {"type": type(exc).__name__, "message": str(exc), "stderr": completed.stderr[-2000:]},
            }
        item["batch_index"] = index
        item["resource_type"] = resource_type
        item["process_exit_code"] = completed.returncode
        item["input_emitted"] = bool(item.get("input_emitted", False))
        results.append(item)

    latencies = [
        float(item["model"]["elapsed_ms"])
        for item in results
        if isinstance(item.get("model"), Mapping)
        and isinstance(item["model"].get("elapsed_ms"), (int, float))
    ]
    usage_totals: dict[str, int | float] = {}
    for item in results:
        usage = item.get("model", {}).get("usage") if isinstance(item.get("model"), Mapping) else None
        if not isinstance(usage, Mapping):
            continue
        for key, value in usage.items():
            if isinstance(key, str) and type(value) in (int, float):
                usage_totals[key] = usage_totals.get(key, 0) + value
    passes = [item for item in results if item.get("status") == "pass"]
    payload: dict[str, Any] = {
        "schema_version": 1,
        "batch_id": args.batch_id,
        "status": "pass" if results and len(passes) == len(results) else "incomplete",
        "measurement_class": "screening_single_real_frame_replay",
        "acceptance": {
            "prd_r1b": "not_evaluated",
            "reason": "ten bounded questions reuse one real ROK frame; multi-frame holdout remains required",
        },
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "capture": str(capture),
            "ocr": str(ocr),
            "image": str(image),
            "local_llm_config": str(llm_config),
            "class": "real_rok_capture_replay",
        },
        "sample_count": len(results),
        "pass_count": len(passes),
        "accuracy": (len(passes) / len(results)) if results else None,
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
