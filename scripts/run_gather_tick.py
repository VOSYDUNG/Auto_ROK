"""Run one bounded GATHER_RESOURCE mission tick on Windows.

This command is caller-driven, not a scheduler. Live input is fail-closed unless
--arm-live is supplied and the foreground/geometry guard passes immediately
before actuation. Each invocation also writes a durable evidence record so a
later validator can distinguish dispatch from verified live completion.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.action_surface import TRAINED_NATIVE_SHORTCUTS  # noqa: E402
from harness.gather_facts import GatherFactObservationProvider  # noqa: E402
from harness.host_input_isolation import (  # noqa: E402
    HostInputIsolationEvidence,
    HostInputIsolationEvidenceError,
)
from harness.gather_replay_evidence import (  # noqa: E402
    build_gather_tick_evidence,
    save_gather_tick_evidence,
)
from harness.local_llm_selector import OpenAICompatibleDecisionProvider  # noqa: E402
from harness.main_view_detector import MainViewProfile, MainViewVisualObservationProvider  # noqa: E402
from harness.map_coordinate_provider import MapCoordinateObservationProvider  # noqa: E402
from harness.mission_loader import compile_mission  # noqa: E402
from harness.mission_runner import MissionRunner  # noqa: E402
from harness.mission_runtime import MissionContext  # noqa: E402
from harness.mission_store import CheckpointStatus, JsonMissionStore  # noqa: E402
from harness.mission_tool import BoundedMissionTool, HumanInterfaceActionProvider  # noqa: E402
from harness.ocr_semantics import OcrSemanticObservationProvider, OcrTargetSpec  # noqa: E402
from harness.overlay_events import OverlayEventWriter  # noqa: E402
from harness.policy_overlay import PolicyEvidenceObservationProvider  # noqa: E402
from harness.resource_level_control import (  # noqa: E402
    GatherScreenMappedActionSurface,
    ResourceLevelControlObservationProvider,
    ResourceLevelProfile,
)
from harness.r3_endurance_authorization import load_reserved_ticket  # noqa: E402
from harness.troop_policy import TroopSelectionApproval  # noqa: E402
from harness.windows_input import WindowsHumanInputActuator  # noqa: E402
from harness.windows_interference_guard import WindowsForegroundInterferenceGuard  # noqa: E402
from harness.windows_live_observation import WindowsLiveObservationProvider  # noqa: E402


def _candidate_specs(path: str | None) -> tuple[OcrTargetSpec, ...]:
    if path is None:
        return ()
    source = Path(path).resolve()
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("candidate file must contain a JSON list")
    result: list[OcrTargetSpec] = []
    for item in value:
        if not isinstance(item, dict):
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


def _local_llm_provider(path: str | None) -> OpenAICompatibleDecisionProvider | None:
    if path is None:
        return None
    config_path = Path(path).resolve()
    if not config_path.is_relative_to(ROOT):
        raise ValueError("local LLM config must be inside the repository")
    value = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("local LLM config must be a JSON object")
    if value.get("enabled") is False:
        return None
    return OpenAICompatibleDecisionProvider.from_mapping(value)


def _local_llm_summary(provider: OpenAICompatibleDecisionProvider | None) -> dict[str, object]:
    if provider is None:
        return {
            "configured": False,
            "model": None,
            "model_output": None,
            "last_error": None,
            "usage": None,
            "request_sha256": None,
            "request_bytes": None,
            "request_elapsed_ms": None,
        }
    return {
        "configured": True,
        "model": provider.model,
        "model_output": provider.last_model_output,
        "last_error": provider.last_error,
        "usage": provider.last_usage,
        "request_sha256": provider.last_request_sha256,
        "request_bytes": provider.last_request_bytes,
        "request_elapsed_ms": provider.last_request_elapsed_ms,
    }


def _host_input_isolation_summary(path: str | None, context: MissionContext) -> dict[str, object]:
    """Load and assess direct one-user host evidence for this occurrence."""
    if path is None:
        return {
            "provided": False,
            "ready": False,
            "trace_path": None,
            "environment": "windows_host_direct",
            "reasons": ["no direct-host input-isolation evidence supplied"],
        }
    source = Path(path).resolve()
    evidence_root = (ROOT / "workspace" / "evidence").resolve()
    if not source.is_relative_to(evidence_root):
        raise ValueError("direct-host input-isolation evidence must be under workspace/evidence")
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read direct-host input-isolation evidence: {source}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("direct-host input-isolation evidence must be a JSON object")
    # Accept either the raw trace or the assessment output, while always
    # re-assessing the trace here.
    trace = raw.get("evidence") if isinstance(raw.get("evidence"), dict) else raw
    try:
        evidence = HostInputIsolationEvidence.from_dict(trace)
    except HostInputIsolationEvidenceError as exc:
        raise ValueError(f"invalid direct-host input-isolation evidence: {exc}") from exc
    ready, assessment_reasons = evidence.assess()
    reasons = list(assessment_reasons)
    if evidence.run_id != context.run_id:
        reasons.append("direct-host trace run_id does not match the current mission occurrence")
    ready = not reasons
    return {
        "provided": True,
        "ready": ready,
        "trace_path": str(source),
        "evidence_id": evidence.evidence_id,
        "session_id": evidence.session_id,
        "environment": evidence.environment,
        "run_id": evidence.run_id,
        "unexpected_input_events": evidence.unexpected_input_events,
        "reasons": reasons,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--task-id", default="one-character")
    parser.add_argument("--character-id", required=True)
    parser.add_argument("--resource-type", required=True, choices=("FOOD", "WOOD", "STONE", "GOLD"))
    parser.add_argument("--resource-level", type=int)
    parser.add_argument(
        "--candidates",
        default=str(ROOT / "config" / "gather_ocr_targets.json"),
        help="JSON OCR target specs; defaults to the trained GATHER target set",
    )
    parser.add_argument(
        "--main-view-profile",
        default=str(ROOT / "config" / "main_view_profiles.json"),
        help="operator-trained CITY_VIEW/WORLD_MAP_VIEW visual signature profile",
    )
    parser.add_argument(
        "--resource-level-profile",
        default=str(ROOT / "config" / "resource_level_profile.json"),
        help="operator-trained resource level slider profile",
    )
    parser.add_argument("--workspace-root", default=str(ROOT / "workspace" / "runtime"))
    parser.add_argument(
        "--ocr-backend",
        choices=("windows", "rapidocr_fixed_roi_experiment"),
        default="windows",
        help="observation OCR backend; RapidOCR option is experiment-only and keeps Windows OCR as the base",
    )
    parser.add_argument("--checkpoint-root", default=str(ROOT / "workspace" / "checkpoints"))
    parser.add_argument(
        "--evidence-root",
        default=str(ROOT / "workspace" / "evidence" / "gather"),
        help="append-only per-tick GATHER evidence root",
    )
    parser.add_argument(
        "--troop-policy-approval",
        help="JSON operator approval bound to this mission/task/run/character occurrence",
    )
    parser.add_argument(
        "--approve-current-troop-selection",
        action="store_true",
        help="explicit one-shot operator approval for the current occurrence; prefer --troop-policy-approval for durable provenance",
    )
    parser.add_argument("--arm-live", action="store_true")
    parser.add_argument(
        "--r3-repetition",
        action="store_true",
        help="require a fresh append-only R3 reservation before this live tick",
    )
    parser.add_argument(
        "--r3-reservation-ledger",
        help="append-only R3 reservation ledger required by --r3-repetition",
    )
    parser.add_argument(
        "--input-isolation-evidence",
        help="raw or assessed windows_host_direct trace JSON; required and ready before --arm-live",
    )
    parser.add_argument(
        "--local-llm-config",
        help="optional repository-local OpenAI-compatible config; used only for NEEDS_DECISION candidates",
    )
    parser.add_argument(
        "--overlay-events",
        help="optional workspace JSONL event stream for the operator shadow HUD",
    )
    parser.add_argument("--min-target-confidence", type=float, default=0.90)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not 0.0 <= args.min_target_confidence <= 1.0:
            raise ValueError("min-target-confidence must be within [0, 1]")
        if args.troop_policy_approval and args.approve_current_troop_selection:
            raise ValueError(
                "use either --troop-policy-approval or --approve-current-troop-selection, not both"
            )
        if args.r3_repetition and not args.arm_live:
            raise ValueError("R3_REPETITION_REQUIRES_LIVE_ARM")
        if args.r3_repetition and not args.r3_reservation_ledger:
            raise ValueError("R3_REPETITION_REQUIRES_RESERVATION_LEDGER")
        overlay_writer: OverlayEventWriter | None = None
        if args.overlay_events:
            overlay_path = Path(args.overlay_events).resolve()
            if not overlay_path.is_relative_to((ROOT / "workspace").resolve()):
                raise ValueError("overlay events must be under workspace")
            overlay_writer = OverlayEventWriter(overlay_path)

        compiled = compile_mission(
            ROOT / "config" / "mission_flows.yaml",
            ROOT / "config" / "ui_states.yaml",
            "GATHER_RESOURCE",
            {"resource_type": args.resource_type, "resource_level": args.resource_level},
        )
        context = MissionContext("GATHER_RESOURCE", args.task_id, args.run_id)
        r3_reservation: dict[str, object] | None = None
        if args.r3_repetition:
            reservation_path = Path(args.r3_reservation_ledger).resolve()
            evidence_root = (ROOT / "workspace" / "evidence").resolve()
            if not reservation_path.is_relative_to(evidence_root):
                raise ValueError("R3 reservation ledger must be under workspace/evidence")
            r3_reservation = load_reserved_ticket(reservation_path, run_id=context.run_id)
        host_input_isolation = _host_input_isolation_summary(args.input_isolation_evidence, context)
        if args.arm_live and host_input_isolation.get("ready") is not True:
            reasons = "; ".join(str(item) for item in host_input_isolation.get("reasons", []))
            raise ValueError("LIVE_ARM_REQUIRES_READY_HOST_INPUT_ISOLATION" + (f": {reasons}" if reasons else ""))
        candidate_specs = _candidate_specs(args.candidates)
        main_view_profile = MainViewProfile.load(args.main_view_profile)
        resource_level_profile = ResourceLevelProfile.load(args.resource_level_profile)

        approval: TroopSelectionApproval | None = None
        if args.troop_policy_approval:
            approval = TroopSelectionApproval.load(args.troop_policy_approval)
        elif args.approve_current_troop_selection:
            approval = TroopSelectionApproval.explicit_cli(context, args.character_id)
        approvals = approval.approvals_for(context, args.character_id) if approval is not None else {}
        approval_summary = (
            approval.to_summary(context, args.character_id)
            if approval is not None
            else {
                "approved": False,
                "bound_to_occurrence": False,
                "source": "none",
            }
        )

        # Provenance -> OCR semantics -> trained visual/layout evidence -> trained
        # typed controls -> visible facts -> occurrence-bound operator policy.
        observations = WindowsLiveObservationProvider(
            args.workspace_root,
            ocr_backend=args.ocr_backend,
        )
        observations = OcrSemanticObservationProvider(observations, candidate_specs)
        observations = MainViewVisualObservationProvider(observations, main_view_profile)
        # Second, independent route to WORLD_MAP_VIEW.  The visual signature
        # above cannot carry that state - open terrain looks different
        # everywhere you pan - so the coordinate readout carries it instead.
        observations = MapCoordinateObservationProvider(observations)
        observations = ResourceLevelControlObservationProvider(observations, resource_level_profile)
        observations = GatherFactObservationProvider(observations, character_id=args.character_id)
        observations = PolicyEvidenceObservationProvider(observations, approvals)

        surface = GatherScreenMappedActionSurface(
            TRAINED_NATIVE_SHORTCUTS,
            min_target_confidence=args.min_target_confidence,
            allow_unscored_exact_targets=any(spec.allow_unscored_exact for spec in candidate_specs),
        )
        action_provider = HumanInterfaceActionProvider(
            surface,
            WindowsHumanInputActuator(),
            WindowsForegroundInterferenceGuard(armed=args.arm_live),
        )
        tool = BoundedMissionTool(compiled, observations, action_provider)
        decision_provider = _local_llm_provider(args.local_llm_config)
        runner = MissionRunner(
            compiled,
            tool,
            JsonMissionStore(args.checkpoint_root),
            decision_provider=decision_provider,
        )
        result = runner.tick(context)

        evidence_record = build_gather_tick_evidence(
            context=context,
            character_id=args.character_id,
            result=result,
            live_armed=bool(args.arm_live),
            host_input_isolation=host_input_isolation,
            policy_approval=approval_summary,
            main_view_profile_trained=bool(main_view_profile.prototypes),
            resource_level_profile_trained=resource_level_profile.trained,
        )
        local_llm = _local_llm_summary(decision_provider)
        evidence_record["runtime"]["local_llm"] = local_llm
        evidence_path = save_gather_tick_evidence(args.evidence_root, evidence_record)

        payload = {
            "status": result.status.value,
            "run_id": context.run_id,
            "checkpoint_revision": result.checkpoint.revision,
            "state": result.checkpoint.last_state,
            "frame_id": result.checkpoint.last_frame_id,
            "decision": result.checkpoint.last_decision,
            "reason": result.reason,
            "live_armed": bool(args.arm_live),
            "host_input_isolation": host_input_isolation,
            "policy_approved": bool(approval_summary.get("bound_to_occurrence")),
            "policy_approval_id": approval_summary.get("approval_id"),
            "policy_approval_source": approval_summary.get("source"),
            "evidence_path": str(evidence_path),
            "ocr_target_specs": len(candidate_specs),
            "unscored_exact_enabled": any(spec.allow_unscored_exact for spec in candidate_specs),
            "main_view_profile_trained": bool(main_view_profile.prototypes),
            "resource_level_profile_trained": resource_level_profile.trained,
            "local_llm_model": decision_provider.model if decision_provider is not None else None,
            "local_llm": local_llm,
            "r3_repetition": bool(args.r3_repetition),
            "r3_reservation": r3_reservation,
        }
        if result.selection is not None:
            payload["selection"] = result.selection.decision.value
            payload["candidate_count"] = len(result.selection.candidates)
            if result.selection.choice is not None:
                payload["choice"] = {
                    "action_id": result.selection.choice.action_id,
                    "target_id": result.selection.choice.target_id,
                    "arguments": dict(result.selection.choice.arguments),
                }
        if overlay_writer is not None:
            overlay_writer.emit(
                "gather_tick",
                {
                    "run_id": context.run_id,
                    "status": payload["status"],
                    "state": payload["state"],
                    "frame_id": payload["frame_id"],
                    "harness": {
                        "status": payload["status"],
                        "state": payload["state"],
                        "frame_id": payload["frame_id"],
                        "decision": payload.get("decision"),
                        "choice": payload.get("choice"),
                        "selection": payload.get("selection"),
                    },
                    "local_llm": local_llm,
                    "evidence_path": str(evidence_path),
                },
            )
        print(json.dumps(payload, ensure_ascii=False))

        if result.status in {CheckpointStatus.RUNNING, CheckpointStatus.COMPLETE}:
            return 0
        if result.status in {
            CheckpointStatus.REOBSERVE,
            CheckpointStatus.WAITING,
            CheckpointStatus.NEEDS_DECISION,
        }:
            return 3
        return 4
    except Exception as exc:
        print(
            json.dumps(
                {"status": "failed", "error": {"type": type(exc).__name__, "message": str(exc)}},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
