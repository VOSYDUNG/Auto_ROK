from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from harness.contracts import ActionProposal, GameState, RiskLevel


@dataclass(frozen=True)
class GameRule:
    rule_id: str
    description: str
    required_states: Sequence[str] = field(default_factory=tuple)
    allowed_actions: Sequence[str] = field(default_factory=tuple)
    forbidden_actions: Sequence[str] = field(default_factory=tuple)
    preconditions: Mapping[str, Any] = field(default_factory=dict)
    postconditions: Mapping[str, Any] = field(default_factory=dict)
    exceptions: Sequence[str] = field(default_factory=tuple)
    reputation_risk: RiskLevel = RiskLevel.NONE
    validated: bool = False

    def applies_to(self, state: GameState) -> bool:
        return not self.required_states or state.name in self.required_states


class GameKnowledgeBase:
    """In-memory knowledge layer.

    V1 deliberately keeps storage simple. YAML/SQLite adapters can be added after
    the game vocabulary and rules are trained and stable.
    """

    def __init__(self, rules: Iterable[GameRule] = ()) -> None:
        self._rules = {rule.rule_id: rule for rule in rules}

    def add(self, rule: GameRule) -> None:
        if rule.rule_id in self._rules:
            raise ValueError(f"duplicate rule_id: {rule.rule_id}")
        self._rules[rule.rule_id] = rule

    def rules_for_state(self, state: GameState) -> list[GameRule]:
        return [
            rule
            for rule in self._rules.values()
            if rule.validated and rule.applies_to(state)
        ]

    def action_constraints(
        self, state: GameState, proposal: ActionProposal
    ) -> tuple[bool, list[str], RiskLevel]:
        matched: list[str] = []
        blocked = False
        risk = RiskLevel.NONE

        for rule in self.rules_for_state(state):
            if proposal.name in rule.forbidden_actions:
                blocked = True
                matched.append(rule.rule_id)
            elif rule.allowed_actions and proposal.name in rule.allowed_actions:
                matched.append(rule.rule_id)

            if _risk_rank(rule.reputation_risk) > _risk_rank(risk):
                risk = rule.reputation_risk

        return (not blocked, matched, risk)


def _risk_rank(level: RiskLevel) -> int:
    order = {
        RiskLevel.NONE: 0,
        RiskLevel.LOW: 1,
        RiskLevel.MEDIUM: 2,
        RiskLevel.HIGH: 3,
        RiskLevel.CRITICAL: 4,
    }
    return order[level]
