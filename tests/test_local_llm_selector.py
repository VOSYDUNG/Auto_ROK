from __future__ import annotations

import json
import unittest

from harness.local_llm_selector import (
    LocalLLMConfig,
    OpenAICompatibleDecisionProvider,
)
from harness.mission_runtime import ActionChoice, AllowedAction, ToolSnapshot


class _Response:
    def __init__(self, value: dict):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.value).encode("utf-8")


def _snapshot() -> ToolSnapshot:
    return ToolSnapshot(
        mission_id="GATHER_RESOURCE",
        task_id="one-character",
        frame_id="frame-1",
        state="RESOURCE_DETAIL",
        facts={"character_id": "char-1", "resource_type": "WOOD"},
        allowed_actions=(
            AllowedAction("GATHER_RESOURCE_NODE", True, ("RESOURCE_GATHER",)),
            AllowedAction("WAIT"),
        ),
        target_ids=("RESOURCE_GATHER",),
    )


class LocalLLMSelectorTests(unittest.TestCase):
    def test_selects_only_an_existing_candidate(self):
        calls = []

        def opener(request, timeout):
            calls.append((request, timeout))
            return _Response({
                "choices": [{"message": {"content": '{"action_id":"GATHER_RESOURCE_NODE","target_id":"RESOURCE_GATHER"}'}}],
            })

        provider = OpenAICompatibleDecisionProvider(
            LocalLLMConfig("http://127.0.0.1:8080/v1", "gpt-oss-20b"),
            opener=opener,
        )
        candidates = (
            ActionChoice("GATHER_RESOURCE_NODE", "RESOURCE_GATHER"),
            ActionChoice("WAIT"),
        )
        result = provider.choose(_snapshot(), candidates)
        self.assertEqual(candidates[0], result)
        self.assertEqual("http://127.0.0.1:8080/v1/chat/completions", calls[0][0].full_url)
        self.assertEqual(8.0, calls[0][1])
        payload = json.loads(calls[0][0].data.decode("utf-8"))
        self.assertEqual("gpt-oss-20b", payload["model"])
        self.assertNotIn("bbox", payload["messages"][1]["content"])

    def test_invalid_model_choice_is_rejected(self):
        def opener(_request, timeout):
            return _Response({
                "choices": [{"message": {"content": '{"action_id":"INVENTED","target_id":null}'}}],
            })

        provider = OpenAICompatibleDecisionProvider(
            LocalLLMConfig("http://127.0.0.1:8080/v1", "gpt-oss-20b"),
            opener=opener,
        )
        result = provider.choose(_snapshot(), (ActionChoice("WAIT"),))
        self.assertIsNone(result)
        self.assertIn("bounded candidate", provider.last_error or "")

    def test_endpoint_failure_fails_closed(self):
        def opener(_request, timeout):
            raise TimeoutError("slow local server")

        provider = OpenAICompatibleDecisionProvider(
            LocalLLMConfig("http://127.0.0.1:8080/v1", "qwen3-coder-30b"),
            opener=opener,
        )
        self.assertIsNone(provider.choose(_snapshot(), (ActionChoice("WAIT"),)))
        self.assertIn("TimeoutError", provider.last_error or "")

    def test_config_rejects_non_loopback_endpoint(self):
        with self.assertRaises(ValueError):
            LocalLLMConfig.from_mapping({"endpoint": "https://example.invalid/v1", "model": "x"})


if __name__ == "__main__":
    unittest.main()
