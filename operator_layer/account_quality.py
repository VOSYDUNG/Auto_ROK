from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


QUALITY_DIMENSIONS = (
    "progression_maturity",
    "combat_history",
    "reserve_optionality",
    "equipment_readiness",
    "armament_readiness",
    "commander_depth",
    "migration_mobility",
    "farm_network_capacity",
    "kingdom_environment_fit",
)


@dataclass(frozen=True)
class QualityDimension:
    """One explainable account-quality dimension.

    V1 intentionally does not convert dimensions to a universal 0-100 score.
    `value` may be a structured summary, category, or versioned numeric metric,
    but every dimension must retain its evidence keys.
    """

    dimension: str
    value: Any
    evidence_keys: tuple[str, ...]
    confidence: float
    method_version: str
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.dimension not in QUALITY_DIMENSIONS:
            raise ValueError(f"unknown quality dimension: {self.dimension}")
        if not self.evidence_keys:
            raise ValueError("quality dimensions require evidence_keys")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")


@dataclass
class AccountQualityVector:
    """Multi-dimensional account readiness profile.

    The vector is used to describe what an account is capable of and where its
    constraints are. It is not a sale-price estimator and should not be used as
    hidden mission policy.
    """

    dimensions: dict[str, QualityDimension] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def put(self, item: QualityDimension) -> None:
        self.dimensions[item.dimension] = item

    def require(self, dimension: str) -> QualityDimension:
        try:
            return self.dimensions[dimension]
        except KeyError as exc:
            raise KeyError(f"quality dimension {dimension!r} is not available") from exc

    def missing_dimensions(self) -> tuple[str, ...]:
        return tuple(
            dimension
            for dimension in QUALITY_DIMENSIONS
            if dimension not in self.dimensions
        )

    def evidence_keys(self) -> tuple[str, ...]:
        ordered: list[str] = []
        seen: set[str] = set()
        for item in self.dimensions.values():
            for key in item.evidence_keys:
                if key not in seen:
                    seen.add(key)
                    ordered.append(key)
        return tuple(ordered)

    def as_context(self) -> dict[str, Any]:
        return {
            "dimensions": {
                key: {
                    "value": item.value,
                    "confidence": item.confidence,
                    "method_version": item.method_version,
                }
                for key, item in self.dimensions.items()
            },
            "missing_dimensions": list(self.missing_dimensions()),
        }


def validate_evidence(
    vector: AccountQualityVector,
    available_fact_keys: Iterable[str],
) -> None:
    available = set(available_fact_keys)
    missing = sorted(set(vector.evidence_keys()) - available)
    if missing:
        raise ValueError(f"account quality vector references missing facts: {missing}")
