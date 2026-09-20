"""The strategic tier: the consumer the decision packets never had.

R1 in docs/DESIGN_BRIEF.md found a producer with no consumer -
``MissionScheduler.decision_packets()`` built a packet for every signal that
needed a decision, returned it, and the chain stopped there. The measurement
that made the local model look too slow (20.6 s) was taken on the tactical
tier, where it sits on the critical path. This is the tier the model was
meant for, and here the fleet is waiting hours for marches to come home.

``StrategicPlanner.plan()`` always returns a ``MissionIntent``. There is no
failure path that yields nothing:

    no candidates        HOLD - waiting is the correct move, not an error
    one candidate        take it, and do not spend a model call on it
    model unavailable    deterministic fallback, recorded as such
    model abstains       the same fallback, also recorded as such

That is the loop-level half of the rule the ladder enforces at the action
level: an action may fail closed, the loop may not stop.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from autorok.llm.intent import (
    DecidedBy,
    IntentCandidate,
    IntentKind,
    MissionIntent,
    StrategicSnapshot,
    fallback_choice,
)
from autorok.llm.transport import (
    LocalLLMConfig,
    LocalLLMError,
    build_request,
    exactly_one,
    json_content,
    post,
    raw_content,
    usage_summary,
)

STRATEGIC_SYSTEM_PROMPT = (
    "You are the strategic decision tier of an Auto_ROK harness. "
    "You are given the state of a farming fleet and a list of candidate "
    "intents the harness has already verified it can carry out. "
    "Choose exactly one candidate by its intent_id. "
    "Do not plan steps, name screens, invent intents, or describe how to "
    "perform anything - the harness owns execution. "
    'Return JSON only: {"intent_id": string, "reason": string}. '
    'Return {"intent_id": null, "reason": string} when the evidence does not '
    "distinguish the candidates."
)

#: Synthesised when there is nothing to do. It is never offered to the model:
#: abstaining already covers "I cannot tell these apart", and offering HOLD as
#: a choice would let a model decide to leave a march slot empty, which is a
#: cost the harness should never put on the table.
HOLD_CANDIDATE = IntentCandidate(
    intent_id="HOLD",
    kind=IntentKind.HOLD,
    note="every character is in the field; wait for a batch to come home",
)


class StrategicDecisionProvider:
    """One bounded strategic request against the local model."""

    def __init__(
        self,
        config: LocalLLMConfig,
        *,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.config = config
        self._opener = opener
        self.last_error: str | None = None
        self.last_usage: dict[str, int | float] | None = None
        self.last_request_sha256: str | None = None
        self.last_request_bytes: int | None = None
        self.last_request_elapsed_ms: float | None = None
        self.last_model_output: str | None = None

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        opener: Callable[..., Any] = urlopen,
    ) -> "StrategicDecisionProvider":
        return cls(LocalLLMConfig.from_mapping(value), opener=opener)

    @property
    def model(self) -> str:
        return self.config.model

    def decide(self, snapshot: StrategicSnapshot) -> MissionIntent | None:
        """Return one candidate the model chose, or ``None``.

        ``None`` covers three different things on purpose - the model
        abstained, the call failed, the reply did not resolve - because the
        caller's response to all three is the same deterministic fallback.
        Which one it was is in ``last_error``, which is ``None`` after an
        abstention and set after a failure.
        """
        self.last_error = None
        self.last_usage = None
        self.last_request_sha256 = None
        self.last_request_bytes = None
        self.last_request_elapsed_ms = None
        self.last_model_output = None

        if len(snapshot.candidates) < 2:
            self.last_error = (
                "fewer than two candidates; the harness decides without asking"
            )
            return None

        request_body = build_request(
            self.config,
            self.config.prompt_or(STRATEGIC_SYSTEM_PROMPT),
            snapshot.as_payload(),
        )
        self.last_request_sha256 = hashlib.sha256(request_body).hexdigest()
        self.last_request_bytes = len(request_body)

        started = time.perf_counter()
        try:
            parsed = post(self.config, request_body, opener=self._opener)
            self.last_usage = usage_summary(parsed)
            self.last_model_output = raw_content(parsed)
            answer = json_content(parsed)
            if not isinstance(answer, Mapping):
                raise LocalLLMError("strategic reply must be a JSON object")

            reason = answer.get("reason")
            reason_text = reason.strip() if isinstance(reason, str) else ""

            intent_id = answer.get("intent_id")
            if intent_id is None:
                # A deliberate abstention. Not an error, and deliberately not
                # recorded as one - the evidence did not separate the
                # candidates, which is a real and correct answer.
                return None
            if not isinstance(intent_id, str):
                raise LocalLLMError("intent_id must be text or null")

            candidate = exactly_one(
                [item for item in snapshot.candidates if item.intent_id == intent_id],
                what="intent_id",
            )
            return MissionIntent(
                candidate=candidate,
                reason=reason_text or f"model chose {candidate.intent_id}",
                decided_by=DecidedBy.MODEL,
            )
        except (HTTPError, URLError, OSError, TimeoutError, ValueError) as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None
        finally:
            self.last_request_elapsed_ms = (time.perf_counter() - started) * 1000.0


class StrategicPlanner:
    """Turn a snapshot into exactly one intent, model or no model.

    The counters are not decoration. ``SC-02`` asks for the model to be
    entered on no more than five ticks in a hundred, and the only honest way
    to report that is to count the calls the planner actually made against the
    cycles it actually planned.
    """

    def __init__(self, provider: StrategicDecisionProvider | None = None) -> None:
        self.provider = provider
        self.plans = 0
        self.model_calls = 0
        self.model_decisions = 0

    @property
    def entries_per_100_plans(self) -> float:
        """How often the model was entered, per hundred planning cycles."""
        if self.plans == 0:
            return 0.0
        return 100.0 * self.model_calls / self.plans

    def plan(self, snapshot: StrategicSnapshot) -> MissionIntent:
        self.plans += 1
        candidates = snapshot.candidates

        if not candidates:
            return MissionIntent(
                candidate=HOLD_CANDIDATE,
                reason="no character is eligible with a free slot; waiting",
                decided_by=DecidedBy.HARNESS_ONLY_OPTION,
            )

        if len(candidates) == 1:
            only = candidates[0]
            return MissionIntent(
                candidate=only,
                reason=(
                    f"{only.intent_id} is the only move available; "
                    "not worth a model call"
                ),
                decided_by=DecidedBy.HARNESS_ONLY_OPTION,
            )

        if self.provider is not None:
            self.model_calls += 1
            decision = self.provider.decide(snapshot)
            if decision is not None:
                self.model_decisions += 1
                return decision

        chosen = fallback_choice(candidates)
        if chosen is None:  # pragma: no cover - candidates is non-empty here
            chosen = HOLD_CANDIDATE
        return MissionIntent(
            candidate=chosen,
            reason=_fallback_reason(self.provider),
            decided_by=DecidedBy.HARNESS_FALLBACK,
        )


def _fallback_reason(provider: StrategicDecisionProvider | None) -> str:
    if provider is None:
        return "no model configured; harness priority order decided"
    if provider.last_error:
        return f"model unavailable ({provider.last_error}); harness priority order decided"
    return "model abstained; harness priority order decided"


__all__ = [
    "HOLD_CANDIDATE",
    "STRATEGIC_SYSTEM_PROMPT",
    "StrategicDecisionProvider",
    "StrategicPlanner",
]
