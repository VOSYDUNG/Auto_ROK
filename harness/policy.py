from __future__ import annotations

from harness.contracts import (
    ActionProposal,
    GameState,
    Goal,
    PolicyDecision,
    RiskLevel,
    RuntimeDecision,
)
from knowledge.game_model import GameKnowledgeBase


class KnowledgePolicyGate:
    """Conservative action gate.

    Training is authoritative. Unknown or unvalidated behavior is not promoted to
    autonomous execution merely because a planner or LLM proposed it.
    """

    def __init__(
        self,
        knowledge: GameKnowledgeBase,
        min_state_confidence: float = 0.90,
        max_autonomous_risk: RiskLevel = RiskLevel.LOW,
    ) -> None:
        self.knowledge = knowledge
        self.min_state_confidence = min_state_confidence
        self.max_autonomous_risk = max_autonomous_risk

    def evaluate(
        self, goal: Goal, state: GameState, proposal: ActionProposal
    ) -> PolicyDecision:
        if state.confidence < self.min_state_confidence:
            return PolicyDecision(
                RuntimeDecision.REOBSERVE,
                RiskLevel.MEDIUM,
                "state confidence below autonomous threshold",
            )

        allowed, matched, risk = self.knowledge.action_constraints(state, proposal)

        if not matched:
            return PolicyDecision(
                RuntimeDecision.NEED_SEMANTIC_REVIEW,
                RiskLevel.MEDIUM,
                "action is not covered by a validated game rule",
            )

        if not allowed:
            return PolicyDecision(
                RuntimeDecision.ABORT,
                risk,
                "proposal violates a validated game rule",
                matched,
            )

        if _risk_rank(risk) > _risk_rank(self.max_autonomous_risk):
            return PolicyDecision(
                RuntimeDecision.NEED_SEMANTIC_REVIEW,
                risk,
                "risk exceeds autonomous execution threshold",
                matched,
            )

        return PolicyDecision(
            RuntimeDecision.EXECUTE,
            risk,
            "validated rule permits action",
            matched,
        )


def _risk_rank(level: RiskLevel) -> int:
    return {
        RiskLevel.NONE: 0,
        RiskLevel.LOW: 1,
        RiskLevel.MEDIUM: 2,
        RiskLevel.HIGH: 3,
        RiskLevel.CRITICAL: 4,
    }[level]
