from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class ExposureMode(str, Enum):
    AUTO = "auto"
    HUMAN_APPROVAL = "human_approval"
    DISABLED = "disabled"


@dataclass(frozen=True)
class FactRequirement:
    key: str
    equals: Any | None = None
    one_of: Sequence[Any] = field(default_factory=tuple)

    def satisfied_by(self, facts: Mapping[str, Any]) -> bool:
        if self.key not in facts:
            return False
        value = facts[self.key]
        if self.one_of:
            return value in self.one_of
        if self.equals is not None:
            return value == self.equals
        return bool(value)


@dataclass(frozen=True)
class CapabilityRule:
    action_id: str
    mode: ExposureMode = ExposureMode.AUTO
    required_facts: Sequence[FactRequirement] = field(default_factory=tuple)
    forbidden_facts: Sequence[FactRequirement] = field(default_factory=tuple)
    reason: str | None = None


@dataclass(frozen=True)
class CapabilityDecision:
    exposed: bool
    requires_human_approval: bool
    reason: str


class CapabilityGate:
    """Decide whether a known game capability may enter allowed_actions.

    The gate separates world knowledge ("this action exists") from autonomous
    scope ("the current mission may expose it now"). It is intentionally
    generic: game-specific mechanics are data in knowledge/config files.
    """

    def __init__(self, rules: Sequence[CapabilityRule]) -> None:
        self._rules = {rule.action_id: rule for rule in rules}
        if len(self._rules) != len(rules):
            raise ValueError("duplicate action_id in capability rules")

    def evaluate(
        self,
        action_id: str,
        facts: Mapping[str, Any],
    ) -> CapabilityDecision:
        rule = self._rules.get(action_id)
        if rule is None:
            return CapabilityDecision(
                exposed=False,
                requires_human_approval=False,
                reason="capability has no exposure rule",
            )

        for requirement in rule.forbidden_facts:
            if requirement.satisfied_by(facts):
                return CapabilityDecision(
                    exposed=False,
                    requires_human_approval=False,
                    reason=f"forbidden fact matched: {requirement.key}",
                )

        missing = [
            requirement.key
            for requirement in rule.required_facts
            if not requirement.satisfied_by(facts)
        ]
        if missing:
            return CapabilityDecision(
                exposed=False,
                requires_human_approval=False,
                reason="missing required facts: " + ", ".join(missing),
            )

        if rule.mode is ExposureMode.DISABLED:
            return CapabilityDecision(
                exposed=False,
                requires_human_approval=False,
                reason=rule.reason or "capability disabled by policy",
            )

        if rule.mode is ExposureMode.HUMAN_APPROVAL:
            return CapabilityDecision(
                exposed=True,
                requires_human_approval=True,
                reason=rule.reason or "human approval required",
            )

        return CapabilityDecision(
            exposed=True,
            requires_human_approval=False,
            reason=rule.reason or "capability requirements satisfied",
        )
