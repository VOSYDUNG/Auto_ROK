from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class MissionContext:
    mission_id: str
    task_id: str
    run_id: str
    attempt: int = 0


@dataclass(frozen=True)
class AllowedAction:
    action_id: str
    requires_target: bool = False
    target_ids: Sequence[str] = field(default_factory=tuple)
    argument_hints: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolSnapshot:
    """What GPT-OSS is allowed to see in the hot path.

    The harness has already converted pixels/OCR/memory/timers into symbolic
    state. Raw screen coordinates are deliberately excluded.
    """

    mission_id: str
    task_id: str
    frame_id: str | None
    state: str
    facts: Mapping[str, Any] = field(default_factory=dict)
    allowed_actions: Sequence[AllowedAction] = field(default_factory=tuple)
    target_ids: Sequence[str] = field(default_factory=tuple)
    last_feedback: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionChoice:
    action_id: str
    target_id: str | None = None
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolFeedback:
    success: bool
    code: str
    state: str | None = None
    facts: Mapping[str, Any] = field(default_factory=dict)
    completed: bool = False
    reobserve_required: bool = True
    message: str | None = None


class StepDecision(str, Enum):
    CONTINUE = "continue"
    COMPLETE = "complete"
    WAIT = "wait"
    REOBSERVE = "reobserve"
    REJECT_CHOICE = "reject_choice"
    FAILED = "failed"


@dataclass(frozen=True)
class MissionStepResult:
    decision: StepDecision
    snapshot: ToolSnapshot
    choice: ActionChoice | None = None
    feedback: ToolFeedback | None = None
    reason: str | None = None


class MissionTool(Protocol):
    def observe(self, context: MissionContext) -> ToolSnapshot: ...

    def execute(
        self,
        context: MissionContext,
        snapshot: ToolSnapshot,
        choice: ActionChoice,
    ) -> ToolFeedback: ...


class DecisionSelector(Protocol):
    """GPT-OSS adapter or a deterministic selector.

    This interface intentionally exposes selection, not free-form planning.
    """

    def select(self, snapshot: ToolSnapshot) -> ActionChoice | None: ...


class MissionRuntime:
    """One bounded decision/action cycle for a mission task."""

    def __init__(self, tool: MissionTool, selector: DecisionSelector) -> None:
        self.tool = tool
        self.selector = selector

    def step(self, context: MissionContext) -> MissionStepResult:
        snapshot = self.tool.observe(context)

        if not snapshot.allowed_actions:
            return MissionStepResult(
                StepDecision.WAIT,
                snapshot,
                reason="tool exposed no valid action for the current state",
            )

        choice = self.selector.select(snapshot)
        if choice is None:
            return MissionStepResult(
                StepDecision.WAIT,
                snapshot,
                reason="decision selector chose to wait",
            )

        allowed = {
            action.action_id: action for action in snapshot.allowed_actions
        }
        action_spec = allowed.get(choice.action_id)
        if action_spec is None:
            return MissionStepResult(
                StepDecision.REJECT_CHOICE,
                snapshot,
                choice=choice,
                reason="selected action was not exposed by the tool",
            )

        if action_spec.requires_target:
            if choice.target_id is None:
                return MissionStepResult(
                    StepDecision.REJECT_CHOICE,
                    snapshot,
                    choice=choice,
                    reason="selected action requires a semantic target handle",
                )
            if choice.target_id not in action_spec.target_ids:
                return MissionStepResult(
                    StepDecision.REJECT_CHOICE,
                    snapshot,
                    choice=choice,
                    reason="target is not valid for the selected action",
                )
            if choice.target_id not in snapshot.target_ids:
                return MissionStepResult(
                    StepDecision.REOBSERVE,
                    snapshot,
                    choice=choice,
                    reason="target handle is not grounded in the current frame",
                )

        feedback = self.tool.execute(context, snapshot, choice)

        if feedback.completed and feedback.success:
            decision = StepDecision.COMPLETE
        elif feedback.success:
            decision = (
                StepDecision.REOBSERVE
                if feedback.reobserve_required
                else StepDecision.CONTINUE
            )
        else:
            decision = (
                StepDecision.REOBSERVE
                if feedback.reobserve_required
                else StepDecision.FAILED
            )

        return MissionStepResult(
            decision,
            snapshot,
            choice=choice,
            feedback=feedback,
        )
