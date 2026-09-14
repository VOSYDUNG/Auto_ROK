"""Run one bounded GATHER_RESOURCE mission tick on Windows.

This command is caller-driven, not a scheduler. Live input is fail-closed unless
--arm-live is supplied and the foreground/geometry guard passes immediately
before actuation.
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
from harness.mission_loader import compile_mission  # noqa: E402
from harness.mission_runner import MissionRunner  # noqa: E402
from harness.mission_runtime import MissionContext  # noqa: E402
from harness.mission_store import CheckpointStatus, JsonMissionStore  # noqa: E402
from harness.mission_tool import BoundedMissionTool, HumanInterfaceActionProvider  # noqa: E402
from harness.ocr_semantics import OcrSemanticObservationProvider, OcrTargetSpec  # noqa: E402
from harness.policy_overlay import PolicyEvidenceObservationProvider  # noqa: E402
from harness.screen_mapped_surface import ScreenMappedSemanticActionSurface  # noqa: E402
from harness.windows_input import WindowsHumanInputActuator  # noqa: E402
from harness.windows_interference_guard import WindowsForegroundInterferenceGuard  # noqa: E402
from harness.windows_live_observation import WindowsLiveObservationProvider  # noqa: E402


PRECONDITION = "troop/commander selection policy is valid for this mission"


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
        result.append(OcrTargetSpec(
            target_id,
            tuple(labels),
            float(confidence),
            allow_unscored,
        ))
    return tuple(result)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--task-id", default="one-character")
    parser.add_argument("--character-id", required=True)
    parser.add_argument("--resource-type", required=True, choices=("FOOD", "WOOD", "STONE", "GOLD"))
    parser.add_argument("--resource-level", type=int)
    parser.add_argument(
        "--candidates",
        help="JSON OCR target specs; unscored Windows OCR requires explicit allow_unscored_exact per target",
    )
    parser.add_argument("--workspace-root", default=str(ROOT / "workspace" / "runtime"))
    parser.add_argument("--checkpoint-root", default=str(ROOT / "workspace" / "checkpoints"))
    parser.add_argument("--approve-current-troop-selection", action="store_true")
    parser.add_argument("--arm-live", action="store_true")
    parser.add_argument("--min-target-confidence", type=float, default=0.90)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not 0.0 <= args.min_target_confidence <= 1.0:
            raise ValueError("min-target-confidence must be within [0, 1]")

        compiled = compile_mission(
            ROOT / "config" / "mission_flows.yaml",
            ROOT / "config" / "ui_states.yaml",
            "GATHER_RESOURCE",
            {
                "resource_type": args.resource_type,
                "resource_level": args.resource_level,
            },
        )
        context = MissionContext("GATHER_RESOURCE", args.task_id, args.run_id)
        candidate_specs = _candidate_specs(args.candidates)

        # The raw projection validates provenance but does not manufacture a
        # confidence score for Windows.Media.Ocr. Phrase assembly/grounding is a
        # separate explicit layer so unscored targets stay visible as unscored.
        observations = WindowsLiveObservationProvider(args.workspace_root)
        observations = OcrSemanticObservationProvider(observations, candidate_specs)
        observations = GatherFactObservationProvider(
            observations,
            character_id=args.character_id,
        )
        approvals = {PRECONDITION: True} if args.approve_current_troop_selection else {}
        observations = PolicyEvidenceObservationProvider(observations, approvals)

        surface = ScreenMappedSemanticActionSurface(
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
        runner = MissionRunner(compiled, tool, JsonMissionStore(args.checkpoint_root))
        result = runner.tick(context)

        payload = {
            "status": result.status.value,
            "run_id": context.run_id,
            "checkpoint_revision": result.checkpoint.revision,
            "state": result.checkpoint.last_state,
            "frame_id": result.checkpoint.last_frame_id,
            "decision": result.checkpoint.last_decision,
            "reason": result.reason,
            "live_armed": bool(args.arm_live),
            "policy_approved": bool(args.approve_current_troop_selection),
            "ocr_target_specs": len(candidate_specs),
            "unscored_exact_enabled": any(spec.allow_unscored_exact for spec in candidate_specs),
        }
        if result.selection is not None:
            payload["selection"] = result.selection.decision.value
            payload["candidate_count"] = len(result.selection.candidates)
            if result.selection.choice is not None:
                payload["choice"] = {
                    "action_id": result.selection.choice.action_id,
                    "target_id": result.selection.choice.target_id,
                }
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
