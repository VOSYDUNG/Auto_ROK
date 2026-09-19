from __future__ import annotations

import json
import hashlib
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
        facts={
            "character_id": "char-1",
            "character_id_source": "configured_single_character_scope",
            "selected_search_level": 4,
            "resource_type": "WOOD",
            "raw_text": "untrusted OCR/chat text",
            "image_path": "C:\\secret\\current.png",
            "client_screen_rect": [10, 20, 1376, 788],
            "window": {"hwnd": 1234, "pid": 99, "title": "Rise of Kingdoms"},
            "main_view_detector": {
                "status": "matched",
                "state_id": "CITY_VIEW",
                "best_distance": 0.04,
                "roi": {"rect": [109, 61, 1148, 614]},
            },
            "resource_level_control": {
                "status": "grounded",
                "min_level": 1,
                "max_level": 5,
                "track_bbox_client": [100, 200, 500, 220],
            },
        },
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
        self.assertEqual(
            '{"action_id":"GATHER_RESOURCE_NODE","target_id":"RESOURCE_GATHER"}',
            provider.last_model_output,
        )
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

    def test_explicit_null_action_is_a_clean_abstention(self):
        def opener(_request, timeout):
            return _Response({
                "choices": [{"message": {"content": '{"action_id":null,"target_id":null}'}}],
            })

        provider = OpenAICompatibleDecisionProvider(
            LocalLLMConfig("http://127.0.0.1:8080/v1", "gpt-oss-20b"),
            opener=opener,
        )
        self.assertIsNone(provider.choose(_snapshot(), (ActionChoice("WAIT"),)))
        self.assertIsNone(provider.last_error)

    def test_resource_category_choice_requires_explicit_intent(self):
        calls = []

        def opener(request, timeout):
            calls.append(request)
            return _Response({
                "choices": [{"message": {"content": '{"action_id":"SELECT_RESOURCE_TYPE","target_id":"SEARCH_CATEGORY_FOOD"}'}}],
            })

        provider = OpenAICompatibleDecisionProvider(
            LocalLLMConfig("http://127.0.0.1:8080/v1", "gpt-oss-20b"),
            opener=opener,
        )
        snapshot = _snapshot()
        facts = dict(snapshot.facts)
        facts.pop("resource_type")
        snapshot = ToolSnapshot(
            snapshot.mission_id, snapshot.task_id, snapshot.frame_id, snapshot.state,
            facts, snapshot.allowed_actions, snapshot.target_ids,
        )
        candidates = tuple(
            ActionChoice("SELECT_RESOURCE_TYPE", target)
            for target in (
                "SEARCH_CATEGORY_FOOD",
                "SEARCH_CATEGORY_WOOD",
                "SEARCH_CATEGORY_STONE",
                "SEARCH_CATEGORY_GOLD",
            )
        )
        self.assertIsNone(provider.choose(snapshot, candidates))
        self.assertEqual([], calls)
        self.assertIn("missing semantic resource intent", provider.last_error or "")

    def test_model_payload_is_semantic_and_excludes_capture_geometry(self):
        calls = []

        def opener(request, timeout):
            calls.append(request)
            return _Response({
                "choices": [{"message": {"content": '{"action_id":"WAIT","target_id":null}'}}],
            })

        provider = OpenAICompatibleDecisionProvider(
            LocalLLMConfig("http://127.0.0.1:8080/v1", "gpt-oss-20b"),
            opener=opener,
        )
        result = provider.choose(
            _snapshot(),
            (ActionChoice("WAIT", arguments={"resource_level": 4}),),
        )
        self.assertEqual(ActionChoice("WAIT", arguments={"resource_level": 4}), result)
        payload = json.loads(calls[0].data.decode("utf-8"))
        self.assertEqual(len(calls[0].data), provider.last_request_bytes)
        self.assertEqual(hashlib.sha256(calls[0].data).hexdigest(), provider.last_request_sha256)
        self.assertIsNotNone(provider.last_request_elapsed_ms)
        user = json.loads(payload["messages"][1]["content"])
        facts = user["facts"]
        self.assertEqual("char-1", facts["character_id"])
        self.assertEqual("WOOD", facts["resource_type"])
        self.assertEqual(4, facts["selected_search_level"])
        for forbidden in (
            "raw_text",
            "image_path",
            "client_screen_rect",
            "window",
        ):
            self.assertNotIn(forbidden, facts)
        self.assertNotIn("roi", facts["main_view_detector"])
        self.assertNotIn("track_bbox_client", facts["resource_level_control"])
        self.assertEqual({"resource_level": 4}, user["candidates"][0]["arguments"])

    def test_provider_keeps_only_numeric_usage_telemetry(self):
        def opener(_request, timeout):
            return _Response({
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "total_tokens": 12,
                    "prompt": "do not retain raw text",
                },
                "choices": [{"message": {"content": '{"action_id":"WAIT","target_id":null}'}}],
            })

        provider = OpenAICompatibleDecisionProvider(
            LocalLLMConfig("http://127.0.0.1:8080/v1", "gpt-oss-20b"),
            opener=opener,
        )
        self.assertEqual(ActionChoice("WAIT"), provider.choose(_snapshot(), (ActionChoice("WAIT"),)))
        self.assertEqual(
            {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            provider.last_usage,
        )

    def test_endpoint_failure_fails_closed(self):
        def opener(_request, timeout):
            raise TimeoutError("slow local server")

        provider = OpenAICompatibleDecisionProvider(
            LocalLLMConfig("http://127.0.0.1:8080/v1", "qwen3-coder-30b"),
            opener=opener,
        )
        self.assertIsNone(provider.choose(_snapshot(), (ActionChoice("WAIT"),)))
        self.assertIn("TimeoutError", provider.last_error or "")

    def test_empty_model_content_fails_closed_and_keeps_usage(self):
        def opener(_request, timeout):
            return _Response({
                "usage": {"prompt_tokens": 706, "completion_tokens": 256, "total_tokens": 962},
                "choices": [{"message": {"content": ""}}],
            })

        provider = OpenAICompatibleDecisionProvider(
            LocalLLMConfig("http://127.0.0.1:8080/v1", "gpt-oss-20b"),
            opener=opener,
        )
        self.assertIsNone(provider.choose(_snapshot(), (ActionChoice("WAIT"),)))
        self.assertIn("JSONDecodeError", provider.last_error or "")
        self.assertEqual(
            {"prompt_tokens": 706, "completion_tokens": 256, "total_tokens": 962},
            provider.last_usage,
        )

    def test_config_rejects_non_loopback_endpoint(self):
        with self.assertRaises(ValueError):
            LocalLLMConfig.from_mapping({"endpoint": "https://example.invalid/v1", "model": "x"})


if __name__ == "__main__":
    unittest.main()
