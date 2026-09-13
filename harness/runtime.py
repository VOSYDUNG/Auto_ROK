from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from harness.contracts import (
    ActionProposal,
    GameState,
    Goal,
    Observation,
    PolicyDecision,
    RuntimeDecision,
    VerificationResult,
)


class Observer(Protocol):
    def observe(self) -> Observation: ...


class StateClassifier(Protocol):
    def classify(self, observation: Observation) -> GameState: ...


class Planner(Protocol):
    def propose(self, goal: Goal, state: GameState) -> ActionProposal | None: ...


class PolicyGate(Protocol):
    def evaluate(
        self, goal: Goal, state: GameState, proposal: ActionProposal
    ) -> PolicyDecision: ...


class Executor(Protocol):
    def execute(self, proposal: ActionProposal) -> None: ...


class Verifier(Protocol):
    def verify(
        self,
        before: GameState,
        proposal: ActionProposal,
        after: GameState,
    ) -> VerificationResult: ...


class SemanticFallback(Protocol):
    def diagnose(self, goal: Goal, observation: Observation, state: GameState) -> str: ...


@dataclass(frozen=True)
class StepResult:
    decision: RuntimeDecision
    state_before: GameState
    proposal: ActionProposal | None = None
    policy: PolicyDecision | None = None
    verification: VerificationResult | None = None
    semantic_note: str | None = None


class AgenticHarness:
    """Single-step runtime.

    The scheduler owns repetition. Keeping one step small makes every action
    auditable and prevents a long macro from continuing after the UI diverges.
    """

    def __init__(
        self,
        observer: Observer,
        classifier: StateClassifier,
        planner: Planner,
        policy: PolicyGate,
        executor: Executor,
        verifier: Verifier,
        semantic_fallback: SemanticFallback | None = None,
        min_plan_confidence: float = 0.75,
    ) -> None:
        self.observer = observer
        self.classifier = classifier
        self.planner = planner
        self.policy = policy
        self.executor = executor
        self.verifier = verifier
        self.semantic_fallback = semantic_fallback
        self.min_plan_confidence = min_plan_confidence

    def step(self, goal: Goal) -> StepResult:
        before_observation = self.observer.observe()
        before_state = self.classifier.classify(before_observation)

        if before_state.confidence < self.min_plan_confidence:
            if self.semantic_fallback is None:
                return StepResult(RuntimeDecision.REOBSERVE, before_state)

            note = self.semantic_fallback.diagnose(
                goal, before_observation, before_state
            )
            return StepResult(
                RuntimeDecision.NEED_SEMANTIC_REVIEW,
                before_state,
                semantic_note=note,
            )

        proposal = self.planner.propose(goal, before_state)
        if proposal is None:
            return StepResult(RuntimeDecision.WAIT, before_state)

        policy = self.policy.evaluate(goal, before_state, proposal)
        if policy.decision is not RuntimeDecision.EXECUTE:
            return StepResult(
                policy.decision,
                before_state,
                proposal=proposal,
                policy=policy,
            )

        self.executor.execute(proposal)

        after_observation = self.observer.observe()
        after_state = self.classifier.classify(after_observation)
        verification = self.verifier.verify(before_state, proposal, after_state)

        return StepResult(
            RuntimeDecision.EXECUTE if verification.success else RuntimeDecision.RECOVER,
            before_state,
            proposal=proposal,
            policy=policy,
            verification=verification,
        )
