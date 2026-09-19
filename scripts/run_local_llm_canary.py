"""Replay a real ROK search-panel frame through the NEEDS_DECISION edge.

This canary is deliberately observation-only.  It rebuilds the frame-bound
OCR/scene contracts from persisted capture metadata and then compiles the
GATHER_RESOURCE flow without a pre-selected resource type.  That leaves four
valid category candidates, so the local model gets a genuine bounded decision
instead of being called on a one-action fast path.  No action provider or
Windows input backend is constructed.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.local_llm_selector import OpenAICompatibleDecisionProvider  # noqa: E402
from harness.main_view_detector import MainViewProfile, MainViewVisualObservationProvider  # noqa: E402
from harness.mission_loader import compile_mission  # noqa: E402
from harness.mission_runtime import MissionContext  # noqa: E402
from harness.mission_selector import DeterministicMissionSelector, SelectionDecision  # noqa: E402
from harness.observation_bridge import (  # noqa: E402
    ObservationBridgeError,
    project_observation,
)
from harness.ocr_semantics import OcrSemanticObservationProvider, OcrTargetSpec  # noqa: E402
from harness.resource_level_control import ResourceLevelControlObservationProvider, ResourceLevelProfile  # noqa: E402
from harness.gather_facts import GatherFactObservationProvider  # noqa: E402
from harness.state_adapter import to_tool_snapshot  # noqa: E402
from harness.state_classifier import StateClassifier  # noqa: E402
from harness.mission_tool import ObservationBundle, ObservationProvider  # noqa: E402


class CanaryError(ValueError):
    pass


class _ReplayProvider:
    """ObservationProvider backed by one persisted, hash-verified frame."""

    def __init__(self, bundle: ObservationBundle) -> None:
        self.bundle = bundle

    def observe(self, context: MissionContext) -> ObservationBundle:
        return self.bundle


def _repo_run_file(value: str, label: str) -> Path:
    path = Path(value).resolve()
    runs = (ROOT / "workspace" / "runs").resolve()
    if not path.is_file() or not path.is_relative_to(runs):
        raise CanaryError(f"{label} must be an existing file under workspace/runs")
    return path


def _read_json_value(path: Path, label: str) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), strict=False)
    except (OSError, json.JSONDecodeError) as exc:
        raise CanaryError(f"cannot read {label}: {path}: {exc}") from exc
    return value


def _read_json(path: Path, label: str) -> Mapping[str, Any]:
    value = _read_json_value(path, label)
    if not isinstance(value, Mapping):
        raise CanaryError(f"{label} must contain a JSON object: {path}")
    return value


def _capture_time(capture: Mapping[str, Any]) -> datetime:
    frame = capture.get("frame")
    raw = frame.get("captured_at") if isinstance(frame, Mapping) else None
    if not isinstance(raw, str):
        raise CanaryError("capture frame captured_at is required for replay")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CanaryError("capture frame captured_at is invalid") from exc
    if parsed.tzinfo is None:
        raise CanaryError("capture frame captured_at needs a timezone")
    return parsed.astimezone(timezone.utc)


def _target_specs(path: Path) -> tuple[OcrTargetSpec, ...]:
    raw = _read_json_value(path, "OCR target config")
    if not isinstance(raw, list):
        raise CanaryError("OCR target config must be a JSON list")
    specs: list[OcrTargetSpec] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise CanaryError("OCR target entries must be objects")
        target_id, labels = item.get("target_id"), item.get("labels")
        if (
            not isinstance(target_id, str)
            or not target_id
            or not isinstance(labels, list)
            or not labels
            or not all(isinstance(label, str) and label for label in labels)
        ):
            raise CanaryError(f"invalid OCR target entry: {item!r}")
        confidence = item.get("min_confidence", 0.90)
        allow_unscored = item.get("allow_unscored_exact", False)
        if type(confidence) not in (int, float) or type(allow_unscored) is not bool:
            raise CanaryError(f"invalid OCR target threshold/authorization: {item!r}")
        specs.append(OcrTargetSpec(target_id, tuple(labels), float(confidence), allow_unscored))
    return tuple(specs)


def _compose_replay(
    capture: Mapping[str, Any],
    ocr: Mapping[str, Any],
    image: Path,
    context: MissionContext,
    target_specs: tuple[OcrTargetSpec, ...],
    main_view_profile: MainViewProfile,
    resource_level_profile: ResourceLevelProfile,
    character_id: str,
    resource_type: str,
    hide_resource_intent: bool = False,
) -> ObservationBundle:
    # Replay uses the capture's own timestamp as the comparison clock.  This
    # proves provenance/hash/geometry without pretending an old frame is live.
    projected = project_observation(
        capture,
        ocr,
        image,
        (),
        now=_capture_time(capture),
        max_age_seconds=5.0,
    )
    if projected.observation is None or projected.scene is None:
        raise CanaryError("replay projection returned no observation/scene")
    # The image path is acquisition metadata for the harness only.  It is
    # attached before the visual provider runs so the CPU detector can consume
    # the replay image; the local-LLM projection explicitly strips path/image
    # fields before any model request.
    replay_facts = dict(projected.scene.facts)
    replay_facts["image_path"] = str(image)
    replay_facts["image_path_source"] = "historical_frame_replay"
    replay_scene = replace(projected.scene, facts=replay_facts)
    bundle: ObservationBundle = ObservationBundle(projected.observation, replay_scene)
    provider: ObservationProvider = _ReplayProvider(bundle)
    provider = OcrSemanticObservationProvider(provider, target_specs)
    provider = MainViewVisualObservationProvider(provider, main_view_profile)
    provider = ResourceLevelControlObservationProvider(provider, resource_level_profile)
    provider = GatherFactObservationProvider(provider, character_id=character_id)
    bundle = provider.observe(context)
    facts = dict(bundle.scene.facts)
    # The normal canary is intent-conditioned: the requested resource is a
    # bounded semantic fact supplied by the mission.  The optional hidden
    # mode deliberately removes it so the same real frame can test whether
    # the model abstains instead of guessing when no intent distinguishes the
    # four candidates.
    if not hide_resource_intent:
        facts["resource_type"] = resource_type
    facts["replay"] = {
        "status": "historical_frame_replay",
        "source": "real_rok_capture_artifact",
        "current_truth": False,
    }
    return ObservationBundle(bundle.observation, replace(bundle.scene, facts=facts))


def _choice_json(choice: Any) -> dict[str, Any] | None:
    if choice is None:
        return None
    return {
        "action_id": choice.action_id,
        "target_id": choice.target_id,
        "arguments": dict(choice.arguments),
    }


def _load_provider(path: Path | None) -> tuple[OpenAICompatibleDecisionProvider | None, str]:
    if path is None:
        return None, "not_configured"
    value = _read_json(path, "local LLM config")
    if value.get("enabled") is False:
        return None, "disabled_in_config"
    try:
        return OpenAICompatibleDecisionProvider.from_mapping(value), "enabled"
    except ValueError as exc:
        raise CanaryError(f"invalid local LLM config: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--capture-meta", required=True)
    parser.add_argument("--ocr", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--resource-type", required=True, choices=("FOOD", "WOOD", "STONE", "GOLD"))
    parser.add_argument("--task-id", default="one-character")
    parser.add_argument("--character-id", default="char-replay-01")
    parser.add_argument(
        "--hide-resource-intent",
        action="store_true",
        help="omit the requested resource fact and require a bounded abstention",
    )
    parser.add_argument(
        "--reverse-candidates",
        action="store_true",
        help="reverse the bounded candidate order to probe position bias",
    )
    parser.add_argument(
        "--ocr-targets",
        default=str(ROOT / "config" / "gather_ocr_targets.json"),
    )
    parser.add_argument(
        "--main-view-profile",
        default=str(ROOT / "config" / "main_view_profiles.json"),
    )
    parser.add_argument(
        "--resource-level-profile",
        default=str(ROOT / "config" / "resource_level_profile.json"),
    )
    parser.add_argument("--local-llm-config")
    parser.add_argument(
        "--evidence-root",
        default=str(ROOT / "workspace" / "evidence" / "local_llm"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence_root = Path(args.evidence_root).resolve()
    if not evidence_root.is_relative_to((ROOT / "workspace" / "evidence").resolve()):
        raise SystemExit("evidence-root must stay under workspace/evidence")
    try:
        capture_path = _repo_run_file(args.capture_meta, "capture metadata")
        ocr_path = _repo_run_file(args.ocr, "OCR evidence")
        image_path = _repo_run_file(args.image, "frame image")
        capture = _read_json(capture_path, "capture metadata")
        ocr = _read_json(ocr_path, "OCR evidence")
        target_specs = _target_specs(Path(args.ocr_targets).resolve())
        main_view_profile = MainViewProfile.load(Path(args.main_view_profile).resolve())
        resource_level_profile = ResourceLevelProfile.load(Path(args.resource_level_profile).resolve())
        context = MissionContext("GATHER_RESOURCE", args.task_id, args.run_id)
        bundle = _compose_replay(
            capture,
            ocr,
            image_path,
            context,
            target_specs,
            main_view_profile,
            resource_level_profile,
            args.character_id,
            args.resource_type,
            args.hide_resource_intent,
        )
        compiled = compile_mission(
            ROOT / "config" / "mission_flows.yaml",
            ROOT / "config" / "ui_states.yaml",
            "GATHER_RESOURCE",
            {"resource_level": None},
        )
        classification = StateClassifier().classify(bundle.observation, bundle.scene)
        snapshot = to_tool_snapshot(context, classification, bundle.scene, compiled.flow)
        selection = DeterministicMissionSelector().select(context, snapshot, compiled.flow)
        candidates = tuple(reversed(selection.candidates)) if args.reverse_candidates else tuple(selection.candidates)
        intent_visibility = "hidden" if args.hide_resource_intent else "visible_semantic_fact"
        expected: dict[str, Any] = {
            "action_id": None if args.hide_resource_intent else "SELECT_RESOURCE_TYPE",
            "target_id": None if args.hide_resource_intent else f"SEARCH_CATEGORY_{args.resource_type}",
            "behavior": "abstain" if args.hide_resource_intent else "select_expected_target",
        }
        payload: dict[str, Any] = {
            "schema_version": 1,
            "run_id": args.run_id,
            "status": "failed",
            "source": {
                "capture": str(capture_path),
                "ocr": str(ocr_path),
                "image": str(image_path),
                "class": "real_rok_capture_replay",
            },
            "mission": {
                "mission_id": context.mission_id,
                "task_id": context.task_id,
                "resource_type": args.resource_type,
                "frame_id": snapshot.frame_id,
            },
            "snapshot": {
                "state": snapshot.state,
                "target_ids": list(snapshot.target_ids),
                "allowed_action_ids": [item.action_id for item in snapshot.allowed_actions],
            },
            "selection": {
                "decision": selection.decision.value,
                "reason": selection.reason,
                "candidate_count": len(candidates),
                "candidates": [_choice_json(choice) for choice in candidates],
            },
            "input_emitted": False,
            "expected": expected,
            "experiment": {
                "intent_visibility": intent_visibility,
                "candidate_order": "reverse" if args.reverse_candidates else "native",
                "candidate_source": "real_rok_capture_replay",
                "input_contract": "semantic_only_no_geometry",
            },
            "model": None,
        }
        if selection.decision is not SelectionDecision.NEEDS_DECISION or len(candidates) < 2:
            payload["status"] = "needs_decision_branch_not_grounded"
            payload["error"] = "replay did not expose at least two bounded candidates"
            return _write_result(evidence_root, args.run_id, payload, 3)

        provider, config_status = _load_provider(
            Path(args.local_llm_config).resolve() if args.local_llm_config else None
        )
        payload["model"] = {
            "config_status": config_status,
            "model": provider.model if provider is not None else None,
            "endpoint": provider.config.endpoint if provider is not None else None,
        }
        if provider is None:
            payload["status"] = "needs_decision_ready_model_unavailable"
            return _write_result(evidence_root, args.run_id, payload, 3)

        started = time.perf_counter()
        choice = provider.choose(snapshot, candidates)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        payload["model"].update({
            "elapsed_ms": elapsed_ms,
            "request_sha256": provider.last_request_sha256,
            "request_bytes": provider.last_request_bytes,
            "request_elapsed_ms": provider.last_request_elapsed_ms,
            "last_error": provider.last_error,
            "usage": provider.last_usage,
            "choice": _choice_json(choice),
        })
        expected = payload["expected"]
        if choice is None and args.hide_resource_intent:
            payload["status"] = "pass"
            return _write_result(evidence_root, args.run_id, payload, 0)
        if choice is None:
            payload["status"] = "model_abstained_or_failed"
            return _write_result(evidence_root, args.run_id, payload, 3)
        if args.hide_resource_intent:
            payload["status"] = "unsafe_guess_without_intent"
            return _write_result(evidence_root, args.run_id, payload, 4)
        if choice.action_id == expected["action_id"] and choice.target_id == expected["target_id"]:
            payload["status"] = "pass"
            return _write_result(evidence_root, args.run_id, payload, 0)
        payload["status"] = "wrong_bounded_choice"
        return _write_result(evidence_root, args.run_id, payload, 4)
    except (OSError, ObservationBridgeError, CanaryError, ValueError) as exc:
        payload = {
            "schema_version": 1,
            "run_id": args.run_id,
            "status": "failed",
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "input_emitted": False,
        }
        return _write_result(evidence_root, args.run_id, payload, 2)


def _write_result(root: Path, run_id: str, payload: Mapping[str, Any], code: int) -> int:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{run_id}.json"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    output = dict(payload)
    output["evidence_path"] = str(path)
    print(json.dumps(output, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
