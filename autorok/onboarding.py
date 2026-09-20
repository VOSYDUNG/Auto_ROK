"""The six phases before the agent is allowed to decide anything.

From docs/LLM_GAMEPLAY_SPEC.md section 2. Onboarding is a cold start: the
agent has to find out where it is, what it owns and what it is for, before
any of the decision machinery means anything.

    0  LOAD_KNOWLEDGE    read the second brain, and list what it is unsure of
    1  LOCATE            which screen, which character
    2  SURVEY_CHARACTER  commanders, city hall, trading post - if no profile
    3  FLEET_STATE       free slots, and when the batch comes home
    4  ACTIVE_GOAL       an operator order, or the default ratio
    5  BUFF_CHECK        how long the gathering buff has left

Two rules carry the whole design.

ONB-001 - all six run, in order, before any action decision. A phase that did
not run is not an inconvenience; it means a later phase reasoned from a state
nobody established. ``may_decide`` is false until every phase has a result.

ONB-002 - only phase 0 may block. Without the knowledge files there is no
second brain and nothing downstream is meaningful, so that one stops
everything. Phases 1-5 failing means the agent knows less than it wanted,
which is what the ladder is for: demote one rung and carry on. The legacy
scripts had the opposite shape - any exception anywhere froze the lifecycle.

Nothing here reads a screen. The phases take callables, so the sequencing
contract is testable with no game, no capture and no Windows; what those
callables do against a live client is M7.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any, Callable, Mapping

from autorok.mission.ladder import Ladder


class OnboardingError(ValueError):
    """Raised when the onboarding contract itself is violated."""


class PhaseFailure(RuntimeError):
    """Raised by a phase step that could not complete.

    A step raises this to say "I could not establish my part". Whether that
    stops the run or costs a rung is decided here, by the phase number, not by
    the step - which is what keeps ONB-002 in one place.
    """


class Phase(IntEnum):
    LOAD_KNOWLEDGE = 0
    LOCATE = 1
    SURVEY_CHARACTER = 2
    FLEET_STATE = 3
    ACTIVE_GOAL = 4
    BUFF_CHECK = 5


PURPOSE: dict[Phase, str] = {
    Phase.LOAD_KNOWLEDGE: "read knowledge/ and list every unverified entry",
    Phase.LOCATE: "classify the current screen and read the character id",
    Phase.SURVEY_CHARACTER: "survey commanders, city hall and trading post",
    Phase.FLEET_STATE: "read free march slots and when the batch returns",
    Phase.ACTIVE_GOAL: "an operator order if one is live, else the default ratio",
    Phase.BUFF_CHECK: "how much gathering buff is left, or that it has lapsed",
}

#: The one phase permitted to stop everything.
BLOCKING_PHASE = Phase.LOAD_KNOWLEDGE


class Outcome(str, Enum):
    COMPLETE = "COMPLETE"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class PhaseResult:
    """What one phase established, or why it could not."""

    phase: Phase
    outcome: Outcome
    detail: str
    at: datetime
    value: Any = None

    def __post_init__(self) -> None:
        if not isinstance(self.phase, Phase):
            raise OnboardingError("phase must be a Phase")
        if not isinstance(self.outcome, Outcome):
            raise OnboardingError("outcome must be an Outcome")
        if not self.detail or not self.detail.strip():
            raise OnboardingError(
                "every phase result must say what it established or why it "
                "could not; a silent phase is indistinguishable from a skipped one"
            )
        if self.at.tzinfo is None:
            raise OnboardingError("phase timestamps must be timezone-aware")
        if self.outcome is Outcome.BLOCKED and self.phase is not BLOCKING_PHASE:
            raise OnboardingError(
                f"only {BLOCKING_PHASE.name} may block; {self.phase.name} must "
                "degrade instead, because the loop does not stop"
            )


#: Markers an entry uses to say it has not been confirmed against the client.
UNVERIFIED_MARKERS = ("UNVERIFIED", "NEEDS_CONFIRMATION")


@dataclass(frozen=True)
class UnverifiedEntry:
    """One thing the second brain admits it is not sure about."""

    source_file: str
    line: int
    marker: str
    text: str


def scan_unverified(knowledge_dir: str | Path) -> tuple[UnverifiedEntry, ...]:
    """List what the knowledge files say they have not confirmed - ONB-003.

    These never block. The point is the opposite: the agent has to know what
    it does not know, because an unverified fact acted on as a certain one is
    how a harness produces confident nonsense.
    """
    directory = Path(knowledge_dir)
    if not directory.is_dir():
        raise OnboardingError(f"{directory} is not a directory")
    pattern = re.compile("|".join(re.escape(marker) for marker in UNVERIFIED_MARKERS))
    found: list[UnverifiedEntry] = []
    for path in sorted(directory.glob("*.yaml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = pattern.search(line)
            if match:
                found.append(
                    UnverifiedEntry(
                        source_file=path.name,
                        line=number,
                        marker=match.group(0),
                        text=line.strip(),
                    )
                )
    return tuple(found)


class Onboarding:
    """Run the six phases and report whether deciding is permitted."""

    def __init__(self, ladder: Ladder | None = None) -> None:
        self.ladder = ladder
        self._results: dict[Phase, PhaseResult] = {}

    @property
    def results(self) -> tuple[PhaseResult, ...]:
        return tuple(self._results[phase] for phase in sorted(self._results))

    @property
    def blocked(self) -> bool:
        return any(item.outcome is Outcome.BLOCKED for item in self._results.values())

    @property
    def may_decide(self) -> bool:
        """True only when all six phases ran and phase 0 completed.

        Deliberately not "nothing blocked". A phase that never ran is the
        dangerous case - it leaves a later phase reasoning from a state nobody
        established - and that is exactly what this property exists to catch.
        """
        if len(self._results) != len(Phase):
            return False
        if self.blocked:
            return False
        return self._results[BLOCKING_PHASE].outcome is Outcome.COMPLETE

    def degraded_phases(self) -> tuple[Phase, ...]:
        return tuple(
            item.phase for item in self.results if item.outcome is Outcome.DEGRADED
        )

    def run(
        self,
        steps: Mapping[Phase, Callable[[], Any]],
        *,
        now: datetime,
    ) -> tuple[PhaseResult, ...]:
        """Execute every phase in order.

        A missing step is not silently skipped - it is a DEGRADED result
        saying so, except at phase 0 where it blocks. Skipping quietly would
        make ``may_decide`` true on a run that never looked at the game.
        """
        if now.tzinfo is None:
            raise OnboardingError("now must be timezone-aware")
        self._results.clear()

        for phase in Phase:
            step = steps.get(phase)
            if step is None:
                self._record(
                    phase, now, failure=f"no step supplied for {phase.name}"
                )
                if phase is BLOCKING_PHASE:
                    break
                continue
            try:
                value = step()
            except PhaseFailure as exc:
                self._record(phase, now, failure=str(exc) or f"{phase.name} failed")
                if phase is BLOCKING_PHASE:
                    break
                continue
            self._results[phase] = PhaseResult(
                phase=phase,
                outcome=Outcome.COMPLETE,
                detail=PURPOSE[phase],
                at=now,
                value=value,
            )
        return self.results

    def _record(self, phase: Phase, now: datetime, *, failure: str) -> None:
        if phase is BLOCKING_PHASE:
            self._results[phase] = PhaseResult(
                phase=phase,
                outcome=Outcome.BLOCKED,
                detail=(
                    f"{failure}; without the second brain nothing downstream "
                    "is meaningful, so this is the one phase that stops"
                ),
                at=now,
            )
            return
        self._results[phase] = PhaseResult(
            phase=phase, outcome=Outcome.DEGRADED, detail=failure, at=now
        )
        if self.ladder is not None:
            self.ladder.demote(f"onboarding {phase.name}: {failure}", at=now)

    def summarise(self) -> dict[str, Any]:
        return {
            "may_decide": self.may_decide,
            "blocked": self.blocked,
            "phases": [
                {
                    "phase": item.phase.name,
                    "outcome": item.outcome.value,
                    "detail": item.detail,
                }
                for item in self.results
            ],
        }


__all__ = [
    "BLOCKING_PHASE",
    "PURPOSE",
    "UNVERIFIED_MARKERS",
    "Onboarding",
    "OnboardingError",
    "Outcome",
    "Phase",
    "PhaseFailure",
    "PhaseResult",
    "UnverifiedEntry",
    "scan_unverified",
]
