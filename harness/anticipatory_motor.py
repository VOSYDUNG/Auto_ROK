from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Protocol


class MotorMode(str, Enum):
    PREPOSITION = "preposition"
    OPTIMISTIC_ACTUATE = "optimistic_actuate"
    CONFIRM_THEN_ACTUATE = "confirm_then_actuate"


@dataclass(frozen=True)
class ScreenProfile:
    profile_id: str
    width: int
    height: int
    scale: float = 1.0


@dataclass(frozen=True)
class MotorPrior:
    """Learned human-like motor expectation for a known UI transition.

    A prior is procedural knowledge, not proof that the target currently exists.
    The normalized point lets the controller stage the cursor before the target
    is fully rendered when the screen profile and transition are known.
    """

    prior_id: str
    from_state: str
    expected_next_state: str | None
    action_id: str
    normalized_x: float
    normalized_y: float
    mode: MotorMode
    profile_id: str
    confidence: float
    stable_layout: bool = True
    metadata: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.normalized_x <= 1.0:
            raise ValueError("normalized_x must be in [0, 1]")
        if not 0.0 <= self.normalized_y <= 1.0:
            raise ValueError("normalized_y must be in [0, 1]")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")

    def point(self, profile: ScreenProfile) -> tuple[int, int]:
        if profile.profile_id != self.profile_id:
            raise ValueError(
                f"motor prior {self.prior_id!r} belongs to profile "
                f"{self.profile_id!r}, got {profile.profile_id!r}"
            )
        return (
            round(self.normalized_x * profile.width),
            round(self.normalized_y * profile.height),
        )


class PointerActuator(Protocol):
    def move_to(self, x: int, y: int) -> None: ...

    def click(self, x: int, y: int) -> None: ...


@dataclass(frozen=True)
class MotorDecision:
    prior_id: str
    mode: MotorMode
    point: tuple[int, int]
    click_sent: bool
    reason: str


class AnticipatoryMotorController:
    """Uses compiled motor priors without treating them as current visual truth."""

    def __init__(
        self,
        actuator: PointerActuator,
        min_prior_confidence: float = 0.90,
    ) -> None:
        self.actuator = actuator
        self.min_prior_confidence = min_prior_confidence

    def stage(
        self,
        prior: MotorPrior,
        profile: ScreenProfile,
    ) -> MotorDecision:
        if prior.confidence < self.min_prior_confidence:
            raise ValueError("motor prior confidence below staging threshold")

        point = prior.point(profile)
        self.actuator.move_to(*point)

        if prior.mode is MotorMode.OPTIMISTIC_ACTUATE:
            if not prior.stable_layout:
                return MotorDecision(
                    prior.prior_id,
                    prior.mode,
                    point,
                    False,
                    "unstable layout: staged cursor only",
                )
            self.actuator.click(*point)
            return MotorDecision(
                prior.prior_id,
                prior.mode,
                point,
                True,
                "trained stable transition: optimistic click sent; verify visually",
            )

        return MotorDecision(
            prior.prior_id,
            prior.mode,
            point,
            False,
            "cursor staged at learned target prior",
        )

    def commit_after_confirmation(
        self,
        prior: MotorPrior,
        profile: ScreenProfile,
        visual_target_confirmed: bool,
    ) -> MotorDecision:
        point = prior.point(profile)
        if not visual_target_confirmed:
            return MotorDecision(
                prior.prior_id,
                prior.mode,
                point,
                False,
                "current-frame target not confirmed",
            )
        self.actuator.click(*point)
        return MotorDecision(
            prior.prior_id,
            prior.mode,
            point,
            True,
            "current-frame target confirmed; click sent",
        )
