from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class ConfidenceBand(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class RuntimeDecision(str, Enum):
    EXECUTE = "execute"
    REOBSERVE = "reobserve"
    WAIT = "wait"
    RECOVER = "recover"
    NEED_SEMANTIC_REVIEW = "need_semantic_review"
    ABORT = "abort"


class RiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class BoundingBox:
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def center(self) -> tuple[int, int]:
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)


@dataclass(frozen=True)
class Evidence:
    source: str
    label: str
    confidence: float
    bbox: BoundingBox | None = None
    value: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Observation:
    timestamp: float
    frame_id: str
    window_size: tuple[int, int]
    evidence: Sequence[Evidence] = field(default_factory=tuple)


@dataclass(frozen=True)
class GameState:
    name: str
    confidence: float
    evidence: Sequence[Evidence] = field(default_factory=tuple)
    attributes: Mapping[str, Any] = field(default_factory=dict)

    @property
    def band(self) -> ConfidenceBand:
        if self.confidence >= 0.90:
            return ConfidenceBand.HIGH
        if self.confidence >= 0.75:
            return ConfidenceBand.MEDIUM
        if self.confidence > 0.0:
            return ConfidenceBand.LOW
        return ConfidenceBand.UNKNOWN


@dataclass(frozen=True)
class Goal:
    name: str
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionProposal:
    name: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    expected_postcondition: str | None = None
    source: str = "deterministic"
    rationale: str | None = None


@dataclass(frozen=True)
class PolicyDecision:
    decision: RuntimeDecision
    risk: RiskLevel
    reason: str
    matched_rules: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class VerificationResult:
    success: bool
    reason: str
    state: GameState | None = None
