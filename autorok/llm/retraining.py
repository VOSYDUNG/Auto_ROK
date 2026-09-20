"""The one job only the model can do: notice the game changed.

Everything else in this project is something a deterministic harness does
better. This is not. A template match failing tells you a template failed; it
does not tell you the button was renamed, or that a dialog grew a third
option. Recognising "what has always worked stopped working" is the thing a
player does and a matcher cannot, and it is why the model is here at all.

Two rules, and they are the whole module.

LLM-008 - a signal must say WHAT CHANGED and WHICH FRAME PROVES IT. Either
one missing and it is not a signal, it is a complaint. Both are checked at
construction, so an invalid one cannot be built and then filtered later.

LLM-009 - the model PROPOSES knowledge; it never writes it. This is the line
between a system that is fed by a person and one that feeds itself, and it is
also the line that keeps a hallucinated fact from becoming a permanent one.
``knowledge/`` is written by the operator, with one review, and that is
enforced here rather than merely documented: ``write_proposal`` refuses any
destination inside the knowledge tree.

Also deliberate: a signal carries no proposed replacement target. The gameplay
spec forbids guessing one - "cấm đoán mục tiêu thay thế". Reporting that the
USE button is gone is evidence; deciding that the button three pixels over
must be the new one is invention, and there is no field here to put it in.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from autorok.mission.ladder import Ladder, Rung, is_persistently_degraded


class RetrainingError(ValueError):
    """Raised when a change signal or a proposal violates its contract."""


class ChangeTrigger(str, Enum):
    """Why the model believes the game, not the harness, changed.

    From docs/LLM_GAMEPLAY_SPEC.md section 4.3. Closed, because an open
    "OTHER" would collect every unexplained failure and the operator would
    stop reading the list.
    """

    CONTROL_ABSENT = "CONTROL_ABSENT"
    LABEL_CHANGED = "LABEL_CHANGED"
    DIALOG_SHAPE_CHANGED = "DIALOG_SHAPE_CHANGED"
    SURFACE_ABSENT_REPEATEDLY = "SURFACE_ABSENT_REPEATEDLY"
    PLAN_PERSISTENTLY_DEGRADED = "PLAN_PERSISTENTLY_DEGRADED"


@dataclass(frozen=True)
class RetrainingSignal:
    """One claim that the game changed, with the frame that shows it."""

    trigger: ChangeTrigger
    what_changed: str
    evidence_frame_id: str
    observed_at: datetime
    knowledge_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.trigger, ChangeTrigger):
            raise RetrainingError("trigger must be a ChangeTrigger")
        if not self.what_changed or not self.what_changed.strip():
            raise RetrainingError(
                "a retraining signal must say WHAT changed; without it the "
                "operator has a complaint rather than a report"
            )
        if not self.evidence_frame_id or not self.evidence_frame_id.strip():
            raise RetrainingError(
                "a retraining signal must name the frame that proves it; a "
                "claim about the game with no frame behind it is a guess"
            )
        if self.observed_at.tzinfo is None:
            raise RetrainingError("observed_at must be timezone-aware")

    def summarise(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger.value,
            "what_changed": self.what_changed.strip(),
            "evidence_frame_id": self.evidence_frame_id.strip(),
            "observed_at": self.observed_at.isoformat(),
            "knowledge_ref": self.knowledge_ref,
        }


def from_persistent_degradation(
    ladder: Ladder,
    now: datetime,
    *,
    evidence_frame_id: str,
    threshold: timedelta = timedelta(hours=1),
) -> RetrainingSignal | None:
    """Turn a long stay down the ladder into a reportable signal.

    A single scarce search is ordinary and says nothing. Hours of it is
    evidence about the kingdom or about the game, and it is the one trigger
    the harness can raise on its own - the other four need eyes on a frame.
    """
    if not is_persistently_degraded(ladder, now, threshold=threshold):
        return None
    seconds = int(ladder.time_below_top(now).total_seconds())
    last = ladder.history[-1].reason if ladder.history else "unrecorded"
    return RetrainingSignal(
        trigger=ChangeTrigger.PLAN_PERSISTENTLY_DEGRADED,
        what_changed=(
            f"the plan has been below {Rung.ORDER_WORK.name} for {seconds}s "
            f"(now {ladder.current.name}); last reason: {last}"
        ),
        evidence_frame_id=evidence_frame_id,
        observed_at=now,
    )


class ProposalStatus(str, Enum):
    """A proposal is only ever pending. There is no ACCEPTED here.

    Acceptance happens when the operator edits ``knowledge/`` themselves. If
    this module could mark something accepted it would also, sooner or later,
    be asked to act on that mark.
    """

    PENDING_OPERATOR_REVIEW = "PENDING_OPERATOR_REVIEW"


@dataclass(frozen=True)
class KnowledgeProposal:
    """A suggested addition to the second brain, for a human to approve.

    Note what is absent: there is no ``apply()``, no ``accept()``, and no
    method that takes a path in ``knowledge/``. The only way this becomes
    knowledge is a person reading it and typing it in.
    """

    proposal_id: str
    signal: RetrainingSignal
    target_knowledge_file: str
    entry: Mapping[str, Any]
    rationale: str
    status: ProposalStatus = ProposalStatus.PENDING_OPERATOR_REVIEW

    def __post_init__(self) -> None:
        if not self.proposal_id or not self.proposal_id.strip():
            raise RetrainingError("proposal_id must be non-empty text")
        if not isinstance(self.signal, RetrainingSignal):
            raise RetrainingError(
                "a proposal must carry the signal that prompted it, so the "
                "frame behind it travels with it"
            )
        if not self.target_knowledge_file.endswith(".yaml"):
            raise RetrainingError("target_knowledge_file must name a .yaml file")
        if not isinstance(self.entry, Mapping) or not self.entry:
            raise RetrainingError("entry must be a non-empty mapping")
        if not self.rationale or not self.rationale.strip():
            raise RetrainingError("a proposal must explain itself")

    def summarise(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "status": self.status.value,
            "target_knowledge_file": self.target_knowledge_file,
            "rationale": self.rationale.strip(),
            "entry": dict(self.entry),
            "signal": self.signal.summarise(),
        }

    def render(self) -> str:
        """The proposal as text for the operator to read and decide on.

        Emitted as JSON rather than YAML on purpose: YAML that looks ready to
        paste invites pasting. This is meant to be read first.
        """
        return json.dumps(self.summarise(), ensure_ascii=False, indent=2, sort_keys=True)


#: Where proposals go. Not ``knowledge/`` - that directory is the operator's.
PROPOSAL_DIRECTORY = ("workspace", "proposals")

#: The directory no automated write may ever land in.
PROTECTED_DIRECTORY = "knowledge"


def proposal_path(root: str | Path, proposal: KnowledgeProposal) -> Path:
    return Path(root).joinpath(*PROPOSAL_DIRECTORY) / f"{proposal.proposal_id}.json"


def write_proposal(
    proposal: KnowledgeProposal,
    root: str | Path,
    *,
    destination: str | Path | None = None,
) -> Path:
    """Write a proposal where the operator can review it.

    ``destination`` exists only so the refusal can be tested and so a caller
    that gets it wrong is stopped loudly. Any path that resolves inside
    ``knowledge/`` is rejected: LLM-009 is a property of the code, not a note
    in a document.
    """
    root_path = Path(root).resolve()
    target = Path(destination).resolve() if destination is not None else proposal_path(root_path, proposal)
    resolved = Path(target)
    parts = {part.casefold() for part in resolved.parts}
    if PROTECTED_DIRECTORY in parts:
        raise RetrainingError(
            f"refusing to write inside {PROTECTED_DIRECTORY}/: the model "
            "proposes knowledge, the operator writes it"
        )
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(proposal.render(), encoding="utf-8")
    return resolved


class ProposalLog:
    """Every proposal raised this session, oldest first.

    Append-only and de-duplicated by id, for the same reason the delivery
    ledger is: the aggregate is the thing an operator reviews, and a log that
    can be rewritten is not evidence.
    """

    def __init__(self) -> None:
        self._items: list[KnowledgeProposal] = []

    @property
    def proposals(self) -> tuple[KnowledgeProposal, ...]:
        return tuple(self._items)

    def add(self, proposal: KnowledgeProposal) -> None:
        if not isinstance(proposal, KnowledgeProposal):
            raise RetrainingError("add() takes a KnowledgeProposal")
        if any(item.proposal_id == proposal.proposal_id for item in self._items):
            raise RetrainingError(f"proposal {proposal.proposal_id} is already logged")
        self._items.append(proposal)

    def pending(self) -> tuple[KnowledgeProposal, ...]:
        return tuple(
            item
            for item in self._items
            if item.status is ProposalStatus.PENDING_OPERATOR_REVIEW
        )

    def by_trigger(self, trigger: ChangeTrigger) -> tuple[KnowledgeProposal, ...]:
        return tuple(item for item in self._items if item.signal.trigger is trigger)

    def __len__(self) -> int:
        return len(self._items)


def self_proposed_share(log: ProposalLog, operator_written_entries: int) -> float:
    """What fraction of new knowledge the system suggested itself.

    The metric docs/LLM_GAMEPLAY_SPEC.md names for the "second brain that
    writes itself": how much of a new domain's knowledge did the system
    propose rather than receive? Zero means it is still being fed.
    """
    total = len(log) + operator_written_entries
    return len(log) / total if total else 0.0


__all__ = [
    "PROPOSAL_DIRECTORY",
    "PROTECTED_DIRECTORY",
    "ChangeTrigger",
    "KnowledgeProposal",
    "ProposalLog",
    "ProposalStatus",
    "RetrainingError",
    "RetrainingSignal",
    "from_persistent_degradation",
    "proposal_path",
    "self_proposed_share",
    "write_proposal",
]
