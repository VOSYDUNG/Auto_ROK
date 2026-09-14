from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class CommanderState:
    commander_id: str
    owned: bool
    level: int | None = None
    stars: int | None = None
    skill_state: str | None = None
    expertise: bool | None = None
    troop_affinity: str | None = None


@dataclass(frozen=True)
class PairRecommendation:
    primary: str
    secondary: str
    role: str
    tier: str
    confidence: float
    troop_type: str | None = None
    kingdom_stage: str | None = None
    trend_status: str | None = None


@dataclass(frozen=True)
class PairFit:
    pair: PairRecommendation
    usable: bool
    score: float
    missing: tuple[str, ...]
    reasons: tuple[str, ...]


def _tier_score(tier: str) -> float:
    normalized = tier.upper().replace("+", "_PLUS").replace("-", "_MINUS")
    table = {
        "S_PLUS": 1.00,
        "S": 0.92,
        "A_PLUS": 0.86,
        "A": 0.80,
        "A_MINUS": 0.74,
        "B": 0.64,
    }
    return table.get(normalized, 0.50)


def evaluate_pair(
    pair: PairRecommendation,
    inventory: Mapping[str, CommanderState],
    *,
    operator_role: str | None = None,
    current_kingdom_stage: str | None = None,
    required_secondary_stars: int = 3,
) -> PairFit:
    missing: list[str] = []
    reasons: list[str] = []

    primary = inventory.get(pair.primary)
    secondary = inventory.get(pair.secondary)

    if primary is None or not primary.owned:
        missing.append(f"primary:{pair.primary}")
    if secondary is None or not secondary.owned:
        missing.append(f"secondary:{pair.secondary}")

    if secondary is not None and secondary.owned:
        if secondary.stars is not None and secondary.stars < required_secondary_stars:
            missing.append(f"secondary_stars<{required_secondary_stars}")

    if pair.kingdom_stage and current_kingdom_stage:
        if pair.kingdom_stage != current_kingdom_stage:
            reasons.append("kingdom_stage_mismatch")

    role_upper = pair.role.upper()
    if role_upper in {"RALLY_PVP", "GARRISON"}:
        if operator_role not in {"alliance_leader", "alliance_officer", "rally_leader", "garrison_lead"}:
            reasons.append("operator_role_not_specialist")

    score = _tier_score(pair.tier) * max(0.0, min(1.0, pair.confidence))

    if missing:
        score *= 0.25
    if "kingdom_stage_mismatch" in reasons:
        score *= 0.40
    if "operator_role_not_specialist" in reasons:
        score *= 0.50

    if primary is not None and primary.level is not None:
        if primary.level < 40:
            reasons.append("primary_level_developing")
            score *= 0.90

    usable = not missing and "kingdom_stage_mismatch" not in reasons
    return PairFit(
        pair=pair,
        usable=usable,
        score=round(score, 4),
        missing=tuple(missing),
        reasons=tuple(reasons),
    )


def rank_account_pairs(
    pairs: Iterable[PairRecommendation],
    inventory: Mapping[str, CommanderState],
    *,
    role: str,
    operator_role: str | None = None,
    current_kingdom_stage: str | None = None,
) -> list[PairFit]:
    fits = [
        evaluate_pair(
            pair,
            inventory,
            operator_role=operator_role,
            current_kingdom_stage=current_kingdom_stage,
        )
        for pair in pairs
        if pair.role.upper() == role.upper()
    ]
    return sorted(fits, key=lambda item: item.score, reverse=True)
