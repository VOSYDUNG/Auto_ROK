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
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from autorok.llm.boundary import FORBIDDEN_KEY_PARTS
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


@dataclass(frozen=True)
class LocalLLMConfig:
    endpoint: str
    model: str
    timeout_seconds: float = 8.0
    max_output_tokens: int = 128
    temperature: float = 0.0
    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LocalLLMConfig":
        endpoint = value.get("endpoint")
        model = value.get("model")
        if not isinstance(endpoint, str) or not endpoint.startswith("http://127.0.0.1"):
            raise ValueError("local LLM endpoint must be loopback HTTP")
        if not isinstance(model, str) or not model:
            raise ValueError("local LLM model is required")
        timeout = value.get("timeout_seconds", 8.0)
        max_tokens = value.get("max_output_tokens", 128)
        temperature = value.get("temperature", 0.0)
        if type(timeout) not in (int, float) or not 0 < timeout <= 60:
            raise ValueError("timeout_seconds must be within (0, 60]")
        if type(max_tokens) is not int or not 1 <= max_tokens <= 1024:
            raise ValueError("max_output_tokens must be within 1..1024")
        if type(temperature) not in (int, float) or not 0 <= temperature <= 2:
            raise ValueError("temperature must be within [0, 2]")
        prompt = value.get("system_prompt", DEFAULT_SYSTEM_PROMPT)
        if not isinstance(prompt, str) or not prompt:
            raise ValueError("system_prompt must be non-empty text")
        return cls(endpoint, model, float(timeout), max_tokens, float(temperature), prompt)


def _completion_endpoint(endpoint: str) -> str:
    clean = endpoint.rstrip("/")
    if clean.endswith("/chat/completions"):
        return clean
    if clean.endswith("/v1"):
        return clean + "/chat/completions"
    return clean + "/v1/chat/completions"


def _json_content(response: Mapping[str, Any]) -> Any:
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], Mapping):
        raise ValueError("local LLM response must contain one choice")
    message = choices[0].get("message")
    if not isinstance(message, Mapping):
        raise ValueError("local LLM response choice lacks message")
    content = message.get("content")
    if isinstance(content, Mapping):
        return content
    if not isinstance(content, str):
        raise ValueError("local LLM response content must be JSON text")
    text = content.strip()
    if text.startswith("```"):
        text = text.removeprefix("```").removeprefix("json").removesuffix("```").strip()
    return json.loads(text)


def _usage_summary(response: Mapping[str, Any]) -> dict[str, int | float] | None:
    """Keep only provider-reported numeric token counters for telemetry."""
    usage = response.get("usage")
    if not isinstance(usage, Mapping):
        return None
    allowed = {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "prompt_eval_count",
        "eval_count",
        "tokens_evaluated",
        "tokens_predicted",
    }
    result: dict[str, int | float] = {}
    for key in allowed:
        value = usage.get(key)
        if type(value) in (int, float):
            result[key] = value
    return result or None


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
        body = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": self.config.system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, sort_keys=True)},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        request_body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.last_request_sha256 = hashlib.sha256(request_body).hexdigest()
        self.last_request_bytes = len(request_body)
        request = Request(
            _completion_endpoint(self.config.endpoint),
            data=request_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        request_started = time.perf_counter()
        try:
            with self._opener(request, timeout=self.config.timeout_seconds) as response:
                parsed = json.loads(response.read().decode("utf-8"))
            if not isinstance(parsed, Mapping):
                raise ValueError("local LLM response must be a JSON object")
            self.last_usage = _usage_summary(parsed)
            raw_choices = parsed.get("choices")
            if isinstance(raw_choices, list) and len(raw_choices) == 1 and isinstance(raw_choices[0], Mapping):
                raw_message = raw_choices[0].get("message")
                if isinstance(raw_message, Mapping):
                    raw_content = raw_message.get("content")
                    if isinstance(raw_content, str):
                        self.last_model_output = raw_content
                    elif isinstance(raw_content, Mapping):
                        self.last_model_output = json.dumps(raw_content, ensure_ascii=False, sort_keys=True)
            choice = _json_content(parsed)
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
            matches = [
                candidate
                for candidate in candidates
                if candidate.action_id == choice["action_id"] and candidate.target_id == target_id
            ]
            if len(matches) != 1:
                raise ValueError("local LLM choice is not one unique bounded candidate")
            return matches[0]
        except (HTTPError, URLError, OSError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None
        finally:
            self.last_request_elapsed_ms = (time.perf_counter() - request_started) * 1000.0
