"""One bounded deterministic mission tick with durable checkpointing."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Protocol, Sequence

from harness.mission_engine import EngineDecision, EngineStepResult, MissionEngine
from harness.mission_loader import CompiledMission
from harness.mission_runtime import ActionChoice, MissionContext, MissionTool, ToolFeedback, ToolSnapshot
from harness.mission_selector import DeterministicMissionSelector, SelectionDecision, SelectionResult
from harness.mission_store import CheckpointStatus, JsonMissionStore, MissionCheckpoint


class BoundedDecisionProvider(Protocol):
    """Optional model/human chooser; it may choose only from bounded candidates."""

    def choose(
        self,
        snapshot: ToolSnapshot,
        candidates: Sequence[ActionChoice],
    ) -> ActionChoice | None: ...


@dataclass(frozen=True)
class MissionTickResult:
    status: CheckpointStatus
    checkpoint: MissionCheckpoint
    snapshot: ToolSnapshot | None = None
    selection: SelectionResult | None = None
    engine_result: EngineStepResult | None = None
    reason: str | None = None


class MissionRunner:
    """Caller-driven mission runtime; deliberately not a scheduler."""

    def __init__(
        self,
        compiled: CompiledMission,
        tool: MissionTool,
        store: JsonMissionStore,
        *,
        selector: DeterministicMissionSelector | None = None,
        decision_provider: BoundedDecisionProvider | None = None,
    ) -> None:
        self.compiled = compiled
        self.tool = tool
        self.store = store
        self.selector = selector or DeterministicMissionSelector()
        self.decision_provider = decision_provider

    def tick(self, context: MissionContext) -> MissionTickResult:
        existing = self.store.load(context)
        if existing is not None:
            mismatch = self._checkpoint_mismatch(context, existing)
            if mismatch is not None:
                return MissionTickResult(
                    CheckpointStatus.BLOCKED,
                    existing,
                    reason=mismatch,
                )
            if existing.status is CheckpointStatus.COMPLETE:
                return MissionTickResult(
                    CheckpointStatus.COMPLETE,
                    existing,
                    reason="mission occurrence already completed",
                )

        expected_revision = existing.revision if existing is not None else 0
        engine = MissionEngine(self.compiled, self.tool)
        if existing is not None:
            engine.restore_verified_self_loops(existing.verified_self_loops)

        snapshot = self.tool.observe(context)
        baseline = existing.completion_baseline if existing is not None else None
        if context.mission_id == "GATHER_RESOURCE" and snapshot.state == "TROOP_DISPATCH_DRAWER":
            facts = snapshot.facts
            if (type(facts.get("march_queue_used")) is int and type(facts.get("march_queue_capacity")) is int
                    and facts.get("march_queue_source") in {"visible_ocr_queue_anchor", "visible_ocr_march_queue_region"}
                    and isinstance(facts.get("character_id"), str)):
                baseline = {"predicate_id": "march_queue_used_increased", "counter_fact": "march_queue_used",
                            "counter_value": facts["march_queue_used"], "capacity": facts["march_queue_capacity"],
                            "source_frame_id": snapshot.frame_id, "source": facts["march_queue_source"],
                            "character_id": facts["character_id"]}
        if baseline is not None:
            enriched = dict(snapshot.facts)
            enriched["completion_baseline"] = baseline
            snapshot = replace(snapshot, facts=enriched)

        # A dispatch can be real while the game's animation is still settling.
        # Resume verification before consulting the selector so a delayed frame
        # can never cause the same input to be selected a second time.
        if existing is not None and existing.pending_verification is not None:
            pending_result, pending = self._resume_pending_verification(
                context,
                engine,
                existing.pending_verification,
                snapshot,
            )
            status = self._status_for_engine(pending_result.decision)
            saved = self._save(
                context,
                expected_revision,
                engine,
                pending_result.after_snapshot or snapshot,
                status,
                pending_result.decision.value,
                pending_result.reason,
                completion_baseline=baseline,
                pending_verification=pending,
            )
            return MissionTickResult(
                status,
                saved,
                snapshot,
                engine_result=pending_result,
                reason=pending_result.reason,
            )

        selection = self.selector.select(
            context,
            snapshot,
            self.compiled.flow,
            verified_self_loops=engine.verified_self_loops,
        )

        if selection.decision is not SelectionDecision.AUTO:
            choice = self._bounded_choice(snapshot, selection)
            if choice is None:
                status = {
                    SelectionDecision.REOBSERVE: CheckpointStatus.REOBSERVE,
                    SelectionDecision.NEEDS_DECISION: CheckpointStatus.NEEDS_DECISION,
                    SelectionDecision.WAIT: CheckpointStatus.WAITING,
                    SelectionDecision.BLOCKED: CheckpointStatus.BLOCKED,
                }.get(selection.decision, CheckpointStatus.BLOCKED)
                saved = self._save(
                    context,
                    expected_revision,
                    engine,
                    snapshot,
                    status,
                    selection.decision.value,
                    selection.reason,
                    completion_baseline=baseline,
                )
                return MissionTickResult(status, saved, snapshot, selection, reason=selection.reason)
        else:
            choice = selection.choice

        if choice is None:
            saved = self._save(
                context,
                expected_revision,
                engine,
                snapshot,
                CheckpointStatus.NEEDS_DECISION,
                "needs_decision",
                "decision provider returned no bounded choice",
                completion_baseline=baseline,
            )
            return MissionTickResult(
                CheckpointStatus.NEEDS_DECISION,
                saved,
                snapshot,
                selection,
                reason="decision provider returned no bounded choice",
            )

        result = engine.step_from_snapshot(context, snapshot, choice)
        status = self._status_for_engine(result.decision)
        pending = self._pending_from_result(result) if result.decision is EngineDecision.REOBSERVE else None
        saved = self._save(
            context,
            expected_revision,
            engine,
            result.after_snapshot or result.snapshot,
            status,
            result.decision.value,
            result.reason,
            completion_baseline=baseline,
            pending_verification=pending,
        )
        return MissionTickResult(
            status,
            saved,
            snapshot,
            selection,
            result,
            result.reason,
        )

    def _checkpoint_mismatch(
        self,
        context: MissionContext,
        existing: MissionCheckpoint,
    ) -> str | None:
        if existing.attempt != context.attempt:
            return (
                f"checkpoint attempt {existing.attempt} does not match requested attempt "
                f"{context.attempt}; use a new run_id for a new occurrence"
            )
        if dict(existing.parameters) != dict(self.compiled.parameters):
            return "checkpoint parameters differ from the compiled mission; use a new run_id"
        return None

    def _bounded_choice(
        self,
        snapshot: ToolSnapshot,
        selection: SelectionResult,
    ) -> ActionChoice | None:
        if selection.decision is not SelectionDecision.NEEDS_DECISION:
            return None
        if self.decision_provider is None:
            return None
        choice = self.decision_provider.choose(snapshot, selection.candidates)
        if choice is None:
            return None
        if choice not in selection.candidates:
            return None
        return choice

    def _save(
        self,
        context: MissionContext,
        expected_revision: int,
        engine: MissionEngine,
        snapshot: ToolSnapshot,
        status: CheckpointStatus,
        decision: str,
        reason: str | None,
        *,
        completion_baseline: Mapping[str, object] | None = None,
        pending_verification: Mapping[str, object] | None = None,
    ) -> MissionCheckpoint:
        baseline = completion_baseline if completion_baseline is not None else snapshot.facts.get("completion_baseline")
        if isinstance(baseline, Mapping):
            baseline = dict(baseline)
        else:
            baseline = None
        checkpoint = MissionCheckpoint(
            mission_id=context.mission_id,
            task_id=context.task_id,
            run_id=context.run_id,
            attempt=context.attempt,
            parameters=dict(self.compiled.parameters),
            status=status,
            revision=expected_revision,
            last_frame_id=snapshot.frame_id,
            last_state=snapshot.state,
            last_decision=decision,
            last_reason=reason,
            verified_self_loops=engine.verified_self_loops,
            completion_baseline=baseline,
            pending_verification=dict(pending_verification) if isinstance(pending_verification, Mapping) else None,
        )
        return self.store.save(checkpoint, expected_revision=expected_revision)

    def _resume_pending_verification(
        self,
        context: MissionContext,
        engine: MissionEngine,
        pending: Mapping[str, Any],
        after: ToolSnapshot,
    ) -> tuple[EngineStepResult, Mapping[str, Any] | None]:
        """Verify a durable dispatch using only a fresh observation."""
        try:
            before = _snapshot_from_pending(pending, context)
            choice = _choice_from_pending(pending)
            feedback = _feedback_from_pending(pending)
        except (TypeError, ValueError, KeyError) as exc:
            return (
                EngineStepResult(
                    EngineDecision.BLOCKED,
                    after,
                    reason=f"malformed pending verification: {exc}",
                ),
                None,
            )
        if after.frame_id == pending.get("last_observed_frame_id"):
            return (
                EngineStepResult(
                    EngineDecision.REOBSERVE,
                    before,
                    choice,
                    feedback,
                    after,
                    "pending verification requires a newer observation frame",
                ),
                dict(pending),
            )
        result = engine.verify_after_snapshot(context, before, choice, feedback, after)
        if result.decision is EngineDecision.REOBSERVE:
            updated = dict(pending)
            if after.frame_id:
                updated["last_observed_frame_id"] = after.frame_id
            if result.feedback is not None:
                updated["feedback"] = _feedback_to_pending(result.feedback)
            return result, updated
        if result.decision in {EngineDecision.COMPLETE, EngineDecision.CONTINUE}:
            return result, None
        return result, None

    @staticmethod
    def _pending_from_result(result: EngineStepResult) -> Mapping[str, Any] | None:
        if result.choice is None or result.feedback is None or not result.feedback.success:
            return None
        if result.feedback.code not in {"DISPATCHED", "VERIFIED"}:
            return None
        before = result.snapshot
        if not before.frame_id:
            return None
        receipt = result.feedback.facts.get("receipt")
        if not isinstance(receipt, Mapping) or receipt.get("before_frame_id") != before.frame_id:
            return None
        pending: dict[str, Any] = {
            "schema_version": 1,
            "action": {
                "action_id": result.choice.action_id,
                "target_id": result.choice.target_id,
                "arguments": dict(result.choice.arguments),
            },
            "before_snapshot": {
                "mission_id": before.mission_id,
                "task_id": before.task_id,
                "frame_id": before.frame_id,
                "state": before.state,
                "facts": dict(before.facts),
            },
            "feedback": _feedback_to_pending(result.feedback),
        }
        if result.after_snapshot is not None and result.after_snapshot.frame_id:
            pending["last_observed_frame_id"] = result.after_snapshot.frame_id
        return pending

    @staticmethod
    def _status_for_engine(decision: EngineDecision) -> CheckpointStatus:
        return {
            EngineDecision.CONTINUE: CheckpointStatus.RUNNING,
            EngineDecision.COMPLETE: CheckpointStatus.COMPLETE,
            EngineDecision.WAIT: CheckpointStatus.WAITING,
            EngineDecision.REOBSERVE: CheckpointStatus.REOBSERVE,
            EngineDecision.NEEDS_DECISION: CheckpointStatus.NEEDS_DECISION,
            EngineDecision.REJECT_CHOICE: CheckpointStatus.BLOCKED,
            EngineDecision.BLOCKED: CheckpointStatus.BLOCKED,
            EngineDecision.FAILED: CheckpointStatus.FAILED,
        }[decision]


def _feedback_to_pending(feedback: ToolFeedback) -> dict[str, Any]:
    if not isinstance(feedback, ToolFeedback):
        raise ValueError("feedback is not a ToolFeedback")
    return {
        "success": bool(feedback.success),
        "code": str(feedback.code),
        "state": feedback.state,
        "facts": dict(feedback.facts),
        "completed": bool(feedback.completed),
        "reobserve_required": bool(feedback.reobserve_required),
        "message": feedback.message,
    }


def _snapshot_from_pending(pending: Mapping[str, Any], context: MissionContext) -> ToolSnapshot:
    raw = pending.get("before_snapshot")
    if not isinstance(raw, Mapping):
        raise ValueError("before_snapshot is missing")
    mission_id, task_id = raw.get("mission_id"), raw.get("task_id")
    frame_id, state = raw.get("frame_id"), raw.get("state")
    facts = raw.get("facts", {})
    if mission_id != context.mission_id or task_id != context.task_id:
        raise ValueError("before_snapshot identity does not match mission context")
    if not all(isinstance(item, str) and item for item in (frame_id, state)):
        raise ValueError("before_snapshot frame_id/state is invalid")
    if not isinstance(facts, Mapping):
        raise ValueError("before_snapshot facts must be an object")
    return ToolSnapshot(
        mission_id=mission_id,
        task_id=task_id,
        frame_id=frame_id,
        state=state,
        facts=dict(facts),
    )


def _choice_from_pending(pending: Mapping[str, Any]) -> ActionChoice:
    raw = pending.get("action")
    if not isinstance(raw, Mapping):
        raise ValueError("action is missing")
    action_id, target_id, arguments = raw.get("action_id"), raw.get("target_id"), raw.get("arguments", {})
    if not isinstance(action_id, str) or not action_id:
        raise ValueError("action_id is invalid")
    if target_id is not None and not isinstance(target_id, str):
        raise ValueError("target_id is invalid")
    if not isinstance(arguments, Mapping):
        raise ValueError("arguments must be an object")
    return ActionChoice(action_id, target_id, dict(arguments))


def _feedback_from_pending(pending: Mapping[str, Any]) -> ToolFeedback:
    raw = pending.get("feedback")
    if not isinstance(raw, Mapping):
        raise ValueError("feedback is missing")
    code, facts = raw.get("code"), raw.get("facts", {})
    if not isinstance(code, str) or not code or not isinstance(facts, Mapping):
        raise ValueError("feedback code/facts are invalid")
    return ToolFeedback(
        success=raw.get("success") is True,
        code=code,
        state=raw.get("state"),
        facts=dict(facts),
        completed=raw.get("completed") is True,
        reobserve_required=raw.get("reobserve_required") is True,
        message=raw.get("message"),
    )
