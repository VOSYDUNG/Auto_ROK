from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class Provenance:
    source_surface: str
    observed_at: str
    confidence: float
    frame_id: str | None = None
    evidence_ref: str | None = None
    extractor: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")


@dataclass(frozen=True)
class ObservedFact:
    key: str
    value: Any
    provenance: Provenance


@dataclass(frozen=True)
class DerivedSignal:
    key: str
    value: Any
    evidence_keys: tuple[str, ...]
    derivation_version: str
    confidence: float

    def __post_init__(self) -> None:
        if not self.evidence_keys:
            raise ValueError("derived signals require evidence_keys")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")


@dataclass
class OperatorSnapshot:
    """Current operator profile assembled from visible game observations.

    `facts` are observations or normalized values obtained from visible UI.
    `derived` contains interpretations that must reference observed fact keys.
    The snapshot itself is harness-owned data, not hidden game state.
    """

    facts: dict[str, ObservedFact] = field(default_factory=dict)
    derived: dict[str, DerivedSignal] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def put_fact(self, fact: ObservedFact) -> None:
        current = self.facts.get(fact.key)
        if current is None:
            self.facts[fact.key] = fact
            return

        # Prefer the more confident observation when the caller is combining
        # multiple visible frames from the same acquisition pass. Temporal
        # snapshotting across sessions belongs in a history store, not here.
        if fact.provenance.confidence >= current.provenance.confidence:
            self.facts[fact.key] = fact

    def put_facts(self, facts: Mapping[str, ObservedFact] | list[ObservedFact]) -> None:
        values = facts.values() if isinstance(facts, Mapping) else facts
        for fact in values:
            self.put_fact(fact)

    def value(self, key: str, default: Any = None) -> Any:
        fact = self.facts.get(key)
        return default if fact is None else fact.value

    def require(self, key: str) -> ObservedFact:
        try:
            return self.facts[key]
        except KeyError as exc:
            raise KeyError(f"operator fact {key!r} has not been observed") from exc

    def put_derived(self, signal: DerivedSignal) -> None:
        missing = [key for key in signal.evidence_keys if key not in self.facts]
        if missing:
            raise ValueError(
                f"derived signal {signal.key!r} references missing evidence: {missing}"
            )
        self.derived[signal.key] = signal

    def role_is_observed(self) -> bool:
        return "alliance.operator_rank" in self.facts

    def as_execution_context(self) -> dict[str, Any]:
        """Return compact operator context for runtime use.

        This deliberately exports normalized values, not raw screenshots.
        """
        return {
            "facts": {key: fact.value for key, fact in self.facts.items()},
            "derived": {key: signal.value for key, signal in self.derived.items()},
        }
