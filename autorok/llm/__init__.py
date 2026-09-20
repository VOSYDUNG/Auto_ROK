"""The 20% decision edge, and the boundary that protects it.

``boundary`` is the single place that decides what may leave the harness
toward a model. ``transport`` is the single place that decides how a model is
called and how its answer is bound back to something the harness built. Both
decision tiers import them; neither keeps its own copy.

``intent`` and ``strategy`` are the strategic tier - the one that had a
producer and no consumer until now.
"""
from autorok.llm.boundary import (
    FORBIDDEN_KEY_PARTS,
    forbidden_parts_in,
    is_forbidden_key,
    strip_forbidden,
)
from autorok.llm.intent import (
    BUFF_LOW_SECONDS,
    FALLBACK_PRIORITY,
    DecidedBy,
    IntentCandidate,
    IntentError,
    IntentKind,
    MissionIntent,
    StrategicSnapshot,
    fallback_choice,
    fleet_summary,
    propose_candidates,
)
from autorok.llm.strategy import (
    STRATEGIC_SYSTEM_PROMPT,
    StrategicDecisionProvider,
    StrategicPlanner,
)
from autorok.llm.transport import LocalLLMConfig, LocalLLMError

__all__ = [
    "BUFF_LOW_SECONDS",
    "FALLBACK_PRIORITY",
    "FORBIDDEN_KEY_PARTS",
    "STRATEGIC_SYSTEM_PROMPT",
    "DecidedBy",
    "IntentCandidate",
    "IntentError",
    "IntentKind",
    "LocalLLMConfig",
    "LocalLLMError",
    "MissionIntent",
    "StrategicDecisionProvider",
    "StrategicPlanner",
    "StrategicSnapshot",
    "fallback_choice",
    "fleet_summary",
    "forbidden_parts_in",
    "is_forbidden_key",
    "propose_candidates",
    "strip_forbidden",
]
