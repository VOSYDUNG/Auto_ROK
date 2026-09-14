"""Canonical MissionTool bridge for deterministic observation and bounded OS input."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from harness.human_io import (
    HUMAN_INTERFACE_BOUNDARY,
    HumanInputActuator,
    KeyboardAction,
    MotorChannel,
    MouseAction,
)
from harness.action_surface import ActionRequest, InputKind, ResolvedInput, SemanticActionSurface
from harness.contracts import Observation
from harness.mission_loader import CompiledMission
from harness.mission_runtime import ActionChoice, MissionContext, ToolFeedback, ToolSnapshot
from harness.scene_graph import SceneGraph
from harness.state_adapter import to_tool_snapshot
from harness.state_classifier import StateClassifier


@dataclass(frozen=True)
class ObservationBundle:
    """One observation and scene graph proven to describe the same frame."""

    observation: Observation
    scene: SceneGraph


class ObservationProvider(Protocol):
    """Produce fresh visible evidence for one bounded mission step."""

    def observe(self, context: MissionContext) -> ObservationBundle: ...


@dataclass(frozen=True)
class InterferenceCheck:
    """Authorization result before any host input is emitted."""

    allowed: bool
    code: str
    facts: Mapping[str, Any] = field(default_factory=dict)


class InterferenceGuard(Protocol):
    """Fail-closed host/isolation gate evaluated before actuation."""

    def check(
        self,
        context: MissionContext,
        before: ToolSnapshot,
        choice: ActionChoice,
        scene: SceneGraph,
        resolved: ResolvedInput,
    ) -> InterferenceCheck: ...


@dataclass(frozen=True)
class ActionDispatchReceipt:
    """Evidence that an action was (or was not) dispatched.

    A dispatch receipt is intentionally *not* a success verdict.  The
    MissionEngine must obtain a fresh post-action observation and verify the
    compiled transition before it can promote this receipt to VERIFIED.
    """

    action_id: str
    before_frame_id: str
    dispatched: bool
    target_id: str | None = None
    non_interference_confirmed: bool = False
    code: str = "DISPATCHED"
    facts: Mapping[str, Any] = field(default_factory=dict)
    message: str | None = None


class ActionProvider(Protocol):
    """Dispatch one already-allowed semantic action."""

    def dispatch(
        self,
        context: MissionContext,
        before: ToolSnapshot,
        choice: ActionChoice,
        scene: SceneGraph,
    ) -> ActionDispatchReceipt: ...


class HumanInterfaceActionProvider:
    """Resolve semantic actions and emit only ordinary mouse/keyboard input.

    Live actuation requires an explicit InterferenceGuard.  The guard is called
    after resolution but before ``perform``; a denied check never emits input.
    """

    def __init__(
        self,
        surface: SemanticActionSurface,
        actuator: HumanInputActuator,
        guard: InterferenceGuard,
    ) -> None:
        self.surface = surface
        self.actuator = actuator
        self.guard = guard

    def dispatch(
        self,
        context: MissionContext,
        before: ToolSnapshot,
        choice: ActionChoice,
        scene: SceneGraph,
    ) -> ActionDispatchReceipt:
        if not before.frame_id or before.frame_id != scene.frame_id:
            return ActionDispatchReceipt(
                choice.action_id,
                before.frame_id or "",
                False,
                choice.target_id,
                False,
                "STALE_BEFORE_FRAME",
                message="snapshot and scene are not bound to the same current frame",
            )

        try:
            resolved = self.surface.resolve(
                ActionRequest(choice.action_id, choice.target_id, dict(choice.arguments)),
                scene=scene,
            )
        except (LookupError, ValueError, RuntimeError) as exc:
            return ActionDispatchReceipt(
                choice.action_id,
                before.frame_id,
                False,
                choice.target_id,
                False,
                "ACTION_RESOLUTION_FAILED",
                message=str(exc),
            )

        try:
            check = self.guard.check(context, before, choice, scene, resolved)
        except Exception as exc:
            return ActionDispatchReceipt(
                choice.action_id,
                before.frame_id,
                False,
                choice.target_id,
                False,
                "INTERFERENCE_CHECK_FAILED",
                message=str(exc),
            )
        if not check.allowed:
            return ActionDispatchReceipt(
                choice.action_id,
                before.frame_id,
                False,
                choice.target_id,
                False,
                check.code or "INTERFERENCE_BLOCKED",
                facts=dict(check.facts),
                message="host/isolation guard denied actuation",
            )

        if resolved.kind is InputKind.HOTKEY:
            if not resolved.key:
                return ActionDispatchReceipt(
                    choice.action_id,
                    before.frame_id,
                    False,
                    choice.target_id,
                    True,
                    "INVALID_RESOLVED_INPUT",
                    facts=dict(check.facts),
                )
            HUMAN_INTERFACE_BOUNDARY.validate_motor_channel(MotorChannel.KEYBOARD)
            action = KeyboardAction(tuple(part for part in resolved.key.split("+") if part))
        elif resolved.kind is InputKind.CLICK_TARGET:
            if resolved.point is None:
                return ActionDispatchReceipt(
                    choice.action_id,
                    before.frame_id,
                    False,
                    choice.target_id,
                    True,
                    "INVALID_RESOLVED_INPUT",
                    facts=dict(check.facts),
                )
            HUMAN_INTERFACE_BOUNDARY.validate_motor_channel(MotorChannel.MOUSE)
            action = MouseAction("click", x=resolved.point[0], y=resolved.point[1], button="left")
        else:  # pragma: no cover - current InputKind is exhaustive
            return ActionDispatchReceipt(
                choice.action_id,
                before.frame_id,
                False,
                choice.target_id,
                True,
                "UNSUPPORTED_INPUT_KIND",
                facts=dict(check.facts),
            )

        try:
            self.actuator.perform(action)
        except Exception as exc:
            return ActionDispatchReceipt(
                choice.action_id,
                before.frame_id,
                False,
                choice.target_id,
                True,
                "ACTUATION_UNCERTAIN",
                facts=dict(check.facts),
                message=str(exc),
            )

        facts = dict(check.facts)
        facts.update(
            {
                "input_kind": resolved.kind.value,
                "input_source": resolved.source,
                "bounded_arguments": dict(choice.arguments),
            }
        )
        return ActionDispatchReceipt(
            action_id=choice.action_id,
            before_frame_id=before.frame_id,
            dispatched=True,
            target_id=choice.target_id,
            non_interference_confirmed=True,
            code="DISPATCHED",
            facts=facts,
        )


class BoundedMissionTool:
    """Canonical bridge from visible evidence to MissionEngine's tool contract."""

    def __init__(
        self,
        compiled: CompiledMission,
        observations: ObservationProvider,
        actions: ActionProvider,
        *,
        classifier: StateClassifier | None = None,
    ) -> None:
        self.compiled = compiled
        self.observations = observations
        self.actions = actions
        self.classifier = classifier or StateClassifier()
        self._scenes: dict[str, SceneGraph] = {}

    def observe(self, context: MissionContext) -> ToolSnapshot:
        bundle = self.observations.observe(context)
        if bundle.observation.frame_id != bundle.scene.frame_id:
            raise ValueError("observation and scene must describe the same frame")
        classification = self.classifier.classify(bundle.observation, bundle.scene)
        snapshot = to_tool_snapshot(
            context,
            classification,
            bundle.scene,
            self.compiled.flow,
        )
        if not snapshot.frame_id:
            raise ValueError("mission observation must have a frame id")
        self._scenes[snapshot.frame_id] = bundle.scene
        if len(self._scenes) > 8:
            oldest = next(iter(self._scenes))
            self._scenes.pop(oldest, None)
        return snapshot

    def execute(
        self,
        context: MissionContext,
        before: ToolSnapshot,
        choice: ActionChoice,
    ) -> ToolFeedback:
        if not before.frame_id:
            return ToolFeedback(False, "MISSING_BEFORE_FRAME", reobserve_required=True)
        scene = self._scenes.get(before.frame_id)
        if scene is None:
            return ToolFeedback(False, "STALE_BEFORE_FRAME", reobserve_required=True)

        receipt = self.actions.dispatch(context, before, choice, scene)
        receipt_facts = {
            "action_id": receipt.action_id,
            "before_frame_id": receipt.before_frame_id,
            "target_id": receipt.target_id,
            "non_interference_confirmed": receipt.non_interference_confirmed,
            "bounded_arguments": dict(choice.arguments),
        }
        character_id = before.facts.get("character_id")
        if isinstance(character_id, str) and character_id:
            receipt_facts["character_id"] = character_id
        facts = dict(receipt.facts)
        facts["receipt"] = receipt_facts

        if receipt.action_id != choice.action_id:
            return ToolFeedback(
                False,
                "RECEIPT_ACTION_MISMATCH",
                facts=facts,
                reobserve_required=True,
            )
        if receipt.before_frame_id != before.frame_id:
            return ToolFeedback(
                False,
                "RECEIPT_FRAME_MISMATCH",
                facts=facts,
                reobserve_required=True,
            )
        if receipt.target_id != choice.target_id:
            return ToolFeedback(
                False,
                "RECEIPT_TARGET_MISMATCH",
                facts=facts,
                reobserve_required=True,
            )
        if not receipt.dispatched:
            return ToolFeedback(
                False,
                receipt.code or "DISPATCH_FAILED",
                facts=facts,
                reobserve_required=True,
                message=receipt.message,
            )
        if not receipt.non_interference_confirmed:
            return ToolFeedback(
                False,
                "INTERFERENCE_UNVERIFIED",
                facts=facts,
                reobserve_required=True,
            )

        return ToolFeedback(
            True,
            "DISPATCHED",
            facts=facts,
            completed=False,
            reobserve_required=True,
            message=receipt.message,
        )
