"""Bounded deterministic execution for one compiled mission flow."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from harness.mission_loader import CompiledMission
from harness.mission_runtime import ActionChoice, MissionContext, MissionTool, ToolFeedback, ToolSnapshot


class EngineDecision(str, Enum):
    CONTINUE = "continue"
    COMPLETE = "complete"
    WAIT = "wait"
    REOBSERVE = "reobserve"
    NEEDS_DECISION = "needs_decision"
    REJECT_CHOICE = "reject_choice"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True)
class EngineStepResult:
    decision: EngineDecision
    snapshot: ToolSnapshot
    choice: ActionChoice | None = None
    feedback: ToolFeedback | None = None
    after_snapshot: ToolSnapshot | None = None
    reason: str | None = None


class MissionEngine:
    """Execute one declared transition, then verify it from fresh evidence.

    Dispatch is never success. A fresh observation is mandatory. Parameterized
    controls are allowed only when current evidence exposes a typed action
    contract, and their semantic postcondition must be visible on the fresh
    post-action frame.
    """

    def __init__(self, compiled: CompiledMission, tool: MissionTool) -> None:
        self.compiled = compiled
        self.tool = tool
        self._verified_self_loops: set[tuple[str, str, str]] = set()

    @property
    def verified_self_loops(self) -> tuple[tuple[str, str, str], ...]:
        return tuple(sorted(self._verified_self_loops))

    def restore_verified_self_loops(
        self,
        items: Sequence[tuple[str, str, str]],
    ) -> None:
        restored: set[tuple[str, str, str]] = set()
        for item in items:
            if (
                not isinstance(item, tuple)
                or len(item) != 3
                or not all(isinstance(part, str) and part for part in item)
            ):
                raise ValueError("invalid verified self-loop checkpoint entry")
            restored.add(item)
        self._verified_self_loops.update(restored)

    def step(self, context: MissionContext, choice: ActionChoice | None) -> EngineStepResult:
        snapshot = self.tool.observe(context)
        return self.step_from_snapshot(context, snapshot, choice)

    def step_from_snapshot(
        self,
        context: MissionContext,
        snapshot: ToolSnapshot,
        choice: ActionChoice | None,
    ) -> EngineStepResult:
        """Advance from an already observed snapshot without recapturing it."""
        if snapshot.mission_id != context.mission_id or snapshot.task_id != context.task_id:
            return EngineStepResult(
                EngineDecision.BLOCKED,
                snapshot,
                choice,
                reason="snapshot identity does not match mission context",
            )
        if snapshot.state in {"UNKNOWN_STATE", "AMBIGUOUS_STATE"}:
            return EngineStepResult(EngineDecision.REOBSERVE, snapshot, reason="state is not actionable")
        if choice is None:
            return EngineStepResult(EngineDecision.WAIT, snapshot, reason="no declared action selected")

        try:
            transition = self.compiled.flow.transition_for(snapshot.state, choice.action_id)
        except ValueError:
            return EngineStepResult(EngineDecision.BLOCKED, snapshot, choice, reason="compiled flow is ambiguous")
        if transition is None:
            return EngineStepResult(EngineDecision.REJECT_CHOICE, snapshot, choice, reason="choice is not declared for current state")

        allowed = {item.action_id: item for item in snapshot.allowed_actions}
        action = allowed.get(choice.action_id)
        if action is None:
            return EngineStepResult(EngineDecision.REOBSERVE, snapshot, choice, reason="choice is absent from current tool surface")
        if transition.requires_target:
            if choice.target_id is None or choice.target_id not in transition.target_ids:
                return EngineStepResult(EngineDecision.REJECT_CHOICE, snapshot, choice, reason="choice lacks declared target")
            if choice.target_id not in snapshot.target_ids:
                return EngineStepResult(EngineDecision.REOBSERVE, snapshot, choice, reason="declared target is not grounded in current frame")

        self_loop = snapshot.state in transition.expect_states
        loop_key = (context.run_id, snapshot.state, choice.action_id)
        if self_loop and loop_key in self._verified_self_loops:
            return EngineStepResult(EngineDecision.REOBSERVE, snapshot, choice, reason="verified self-loop cannot be reselected")

        required_preconditions = self.compiled.transition_preconditions.get(
            f"{transition.from_state}:{transition.action_id}", ()
        )
        missing_preconditions = _missing_preconditions(snapshot.facts, required_preconditions)
        if missing_preconditions:
            return EngineStepResult(
                EngineDecision.NEEDS_DECISION,
                snapshot,
                choice,
                reason="precondition evidence missing: " + "; ".join(missing_preconditions),
            )

        typed_contract = _typed_action_contract(snapshot, choice.action_id)
        if choice.arguments and typed_contract is None:
            return EngineStepResult(
                EngineDecision.NEEDS_DECISION,
                snapshot,
                choice,
                reason="parameterized action requires a trained typed handler: "
                + ", ".join(sorted(choice.arguments)),
            )
        if typed_contract is not None:
            contract_error = _typed_contract_request_error(typed_contract, choice)
            if contract_error is not None:
                return EngineStepResult(EngineDecision.REJECT_CHOICE, snapshot, choice, reason=contract_error)

        execute = getattr(self.tool, "execute", None)
        if not callable(execute):
            return EngineStepResult(EngineDecision.BLOCKED, snapshot, choice, reason="mission executor is unavailable")
        feedback = execute(context, snapshot, choice)
        if not feedback.success:
            decision = EngineDecision.REOBSERVE if feedback.reobserve_required else EngineDecision.FAILED
            if feedback.code == "EXECUTOR_UNAVAILABLE":
                decision = EngineDecision.BLOCKED
            return EngineStepResult(decision, snapshot, choice, feedback, reason=feedback.code)

        if feedback.code not in {"DISPATCHED", "VERIFIED"}:
            return EngineStepResult(
                EngineDecision.REOBSERVE,
                snapshot,
                choice,
                feedback,
                reason="action feedback is neither dispatched nor verified",
            )

        if feedback.code == "DISPATCHED":
            receipt_error = _dispatch_receipt_error(feedback.facts, snapshot, choice)
            if receipt_error is not None:
                return EngineStepResult(
                    EngineDecision.REOBSERVE,
                    snapshot,
                    choice,
                    feedback,
                    reason=receipt_error,
                )

        after = self.tool.observe(context)
        if not after.frame_id or after.frame_id == snapshot.frame_id:
            return EngineStepResult(EngineDecision.REOBSERVE, snapshot, choice, feedback, after, "post-observation is not fresh")

        verified_feedback = _promote_verified_feedback(feedback, snapshot, after, choice)
        completion_requested = transition.completion_edge or feedback.completed
        state_matches = self.compiled.flow.accepts_observation(transition, after.state)

        if completion_requested:
            completion_matches = _completion_matches(
                self.compiled.completion,
                required_preconditions,
                snapshot,
                after,
                verified_feedback,
            )
            if completion_matches:
                return EngineStepResult(
                    EngineDecision.COMPLETE,
                    snapshot,
                    choice,
                    verified_feedback,
                    after,
                )
            if not state_matches:
                return EngineStepResult(
                    EngineDecision.REOBSERVE,
                    snapshot,
                    choice,
                    verified_feedback,
                    after,
                    "post-observation matches neither declared transition nor typed completion predicate",
                )
            return EngineStepResult(
                EngineDecision.REOBSERVE,
                snapshot,
                choice,
                verified_feedback,
                after,
                "completion evidence is insufficient",
            )

        if not state_matches:
            return EngineStepResult(
                EngineDecision.REOBSERVE,
                snapshot,
                choice,
                verified_feedback,
                after,
                "post-observation does not match declared transition",
            )

        typed_error = _typed_postcondition_error(typed_contract, choice, after)
        if typed_error is not None:
            return EngineStepResult(
                EngineDecision.REOBSERVE,
                snapshot,
                choice,
                verified_feedback,
                after,
                typed_error,
            )

        if self_loop:
            self._verified_self_loops.add(loop_key)

        return EngineStepResult(
            EngineDecision.CONTINUE,
            snapshot,
            choice,
            verified_feedback,
            after,
        )


def _missing_preconditions(
    facts: Mapping[str, Any],
    required_preconditions: Sequence[str],
) -> tuple[str, ...]:
    if not required_preconditions:
        return ()
    evidence = facts.get("precondition_evidence")
    if not isinstance(evidence, Mapping):
        return tuple(required_preconditions)
    return tuple(item for item in required_preconditions if evidence.get(item) is not True)


def _typed_action_contract(snapshot: ToolSnapshot, action_id: str) -> Mapping[str, Any] | None:
    contracts = snapshot.facts.get("typed_action_contracts")
    if not isinstance(contracts, Mapping):
        return None
    contract = contracts.get(action_id)
    return contract if isinstance(contract, Mapping) else None


def _typed_contract_request_error(contract: Mapping[str, Any], choice: ActionChoice) -> str | None:
    if contract.get("verification_mode") != "fact_equals_argument":
        return "typed action contract uses an unsupported verification mode"
    argument = contract.get("argument")
    fact = contract.get("fact")
    if not isinstance(argument, str) or not argument or not isinstance(fact, str) or not fact:
        return "typed action contract is malformed"
    if set(choice.arguments) != {argument}:
        return "typed action arguments do not match the trained control contract"
    return None


def _typed_postcondition_error(
    contract: Mapping[str, Any] | None,
    choice: ActionChoice,
    after: ToolSnapshot,
) -> str | None:
    if contract is None:
        return None
    argument = contract.get("argument")
    fact = contract.get("fact")
    if not isinstance(argument, str) or not isinstance(fact, str):
        return "typed action contract is malformed"
    expected = choice.arguments.get(argument)
    observed = after.facts.get(fact)
    if observed != expected:
        return f"typed postcondition {fact!r} did not equal requested {argument!r}"
    return None


def _dispatch_receipt_error(
    facts: Mapping[str, Any],
    before: ToolSnapshot,
    choice: ActionChoice,
) -> str | None:
    receipt = facts.get("receipt")
    if not isinstance(receipt, Mapping):
        return "dispatch receipt is missing"
    if receipt.get("before_frame_id") != before.frame_id:
        return "dispatch receipt is bound to a different frame"
    if receipt.get("action_id") != choice.action_id:
        return "dispatch receipt action does not match choice"
    if receipt.get("target_id") != choice.target_id:
        return "dispatch receipt target does not match choice"
    if receipt.get("non_interference_confirmed") is not True:
        return "dispatch receipt lacks non-interference proof"
    if dict(receipt.get("bounded_arguments") or {}) != dict(choice.arguments):
        return "dispatch receipt arguments do not match choice"
    return None


def _promote_verified_feedback(
    feedback: ToolFeedback,
    before: ToolSnapshot,
    after: ToolSnapshot,
    choice: ActionChoice,
) -> ToolFeedback:
    """Attach post-frame provenance after a fresh observation is obtained."""
    facts = dict(feedback.facts)
    receipt = facts.get("receipt")
    if isinstance(receipt, Mapping):
        verified_receipt = dict(receipt)
    else:
        verified_receipt = {}
    verified_receipt.setdefault("action_id", choice.action_id)
    verified_receipt.setdefault("target_id", choice.target_id)
    verified_receipt.setdefault("before_frame_id", before.frame_id)
    verified_receipt.setdefault("bounded_arguments", dict(choice.arguments))
    verified_receipt["after_frame_id"] = after.frame_id
    facts["receipt"] = verified_receipt
    return ToolFeedback(
        True,
        "VERIFIED",
        state=after.state,
        facts=facts,
        completed=feedback.completed,
        reobserve_required=False,
        message=feedback.message,
    )


def _has_matching_receipt(facts: Mapping[str, Any], before_frame_id: str | None, after_frame_id: str | None) -> bool:
    receipt = facts.get("receipt")
    if not isinstance(receipt, Mapping):
        return False
    return receipt.get("before_frame_id") == before_frame_id and receipt.get("after_frame_id") == after_frame_id


def _contract_value(contract: object, name: str) -> object:
    if isinstance(contract, Mapping):
        return contract.get(name)
    return getattr(contract, name, None)


def _completion_matches(
    completion: object,
    required_preconditions: tuple[str, ...],
    before: ToolSnapshot,
    after: ToolSnapshot,
    feedback: ToolFeedback,
) -> bool:
    """Validate the compiler-provided gather completion predicate fail-closed."""
    if _contract_value(completion, "predicate_id") != "march_queue_used_increased":
        return False
    counter = _contract_value(completion, "canonical_counter_fact")
    if not isinstance(counter, str) or not counter:
        return False
    before_count, after_count = before.facts.get(counter), after.facts.get(counter)
    if type(before_count) is not int or type(after_count) is not int or after_count <= before_count:
        return False
    before_character = before.facts.get("character_id")
    after_character = after.facts.get("character_id")
    if not isinstance(before_character, str) or not before_character or before_character != after_character:
        return False
    if _missing_preconditions(before.facts, required_preconditions):
        return False
    return _has_matching_receipt(feedback.facts, before.frame_id, after.frame_id) and (
        feedback.facts["receipt"].get("character_id") == before_character
    )
