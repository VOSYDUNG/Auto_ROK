"""One bounded deterministic mission tick with durable checkpointing."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol, Sequence

from harness.mission_engine import EngineDecision, EngineStepResult, MissionEngine
from harness.mission_loader import CompiledMission
from harness.mission_runtime import ActionChoice, MissionContext, MissionTool, ToolSnapshot
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
        saved = self._save(
            context,
            expected_revision,
            engine,
            result.after_snapshot or result.snapshot,
            status,
            result.decision.value,
            result.reason,
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
    ) -> MissionCheckpoint:
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
        )
        return self.store.save(checkpoint, expected_revision=expected_revision)

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
