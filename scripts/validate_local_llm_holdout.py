"""Validate a frame-disjoint local-LLM NEEDS_DECISION holdout manifest.

This command never calls the model and never emits input.  It proves that the
holdout images/OCR are frame-bound and disjoint from the screening decision
matrix, so a later loopback run cannot accidentally report training replay as
holdout accuracy.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = (ROOT / "workspace" / "runs").resolve()
EVIDENCE_ROOT = (ROOT / "workspace" / "evidence" / "local_llm").resolve()
sys.path.insert(0, str(ROOT))


class HoldoutValidationError(ValueError):
    pass


def _read(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), strict=False)
    except (OSError, json.JSONDecodeError) as exc:
        raise HoldoutValidationError(f"cannot read {label}: {path}") from exc


def _run_file(value: str, label: str) -> Path:
    path = (ROOT / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    if not path.is_file() or not path.is_relative_to(RUNS_ROOT):
        raise HoldoutValidationError(f"{label} must be an existing file under workspace/runs: {value}")
    return path


def _manifest(path: Path, label: str) -> list[Mapping[str, Any]]:
    raw = _read(path, label)
    if not isinstance(raw, Mapping) or not isinstance(raw.get("cases"), list) or not raw["cases"]:
        raise HoldoutValidationError(f"{label} must contain a non-empty cases list")
    cases: list[Mapping[str, Any]] = []
    for item in raw["cases"]:
        if not isinstance(item, Mapping):
            raise HoldoutValidationError(f"{label} contains a non-object case")
        cases.append(item)
    return cases


def _frame_for_case(case: Mapping[str, Any], label: str) -> str:
    case_id = case.get("id")
    if not isinstance(case_id, str) or not case_id:
        raise HoldoutValidationError(f"{label} case id is missing")
    resource_type = case.get("resource_type")
    expected_target = case.get("expected_target_id", f"SEARCH_CATEGORY_{resource_type}")
    if resource_type not in {"FOOD", "WOOD", "STONE", "GOLD"}:
        raise HoldoutValidationError(f"{label} case {case_id} has invalid resource_type")
    if expected_target != f"SEARCH_CATEGORY_{resource_type}":
        raise HoldoutValidationError(f"{label} case {case_id} has mismatched expected_target_id")
    capture_path = _run_file(str(case.get("capture_meta", "")), f"{label} capture metadata")
    ocr_path = _run_file(str(case.get("ocr", "")), f"{label} OCR")
    image_path = _run_file(str(case.get("image", "")), f"{label} image")
    capture = _read(capture_path, "capture metadata")
    ocr = _read(ocr_path, "OCR")
    if not isinstance(capture, Mapping) or capture.get("status") != "captured":
        raise HoldoutValidationError(f"{label} case {case_id} capture is not successful")
    frame = capture.get("frame")
    if not isinstance(frame, Mapping) or not isinstance(frame.get("id"), str) or not frame["id"]:
        raise HoldoutValidationError(f"{label} case {case_id} frame id is missing")
    digest = frame.get("image_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise HoldoutValidationError(f"{label} case {case_id} image hash is missing")
    actual = hashlib.sha256(image_path.read_bytes()).hexdigest()
    if actual != digest:
        raise HoldoutValidationError(f"{label} case {case_id} image hash does not match capture")
    if not isinstance(ocr, Mapping) or ocr.get("frame_id") != frame["id"] or ocr.get("image_sha256") != digest:
        raise HoldoutValidationError(f"{label} case {case_id} OCR is not bound to capture frame/hash")
    return str(frame["id"])


def validate(holdout_path: Path, training_path: Path) -> dict[str, Any]:
    holdout = _manifest(holdout_path, "holdout manifest")
    training = _manifest(training_path, "training manifest")
    errors: list[str] = []
    holdout_ids: set[str] = set()
    training_frames: set[str] = set()
    holdout_frames: dict[str, str] = {}
    for case in training:
        try:
            training_frames.add(_frame_for_case(case, "training"))
        except HoldoutValidationError as exc:
            errors.append(str(exc))
    for case in holdout:
        case_id = str(case.get("id", ""))
        if case_id in holdout_ids:
            errors.append(f"duplicate holdout case id: {case_id}")
            continue
        holdout_ids.add(case_id)
        try:
            frame_id = _frame_for_case(case, "holdout")
            holdout_frames[case_id] = frame_id
            if frame_id in training_frames:
                errors.append(f"holdout frame overlaps training matrix: {frame_id}")
        except HoldoutValidationError as exc:
            errors.append(str(exc))
    return {
        "schema_version": 1,
        "status": "ready_for_model_run" if not errors else "blocked",
        "measurement_class": "local_llm_holdout_manifest_validation",
        "acceptance": {
            "prd_r1b": "not_evaluated",
            "reason": "frame-disjoint cases are ready; model endpoint run and outcome evidence are still required",
        },
        "holdout_manifest": str(holdout_path),
        "training_manifest": str(training_path),
        "holdout_case_count": len(holdout),
        "holdout_frame_count": len(set(holdout_frames.values())),
        "training_frame_count": len(training_frames),
        "overlap_count": sum(frame in training_frames for frame in holdout_frames.values()),
        "errors": errors,
        "input_emitted": False,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdout-cases", default=str(ROOT / "config" / "local_llm_holdout_cases.json"))
    parser.add_argument("--training-cases", default=str(ROOT / "config" / "local_llm_decision_matrix_cases.json"))
    parser.add_argument("--output", default=str(EVIDENCE_ROOT / "needs-decision-gpt-oss-holdout-manifest-20260918.json"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = Path(args.output).resolve()
    if not output.is_relative_to(EVIDENCE_ROOT) or output == EVIDENCE_ROOT:
        raise SystemExit("output must stay under workspace/evidence/local_llm")
    try:
        report = validate(Path(args.holdout_cases).resolve(), Path(args.training_cases).resolve())
    except (OSError, HoldoutValidationError) as exc:
        report = {
            "schema_version": 1,
            "status": "invalid",
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "input_emitted": False,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    printed = dict(report)
    printed["evidence_path"] = str(output)
    print(json.dumps(printed, ensure_ascii=False))
    return 0 if report.get("status") == "ready_for_model_run" else 3


if __name__ == "__main__":
    raise SystemExit(main())
