"""One bounded deterministic mission tick with durable checkpointing."""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
import math
from typing import Any, Mapping, Protocol, Sequence

from harness.mission_engine import EngineDecision, EngineStepResult, MissionEngine
from harness.mission_loader import CompiledMission
from harness.mission_runtime import ActionChoice, MissionContext, MissionTool, ToolFeedback, ToolSnapshot
from harness.mission_selector import DeterministicMissionSelector, SelectionDecision, SelectionResult
from harness.mission_store import CheckpointStatus, JsonMissionStore, MissionCheckpoint
from harness.gather_job_store import GatherClientBinding, GatherJobStoreError


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


def gather_queue_completion_baseline(snapshot: ToolSnapshot) -> dict[str, object] | None:
    """One factory for an actual Drawer queue measurement and its provenance."""
    facts = snapshot.facts
    if (snapshot.state != "TROOP_DISPATCH_DRAWER"
            or facts.get("gather_job_first_slot_queue_optional") is True
            or type(facts.get("march_queue_used")) is not int
            or type(facts.get("march_queue_capacity")) is not int
            or facts.get("march_queue_source") not in {
                "visible_ocr_queue_anchor", "visible_ocr_march_queue_region"}
            or not isinstance(facts.get("character_id"), str)
            or not isinstance(snapshot.observed_at, (int, float))
            or isinstance(snapshot.observed_at, bool)
            or not math.isfinite(snapshot.observed_at)):
        return None
    return {"predicate_id": "march_queue_used_increased", "counter_fact": "march_queue_used",
            "counter_value": facts["march_queue_used"], "capacity": facts["march_queue_capacity"],
            "source_frame_id": snapshot.frame_id, "source_timestamp": snapshot.observed_at,
            "source": facts["march_queue_source"], "character_id": facts["character_id"]}


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
        current_marker = snapshot.facts.get("completion_baseline")
        if (context.mission_id == "GATHER_RESOURCE" and isinstance(current_marker, Mapping)
                and current_marker.get("predicate_id") == "first_march_queue_appeared_at_one"
                and current_marker.get("source") == "job_initial_slot_ordinal"
                and "counter_value" not in current_marker):
            # Coordinator refreshed the ordinal from this New Troop frame.
            # A navigation checkpoint's older marker must not replace it.
            baseline = dict(current_marker)
        if context.mission_id == "GATHER_RESOURCE":
            measured = gather_queue_completion_baseline(snapshot)
            if measured is not None:
                baseline = measured
        if baseline is not None:
            enriched = dict(snapshot.facts)
            enriched["completion_baseline"] = baseline
            snapshot = replace(snapshot, facts=enriched)

        # A dispatch can be real while the game's animation is still settling.
        # Resume verification before consulting the selector so a delayed frame
        # can never cause the same input to be selected a second time.
        if existing is not None and existing.pending_verification is not None:
            recovery_reason = _reversible_navigation_recovery_reason(
                context, existing.pending_verification, snapshot,
            )
            if recovery_reason is not None:
                # CREATE_NEW_TROOP is reversible navigation. A fresh grounded
                # world-map frame proves that the stale drawer navigation is
                # no longer open; retire only that pending marker and return
                # without executing anything. The receipt summary remains in
                # last_reason for auditability; it is not VERIFIED evidence.
                saved = self._save(
                    context,
                    expected_revision,
                    engine,
                    snapshot,
                    CheckpointStatus.REOBSERVE,
                    "reconcile_pending_navigation",
                    recovery_reason,
                    completion_baseline=baseline,
                )
                return MissionTickResult(
                    CheckpointStatus.REOBSERVE,
                    saved,
                    snapshot,
                    reason=recovery_reason,
                )
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
                verified_transition=_verified_transition_from_result(context, pending_result),
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
            verified_transition=_verified_transition_from_result(context, result),
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
        verified_transition: Mapping[str, object] | None = None,
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
            verified_transition=dict(verified_transition) if isinstance(verified_transition, Mapping) else None,
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
                "observed_at": before.observed_at,
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
        observed_at=raw.get("observed_at"),
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


def _reversible_navigation_recovery_reason(
    context: MissionContext,
    pending: Mapping[str, Any],
    after: ToolSnapshot,
) -> str | None:
    """Recognize one safe stale drawer-navigation marker.

    This is intentionally narrower than generic pending recovery: a March,
    malformed receipt, unknown state, changed context, or changed client must
    continue through the normal fail-closed verification path.
    """
    if context.mission_id != "GATHER_RESOURCE" or after.state != "WORLD_MAP_VIEW":
        return None
    try:
        before = _snapshot_from_pending(pending, context)
        choice = _choice_from_pending(pending)
        feedback = _feedback_from_pending(pending)
    except (TypeError, ValueError, KeyError):
        return None
    if (before.mission_id != context.mission_id
            or before.task_id != context.task_id
            or after.mission_id != context.mission_id
            or after.task_id != context.task_id
            or not isinstance(before.frame_id, str) or not before.frame_id
            or not isinstance(pending.get("last_observed_frame_id"), str)
            or not pending.get("last_observed_frame_id")
            or not isinstance(after.frame_id, str) or not after.frame_id
            or before.frame_id == after.frame_id
            or after.frame_id == pending.get("last_observed_frame_id")
            or before.state != "TROOP_DISPATCH_DRAWER"
            or choice.action_id != "CREATE_NEW_TROOP"
            or choice.target_id != "NEW_TROOP"
            or choice.arguments != {}
            or feedback.success is not True
            or feedback.code not in {"DISPATCHED", "VERIFIED"}):
        return None
    before_character = before.facts.get("character_id")
    after_character = after.facts.get("character_id")
    if (not isinstance(before_character, str) or not before_character
            or after_character != before_character):
        return None
    before_bounds = before.facts.get("client_bounds")
    after_bounds = after.facts.get("client_bounds")
    if (before_bounds != [0, 0, 1366, 768]
            or after_bounds != [0, 0, 1366, 768]
            or before_bounds != after_bounds):
        return None
    try:
        if (GatherClientBinding.from_window(before.facts.get("window"))
                != GatherClientBinding.from_window(after.facts.get("window"))):
            return None
    except GatherJobStoreError:
        return None
    if (not isinstance(before.observed_at, (int, float))
            or isinstance(before.observed_at, bool)
            or not math.isfinite(before.observed_at)
            or not isinstance(after.observed_at, (int, float))
            or isinstance(after.observed_at, bool)
            or not math.isfinite(after.observed_at)
            or after.observed_at <= before.observed_at):
        return None
    receipt = feedback.facts.get("receipt")
    if (not isinstance(receipt, Mapping)
            or receipt.get("before_frame_id") != before.frame_id
            or receipt.get("action_id") != choice.action_id
            or receipt.get("target_id") != choice.target_id
            or receipt.get("bounded_arguments") != {}
            or receipt.get("after_frame_id") != pending.get("last_observed_frame_id")
            or receipt.get("character_id") != before_character
            or receipt.get("non_interference_confirmed") is not True):
        return None
    return (
        "retired stale reversible CREATE_NEW_TROOP navigation after fresh "
        f"WORLD_MAP_VIEW frame {after.frame_id}; pending receipt preserved "
        "for audit: " + json.dumps({
            "source": "pending_verification",
            "schema_version": pending.get("schema_version"),
            "last_observed_frame_id": pending.get("last_observed_frame_id"),
            "receipt": dict(receipt),
        }, sort_keys=True)
    )


def _verified_transition_from_result(
    context: MissionContext, result: EngineStepResult,
) -> Mapping[str, Any] | None:
    """Persist only an Engine COMPLETE whose feedback was promoted to VERIFIED."""
    if (result.decision is not EngineDecision.COMPLETE or result.choice is None
            or result.after_snapshot is None or result.feedback is None
            or result.feedback.success is not True or result.feedback.code != "VERIFIED"):
        return None

    def snapshot_data(snapshot: ToolSnapshot) -> dict[str, Any]:
        return {
            "mission_id": snapshot.mission_id, "task_id": snapshot.task_id,
            "frame_id": snapshot.frame_id, "state": snapshot.state,
            "facts": dict(snapshot.facts), "observed_at": snapshot.observed_at,
        }

    return {
        "schema_version": 1, "source": "mission_engine_complete_verified",
        "mission_id": context.mission_id, "task_id": context.task_id,
        "run_id": context.run_id,
        "before_snapshot": snapshot_data(result.snapshot),
        "after_snapshot": snapshot_data(result.after_snapshot),
        "action": {
            "action_id": result.choice.action_id,
            "target_id": result.choice.target_id,
            "arguments": dict(result.choice.arguments),
        },
        "feedback": _feedback_to_pending(result.feedback),
    }


def restore_verified_transition(
    checkpoint: MissionCheckpoint, context: MissionContext,
) -> EngineStepResult:
    """Reconstruct exact durable proof; never promote a pending receipt."""
    raw = checkpoint.verified_transition
    if (checkpoint.status is not CheckpointStatus.COMPLETE
            or checkpoint.last_decision != EngineDecision.COMPLETE.value
            or not checkpoint.matches(context)
            or not isinstance(raw, Mapping)
            or frozenset(raw) != {
                "schema_version", "source", "mission_id", "task_id", "run_id",
                "before_snapshot", "after_snapshot", "action", "feedback",
            }
            or raw.get("schema_version") != 1
            or raw.get("source") != "mission_engine_complete_verified"
            or (raw.get("mission_id"), raw.get("task_id"), raw.get("run_id"))
            != (context.mission_id, context.task_id, context.run_id)):
        raise ValueError("checkpoint lacks exact Engine COMPLETE/VERIFIED proof")
    before = _snapshot_from_pending({"before_snapshot": raw["before_snapshot"]}, context)
    after = _snapshot_from_pending({"before_snapshot": raw["after_snapshot"]}, context)
    choice = _choice_from_pending(raw)
    feedback = _feedback_from_pending(raw)
    if (feedback.success is not True or feedback.code != "VERIFIED"
            or checkpoint.last_frame_id != after.frame_id
            or before.observed_at is None or after.observed_at is None):
        raise ValueError("checkpoint VERIFIED proof is incomplete")
    return EngineStepResult(EngineDecision.COMPLETE, before, choice, feedback, after)
