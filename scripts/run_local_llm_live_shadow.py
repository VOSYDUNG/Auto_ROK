"""Observation-only live shadow query for the local LLM.

This script captures the current ROK frame, projects it to a semantic
ToolSnapshot, asks the loopback model a bounded non-authoritative question, and
writes both evidence JSON and overlay JSONL.  It never constructs an input
actuator and never emits mouse/keyboard events.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.gather_facts import GatherFactObservationProvider  # noqa: E402
from harness.local_llm_selector import OpenAICompatibleDecisionProvider  # noqa: E402
from harness.main_view_detector import MainViewProfile, MainViewVisualObservationProvider  # noqa: E402
from harness.mission_loader import compile_mission  # noqa: E402
from harness.mission_runtime import ActionChoice, MissionContext, ToolSnapshot  # noqa: E402
from harness.mission_selector import DeterministicMissionSelector  # noqa: E402
from harness.ocr_semantics import OcrSemanticObservationProvider, OcrTargetSpec  # noqa: E402
from harness.overlay_events import OverlayEventWriter  # noqa: E402
from harness.resource_level_control import ResourceLevelControlObservationProvider, ResourceLevelProfile  # noqa: E402
from harness.state_adapter import to_tool_snapshot  # noqa: E402
from harness.state_classifier import StateClassifier  # noqa: E402
from harness.windows_live_observation import WindowsLiveObservationProvider  # noqa: E402


def _read_json(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _candidate_specs(path: Path) -> tuple[OcrTargetSpec, ...]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("candidate file must contain a JSON list")
    result: list[OcrTargetSpec] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("candidate entries must be objects")
        target_id = item.get("target_id")
        labels = item.get("labels")
        confidence = item.get("min_confidence", 0.90)
        allow_unscored = item.get("allow_unscored_exact", False)
        if (
            not isinstance(target_id, str)
            or not target_id
            or not isinstance(labels, list)
            or not labels
            or not all(isinstance(label, str) and label for label in labels)
            or type(confidence) not in (int, float)
            or type(allow_unscored) is not bool
        ):
            raise ValueError(f"invalid candidate entry: {item!r}")
        result.append(OcrTargetSpec(target_id, tuple(labels), float(confidence), allow_unscored))
    return tuple(result)


def _local_provider(path: Path) -> OpenAICompatibleDecisionProvider:
    value = _read_json(path, "local LLM config")
    if value.get("enabled") is False:
        raise ValueError("local LLM config is disabled")
    return OpenAICompatibleDecisionProvider.from_mapping(value)


def _choice_json(choice: ActionChoice | None) -> dict[str, Any] | None:
    if choice is None:
        return None
    return {
        "action_id": choice.action_id,
        "target_id": choice.target_id,
        "arguments": dict(choice.arguments),
    }


def _shadow_candidates(snapshot: ToolSnapshot) -> tuple[ActionChoice, ...]:
    used = snapshot.facts.get("march_queue_used")
    capacity = snapshot.facts.get("march_queue_capacity")
    arguments: dict[str, Any] = {}
    if type(used) is int:
        arguments["march_queue_used"] = used
    if type(capacity) is int:
        arguments["march_queue_capacity"] = capacity
    return (
        ActionChoice("SHADOW_QUEUE_HAS_CAPACITY", arguments=arguments),
        ActionChoice("SHADOW_QUEUE_WAIT", arguments=arguments),
        ActionChoice("SHADOW_ABSTAIN", arguments=arguments),
    )


def _write_result(root: Path, run_id: str, payload: Mapping[str, Any]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{run_id}.json"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--task-id", default="one-character")
    parser.add_argument("--character-id", required=True)
    parser.add_argument("--resource-type", choices=("FOOD", "WOOD", "STONE", "GOLD"))
    parser.add_argument("--resource-level", type=int)
    parser.add_argument("--workspace-root", default=str(ROOT / "workspace" / "runtime"))
    parser.add_argument("--local-llm-config", default=str(ROOT / "config" / "local-llm.json"))
    parser.add_argument("--overlay-events")
    parser.add_argument("--ocr-targets", default=str(ROOT / "config" / "gather_ocr_targets.json"))
    parser.add_argument("--main-view-profile", default=str(ROOT / "config" / "main_view_profiles.json"))
    parser.add_argument("--resource-level-profile", default=str(ROOT / "config" / "resource_level_profile.json"))
    parser.add_argument("--evidence-root", default=str(ROOT / "workspace" / "evidence" / "local_llm"))
    parser.add_argument(
        "--ocr-backend",
        choices=("windows", "rapidocr_fixed_roi_experiment"),
        default="windows",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence_root = Path(args.evidence_root).resolve()
    if not evidence_root.is_relative_to((ROOT / "workspace" / "evidence").resolve()):
        raise SystemExit("evidence-root must stay under workspace/evidence")
    overlay_writer: OverlayEventWriter | None = None
    if args.overlay_events:
        overlay_path = Path(args.overlay_events).resolve()
        if not overlay_path.is_relative_to((ROOT / "workspace").resolve()):
            raise SystemExit("overlay-events must stay under workspace")
        overlay_writer = OverlayEventWriter(overlay_path)

    context = MissionContext("GATHER_RESOURCE", args.task_id, args.run_id)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "run_id": args.run_id,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "failed",
        "input_emitted": False,
        "shadow_mode": "observation_only",
    }
    try:
        provider = WindowsLiveObservationProvider(args.workspace_root, ocr_backend=args.ocr_backend)
        observations = OcrSemanticObservationProvider(provider, _candidate_specs(Path(args.ocr_targets).resolve()))
        observations = MainViewVisualObservationProvider(
            observations,
            MainViewProfile.load(Path(args.main_view_profile).resolve()),
        )
        observations = ResourceLevelControlObservationProvider(
            observations,
            ResourceLevelProfile.load(Path(args.resource_level_profile).resolve()),
        )
        observations = GatherFactObservationProvider(observations, character_id=args.character_id)
        bundle = observations.observe(context)
        parameters: dict[str, Any] = {}
        if args.resource_type is not None:
            parameters["resource_type"] = args.resource_type
        if args.resource_level is not None:
            parameters["resource_level"] = args.resource_level
        compiled = compile_mission(
            ROOT / "config" / "mission_flows.yaml",
            ROOT / "config" / "ui_states.yaml",
            "GATHER_RESOURCE",
            parameters or None,
        )
        classification = StateClassifier().classify(bundle.observation, bundle.scene)
        snapshot = to_tool_snapshot(context, classification, bundle.scene, compiled.flow)
        selection = DeterministicMissionSelector().select(context, snapshot, compiled.flow)
        canonical_candidates = tuple(selection.candidates)
        if len(canonical_candidates) >= 2:
            candidates = canonical_candidates
            candidate_source = "canonical_needs_decision"
        else:
            candidates = _shadow_candidates(snapshot)
            candidate_source = "shadow_queue_semantic_probe"

        llm = _local_provider(Path(args.local_llm_config).resolve())
        started = time.perf_counter()
        choice = llm.choose(snapshot, candidates)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        local_llm = {
            "model": llm.model,
            "elapsed_ms": elapsed_ms,
            "request_sha256": llm.last_request_sha256,
            "request_bytes": llm.last_request_bytes,
            "request_elapsed_ms": llm.last_request_elapsed_ms,
            "last_error": llm.last_error,
            "usage": llm.last_usage,
            "model_output": llm.last_model_output,
            "choice": _choice_json(choice),
        }
        payload.update(
            {
                "status": "pass" if llm.last_model_output is not None or llm.last_error is None else "model_failed",
                "mission": {
                    "mission_id": context.mission_id,
                    "task_id": context.task_id,
                    "character_id": args.character_id,
                },
                "snapshot": {
                    "frame_id": snapshot.frame_id,
                    "state": snapshot.state,
                    "facts": {
                        key: snapshot.facts.get(key)
                        for key in (
                            "character_id",
                            "march_queue_used",
                            "march_queue_capacity",
                            "march_queue_source",
                            "selected_search_level",
                            "resource_type",
                        )
                        if key in snapshot.facts
                    },
                },
                "selection": {
                    "decision": selection.decision.value,
                    "reason": selection.reason,
                    "canonical_candidate_count": len(canonical_candidates),
                    "candidate_source": candidate_source,
                    "candidates": [_choice_json(item) for item in candidates],
                },
                "local_llm": local_llm,
            }
        )
    except Exception as exc:
        payload.update(
            {
                "status": "failed",
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
        )

    path = _write_result(evidence_root, args.run_id, payload)
    payload["evidence_path"] = str(path)
    if overlay_writer is not None:
        overlay_writer.emit(
            "local_llm_shadow",
            {
                "run_id": args.run_id,
                "status": payload.get("status"),
                "state": (payload.get("snapshot") or {}).get("state") if isinstance(payload.get("snapshot"), Mapping) else None,
                "frame_id": (payload.get("snapshot") or {}).get("frame_id") if isinstance(payload.get("snapshot"), Mapping) else None,
                "local_llm": payload.get("local_llm"),
                "harness": {
                    "selection": payload.get("selection"),
                    "input_emitted": False,
                },
                "evidence_path": str(path),
            },
        )
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("status") == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())
