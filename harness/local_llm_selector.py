"""Constrained OpenAI-compatible selector for the local ROK decision edge.

The deterministic mission selector remains authoritative for all unambiguous
states.  This adapter is called only when the harness has exposed multiple
bounded candidates.  Model output is treated as untrusted data and is mapped
back to one of the already-created ``ActionChoice`` objects; it cannot invent
coordinates, tools, targets, or arguments.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from autorok.llm.boundary import FORBIDDEN_KEY_PARTS
from autorok.llm.transport import (
    LocalLLMConfig,
    build_request,
    exactly_one,
    json_content,
    post,
    raw_content,
    usage_summary,
)
from harness.mission_runtime import ActionChoice, ToolSnapshot


DEFAULT_SYSTEM_PROMPT = (
    "You are the bounded decision edge of an Auto_ROK harness. "
    "Choose only one candidate supplied by the harness. "
    "Do not plan, click, inspect pixels, invent coordinates, or invent actions. "
    "Return JSON only: {\"action_id\": string, \"target_id\": string|null}. "
    "Return {\"action_id\": null} when no candidate is safe."
)


# The scene graph intentionally retains acquisition and execution geometry for
# the harness.  That does not make those fields part of the local model's
# contract: a path, HWND, client rectangle or target bbox is neither useful to
# a bounded selector nor safe to expose as a free-form coordinate plan.  Keep
# this allowlist narrow so new scene facts do not silently expand model input.
_MODEL_SCALAR_FACT_KEYS = frozenset({
    "character_id",
    "character_id_source",
    "resource_type",
    "selected_search_level",
    "selected_search_level_source",
    "march_queue_used",
    "march_queue_capacity",
    "march_queue_source",
    "precondition_evidence_source",
})
_MODEL_MAPPING_FACT_KEYS = {
    "main_view_detector": frozenset({
        "status",
        "state_id",
        "best_distance",
        "second_distance",
        "reason",
        "source",
        "processing_device",
    }),
    "resource_level_control": frozenset({
        "status",
        "control_mode",
        "min_level",
        "max_level",
        "source",
    }),
    "precondition_evidence": None,
    "completion_baseline": frozenset({
        "predicate_id",
        "counter_fact",
        "counter_value",
        "capacity",
        "source_frame_id",
        "source",
        "character_id",
    }),
}
_MODEL_SEQUENCE_FACT_KEYS = frozenset({"ocr_grounding_decisions"})
_MODEL_FEEDBACK_SCALAR_KEYS = frozenset({
    "success",
    "code",
    "state",
    "completed",
    "reobserve_required",
    "message",
})
#: Kept as an alias so the existing call sites read unchanged.  The list
#: itself now lives in autorok.llm.boundary, shared with the strategic tier.
_MODEL_FORBIDDEN_KEY_PARTS = FORBIDDEN_KEY_PARTS


def _safe_json_value(value: Any) -> Any:
    """Copy only JSON-shaped scalar/mapping/sequence values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                continue
            copied = _safe_json_value(item)
            if copied is not _UNSAFE:
                result[key] = copied
        return result
    if isinstance(value, (list, tuple)):
        copied = [_safe_json_value(item) for item in value]
        return [] if any(item is _UNSAFE for item in copied) else copied
    return _UNSAFE


class _UnsafeValue:
    pass


_UNSAFE = _UnsafeValue()


def _allowed_key(key: str) -> bool:
    folded = key.casefold()
    return not any(part in folded for part in _MODEL_FORBIDDEN_KEY_PARTS)


def _model_visible_facts(facts: Mapping[str, Any]) -> dict[str, Any]:
    """Project scene facts into the compact semantic local-LLM contract."""
    result: dict[str, Any] = {}
    for key in _MODEL_SCALAR_FACT_KEYS:
        if key not in facts or not _allowed_key(key):
            continue
        copied = _safe_json_value(facts[key])
        if copied is not _UNSAFE:
            result[key] = copied

    for key, nested_keys in _MODEL_MAPPING_FACT_KEYS.items():
        value = facts.get(key)
        if not isinstance(value, Mapping):
            continue
        if nested_keys is None:
            # Policy evidence is a map of compiled precondition IDs to true;
            # preserve only those semantic IDs and never arbitrary metadata.
            copied = {
                item_key: True
                for item_key, item_value in value.items()
                if isinstance(item_key, str)
                and _allowed_key(item_key)
                and item_value is True
            }
        else:
            copied = {
                item_key: _safe_json_value(value[item_key])
                for item_key in nested_keys
                if item_key in value and _allowed_key(item_key)
                and _safe_json_value(value[item_key]) is not _UNSAFE
            }
        if copied:
            result[key] = copied

    for key in _MODEL_SEQUENCE_FACT_KEYS:
        value = facts.get(key)
        if not isinstance(value, (list, tuple)):
            continue
        copied_items: list[Any] = []
        for item in value:
            if not isinstance(item, Mapping):
                continue
            # OCR grounding decisions are already semantic (target/status),
            # but copy them through the same key filter for future additions.
            safe_item = {
                item_key: _safe_json_value(item_value)
                for item_key, item_value in item.items()
                if isinstance(item_key, str)
                and _allowed_key(item_key)
                and _safe_json_value(item_value) is not _UNSAFE
            }
            if safe_item:
                copied_items.append(safe_item)
        if copied_items:
            result[key] = copied_items
    return result


def _model_feedback(feedback: Mapping[str, Any]) -> dict[str, Any]:
    """Keep feedback useful without forwarding receipt/guard geometry."""
    result: dict[str, Any] = {}
    for key in _MODEL_FEEDBACK_SCALAR_KEYS:
        if key not in feedback or not _allowed_key(key):
            continue
        copied = _safe_json_value(feedback[key])
        if copied is not _UNSAFE:
            result[key] = copied
    facts = feedback.get("facts")
    if isinstance(facts, Mapping):
        projected = _model_visible_facts(facts)
        if projected:
            result["facts"] = projected
    return result


def _model_arguments(arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Expose only bounded, non-geometric action arguments to the model."""
    result: dict[str, Any] = {}
    for key, value in arguments.items():
        if not isinstance(key, str) or not _allowed_key(key):
            continue
        copied = _safe_json_value(value)
        if copied is not _UNSAFE:
            result[key] = copied
    return result


def _missing_resource_intent(facts: Mapping[str, Any], candidates: Sequence[ActionChoice]) -> bool:
    """Require an explicit semantic intent before choosing among resource categories."""
    if isinstance(facts.get("resource_type"), str) and facts["resource_type"].strip():
        return False
    return (
        len(candidates) > 1
        and all(
            choice.action_id == "SELECT_RESOURCE_TYPE"
            and isinstance(choice.target_id, str)
            and choice.target_id.startswith("SEARCH_CATEGORY_")
            for choice in candidates
        )
    )


# The config, the transport and the "resolve to exactly one existing
# candidate" rule now live in autorok.llm.transport, shared with the strategic
# tier.  Re-exported here so every existing import site reads unchanged - the
# same treatment the forbidden-key list got, and for the same reason: a rule
# copied into two files is a rule already wrong in one of them.
__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "LocalLLMConfig",
    "OpenAICompatibleDecisionProvider",
]


class OpenAICompatibleDecisionProvider:
    """One bounded local request, returning only an existing candidate."""

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
        # Benchmark/audit telemetry deliberately keeps only a digest and
        # sizes.  The model-visible request remains reconstructable from the
        # caller's frame-bound snapshot, but raw prompt text is not retained in
        # the provider object or emitted as incidental diagnostic state.
        self.last_request_sha256: str | None = None
        self.last_request_bytes: int | None = None
        self.last_request_elapsed_ms: float | None = None
        # The bounded JSON content returned by the local model is retained for
        # operator-visible shadow/replay evidence.  It never becomes an action
        # authority; the normalized choice below must still match one of the
        # harness-created candidates.
        self.last_model_output: str | None = None

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        opener: Callable[..., Any] = urlopen,
    ) -> "OpenAICompatibleDecisionProvider":
        return cls(LocalLLMConfig.from_mapping(value), opener=opener)

    @property
    def model(self) -> str:
        return self.config.model

    def choose(
        self,
        snapshot: ToolSnapshot,
        candidates: Sequence[ActionChoice],
    ) -> ActionChoice | None:
        self.last_error = None
        self.last_usage = None
        self.last_request_sha256 = None
        self.last_request_bytes = None
        self.last_request_elapsed_ms = None
        self.last_model_output = None
        if not candidates:
            return None
        if _missing_resource_intent(snapshot.facts, candidates):
            self.last_error = "missing semantic resource intent; abstained before local request"
            return None
        candidate_payload = [
            {
                "index": index,
                "action_id": choice.action_id,
                "target_id": choice.target_id,
                "arguments": _model_arguments(choice.arguments),
            }
            for index, choice in enumerate(candidates)
        ]
        user_payload = {
            "mission_id": snapshot.mission_id,
            "task_id": snapshot.task_id,
            "frame_id": snapshot.frame_id,
            "state": snapshot.state,
            "facts": _model_visible_facts(snapshot.facts),
            "last_feedback": _model_feedback(snapshot.last_feedback),
            "candidates": candidate_payload,
        }
        request_body = build_request(
            self.config,
            self.config.prompt_or(DEFAULT_SYSTEM_PROMPT),
            user_payload,
        )
        self.last_request_sha256 = hashlib.sha256(request_body).hexdigest()
        self.last_request_bytes = len(request_body)
        request_started = time.perf_counter()
        try:
            parsed = post(self.config, request_body, opener=self._opener)
            self.last_usage = usage_summary(parsed)
            self.last_model_output = raw_content(parsed)
            choice = json_content(parsed)
            if not isinstance(choice, Mapping):
                raise ValueError("local LLM response must be a JSON object")
            # A deliberate null action is the model's bounded abstention.  It
            # is not an error and still cannot reach the action surface.
            if choice.get("action_id") is None:
                return None
            if not isinstance(choice.get("action_id"), str):
                raise ValueError("local LLM selected no valid action_id")
            target_id = choice.get("target_id")
            if target_id is not None and not isinstance(target_id, str):
                raise ValueError("local LLM target_id must be text or null")
            return exactly_one(
                [
                    candidate
                    for candidate in candidates
                    if candidate.action_id == choice["action_id"]
                    and candidate.target_id == target_id
                ],
                what="action choice",
            )
        except (HTTPError, URLError, OSError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None
        finally:
            self.last_request_elapsed_ms = (time.perf_counter() - request_started) * 1000.0
