"""One local-model call, shared by both decision tiers.

The tactical tier already had all of this inline. Writing the strategic tier
beside it would have produced a second copy of two things that must never
disagree:

  * the loopback-only endpoint check, which is what keeps a "local LLM" local
  * the rule that model output maps back to an ALREADY EXISTING candidate, or
    is refused

The boundary module exists because a denylist living in two files was already
wrong in one of them. The same argument applies here, so the plumbing and the
two safety rules live once and both tiers import them.

What does NOT live here is the system prompt. A prompt is the tier - "choose a
button on this screen" and "choose what the fleet does for the next hour" are
different jobs - so each provider owns its own and this module holds none.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence, TypeVar
from urllib.request import Request

T = TypeVar("T")


class LocalLLMError(ValueError):
    """Raised when a local model call cannot produce a usable answer."""


@dataclass(frozen=True)
class LocalLLMConfig:
    """Where the local model lives and how tightly the call is bounded.

    ``system_prompt`` is ``None`` by default: the provider supplies the prompt
    for its own tier. An operator may still override it through
    ``from_mapping``, which is why the field exists at all.
    """

    endpoint: str
    model: str
    timeout_seconds: float = 8.0
    max_output_tokens: int = 128
    temperature: float = 0.0
    system_prompt: str | None = None

    def prompt_or(self, default: str) -> str:
        """The operator's prompt if they set one, otherwise the tier's own."""
        return self.system_prompt or default

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LocalLLMConfig":
        endpoint = value.get("endpoint")
        model = value.get("model")
        if not isinstance(endpoint, str) or not endpoint.startswith("http://127.0.0.1"):
            raise LocalLLMError("local LLM endpoint must be loopback HTTP")
        if not isinstance(model, str) or not model:
            raise LocalLLMError("local LLM model is required")
        timeout = value.get("timeout_seconds", 8.0)
        max_tokens = value.get("max_output_tokens", 128)
        temperature = value.get("temperature", 0.0)
        if type(timeout) not in (int, float) or not 0 < timeout <= 60:
            raise LocalLLMError("timeout_seconds must be within (0, 60]")
        if type(max_tokens) is not int or not 1 <= max_tokens <= 1024:
            raise LocalLLMError("max_output_tokens must be within 1..1024")
        if type(temperature) not in (int, float) or not 0 <= temperature <= 2:
            raise LocalLLMError("temperature must be within [0, 2]")
        prompt = value.get("system_prompt")
        if prompt is not None and (not isinstance(prompt, str) or not prompt):
            raise LocalLLMError("system_prompt must be non-empty text when given")
        return cls(
            endpoint, model, float(timeout), max_tokens, float(temperature), prompt
        )


def completion_endpoint(endpoint: str) -> str:
    """Normalise an endpoint to the chat-completions path."""
    clean = endpoint.rstrip("/")
    if clean.endswith("/chat/completions"):
        return clean
    if clean.endswith("/v1"):
        return clean + "/chat/completions"
    return clean + "/v1/chat/completions"


def build_request(
    config: LocalLLMConfig, system_prompt: str, payload: Mapping[str, Any]
) -> bytes:
    """Serialise one bounded JSON-mode request.

    ``sort_keys`` on the user payload so the same state produces the same
    bytes, which is what makes the request digest a usable audit key.
    """
    body = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
            },
        ],
        "temperature": config.temperature,
        "max_tokens": config.max_output_tokens,
        "response_format": {"type": "json_object"},
    }
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def post(
    config: LocalLLMConfig, request_body: bytes, *, opener: Callable[..., Any]
) -> Mapping[str, Any]:
    """Send the request and return the parsed response object."""
    request = Request(
        completion_endpoint(config.endpoint),
        data=request_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener(request, timeout=config.timeout_seconds) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    if not isinstance(parsed, Mapping):
        raise LocalLLMError("local LLM response must be a JSON object")
    return parsed


def raw_content(response: Mapping[str, Any]) -> str | None:
    """The model's reply verbatim, for operator-visible replay evidence.

    Kept separate from ``json_content`` because this one must survive a reply
    that fails to parse - that is exactly the reply worth showing someone.
    """
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        return None
    if not isinstance(choices[0], Mapping):
        return None
    message = choices[0].get("message")
    if not isinstance(message, Mapping):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, Mapping):
        return json.dumps(content, ensure_ascii=False, sort_keys=True)
    return None


def json_content(response: Mapping[str, Any]) -> Any:
    """The decoded JSON object the model returned, or an error."""
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise LocalLLMError("local LLM response must contain one choice")
    if not isinstance(choices[0], Mapping):
        raise LocalLLMError("local LLM response must contain one choice")
    message = choices[0].get("message")
    if not isinstance(message, Mapping):
        raise LocalLLMError("local LLM response choice lacks message")
    content = message.get("content")
    if isinstance(content, Mapping):
        return content
    if not isinstance(content, str):
        raise LocalLLMError("local LLM response content must be JSON text")
    text = content.strip()
    if text.startswith("```"):
        text = text.removeprefix("```").removeprefix("json").removesuffix("```").strip()
    return json.loads(text)


#: Provider-reported counters worth keeping. An allowlist rather than a copy
#: of the usage object, so a server that decides to report a file path or a
#: prompt echo under ``usage`` cannot smuggle it into telemetry.
_USAGE_KEYS = frozenset(
    {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "prompt_eval_count",
        "eval_count",
        "tokens_evaluated",
        "tokens_predicted",
    }
)


def usage_summary(response: Mapping[str, Any]) -> dict[str, int | float] | None:
    usage = response.get("usage")
    if not isinstance(usage, Mapping):
        return None
    result: dict[str, int | float] = {}
    for key in _USAGE_KEYS:
        value = usage.get(key)
        if type(value) in (int, float):
            result[key] = value
    return result or None


def exactly_one(matches: Sequence[T], *, what: str) -> T:
    """Return the single match, or refuse.

    This is the rule that keeps a model from acting: whatever it returns is
    resolved against objects the harness already built, and anything that does
    not resolve to exactly one of them is REFUSED rather than repaired.

    Repairing would be the failure - "it almost named a real candidate, so use
    the nearest one" is how a bounded chooser turns into a free-form actor.
    Two matches is equally a refusal: the harness built an ambiguous candidate
    set, and that is a harness bug rather than something to break a tie on.
    """
    if len(matches) != 1:
        raise LocalLLMError(
            f"local LLM {what} resolved to {len(matches)} bounded candidates, "
            "expected exactly one; refusing rather than repairing"
        )
    return matches[0]


__all__ = [
    "LocalLLMConfig",
    "LocalLLMError",
    "build_request",
    "completion_endpoint",
    "exactly_one",
    "json_content",
    "post",
    "raw_content",
    "usage_summary",
]
