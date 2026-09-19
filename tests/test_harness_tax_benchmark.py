from __future__ import annotations

from scripts.run_harness_tax_benchmark import build_comparison


def _row(resource: str, *, choice: bool = True) -> dict:
    target = f"SEARCH_CATEGORY_{resource}"
    candidates = [
        {"action_id": "SELECT_RESOURCE_TYPE", "target_id": "SEARCH_CATEGORY_FOOD", "arguments": {}},
        {"action_id": "SELECT_RESOURCE_TYPE", "target_id": target, "arguments": {}},
    ]
    return {
        "snapshot": {"candidates": candidates},
        "expected_target_id": target,
        "model": {"choice": {"action_id": "SELECT_RESOURCE_TYPE", "target_id": target} if choice else None, "elapsed_ms": 12.0, "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}},
    }


def test_comparison_keeps_h0_safe_abstention_and_h1_choice() -> None:
    holdout = {"measurement_class": "holdout_multi_frame_real_replay", "batch_id": "test", "distinct_frame_count": 1, "results": [_row("WOOD"), _row("GOLD")]}
    matrix = {"id": "AUTOROK_HARNESS_TAX_V1", "constraints": {"processing_device": "cpu", "model_can_emit_input": False}, "case_source": {"live_input_allowed": False}}
    report = build_comparison(holdout, matrix)
    assert report["status"] == "screening_only"
    h0, h1 = report["variants"]
    assert h0["safe_abstention_rate"] == 1.0
    assert h0["bounded_choice_accuracy"] == 0.0
    assert h1["bounded_choice_accuracy"] == 1.0
    assert report["input_emitted_any"] is False
