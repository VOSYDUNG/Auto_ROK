"""Constrained OpenAI-compatible selector for the local ROK decision edge.

The deterministic mission selector remains authoritative for all unambiguous
states.  This adapter is called only when the harness has exposed multiple
bounded candidates.  Model output is treated as untrusted data and is mapped
back to one of the already-created ``ActionChoice`` objects; it cannot invent
coordinates, tools, targets, or arguments.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from harness.mission_runtime import ActionChoice, ToolSnapshot


DEFAULT_SYSTEM_PROMPT = (
    "You are the bounded decision edge of an Auto_ROK harness. "
    "Choose only one candidate supplied by the harness. "
    "Do not plan, click, inspect pixels, invent coordinates, or invent actions. "
    "Return JSON only: {\"action_id\": string, \"target_id\": string|null}. "
    "Return {\"action_id\": null} when no candidate is safe."
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
        if not candidates:
            return None
        candidate_payload = [
            {
                "index": index,
                "action_id": choice.action_id,
                "target_id": choice.target_id,
                "arguments": dict(choice.arguments),
            }
            for index, choice in enumerate(candidates)
        ]
        user_payload = {
            "mission_id": snapshot.mission_id,
            "task_id": snapshot.task_id,
            "frame_id": snapshot.frame_id,
            "state": snapshot.state,
            "facts": dict(snapshot.facts),
            "last_feedback": dict(snapshot.last_feedback),
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
        request = Request(
            _completion_endpoint(self.config.endpoint),
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.config.timeout_seconds) as response:
                parsed = json.loads(response.read().decode("utf-8"))
            choice = _json_content(parsed)
            if not isinstance(choice, Mapping) or not isinstance(choice.get("action_id"), str):
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
