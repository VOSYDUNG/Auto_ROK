"""The model-input boundary.

The regression these guard against already happened once: two copies of the
denylist existed, and the one in mission_scheduler was missing "memory",
"point" and "window". The strategic tier would have leaked exactly what the
tactical tier was written to stop.
"""
import pytest

from autorok.llm.boundary import (
    FORBIDDEN_KEY_PARTS,
    forbidden_parts_in,
    is_forbidden_key,
    strip_forbidden,
)


def test_both_decision_tiers_share_one_list_object():
    """Not merely equal - the same object, so they cannot drift again."""
    from harness.local_llm_selector import _MODEL_FORBIDDEN_KEY_PARTS as tactical
    from harness.mission_scheduler import _FORBIDDEN_FACT_KEY_PARTS as strategic

    assert tactical is FORBIDDEN_KEY_PARTS
    assert strategic is FORBIDDEN_KEY_PARTS


def test_the_three_fragments_the_scheduler_used_to_miss_are_present():
    for part in ("memory", "point", "window"):
        assert part in FORBIDDEN_KEY_PARTS


def test_geometry_and_handles_are_all_covered():
    for part in ("bbox", "coord", "hwnd", "pid", "rect", "screen"):
        assert part in FORBIDDEN_KEY_PARTS


@pytest.mark.parametrize(
    "key",
    [
        "bbox",
        "target_bbox",
        "BBox",
        "screen_rect",
        "SCREEN",
        "client_window_rect",
        "hwnd",
        "process_pid",
        "image_path",
        "memory_usage",
        "click_point",
    ],
)
def test_keys_that_must_never_reach_a_model(key):
    assert is_forbidden_key(key)


@pytest.mark.parametrize(
    "key",
    [
        "character_id",
        "resource_type",
        "march_queue_used",
        "march_queue_capacity",
        "selected_search_level",
        "state",
        "buff_remaining_seconds",
    ],
)
def test_the_facts_a_bounded_chooser_actually_needs_are_allowed(key):
    assert not is_forbidden_key(key)


def test_matching_is_case_folded():
    assert is_forbidden_key("TARGET_BBOX")
    assert is_forbidden_key("Screen_Rect")


def test_it_reports_which_fragment_matched():
    assert forbidden_parts_in("client_window_rect") == ("rect", "window")
    assert forbidden_parts_in("character_id") == ()


def test_stripping_removes_forbidden_keys_and_keeps_the_rest():
    facts = {
        "character_id": "char-1",
        "march_queue_used": 2,
        "target_bbox": [1, 2, 3, 4],
        "hwnd": 12345,
    }
    kept = strip_forbidden(facts)
    assert kept == {"character_id": "char-1", "march_queue_used": 2}


def test_stripping_walks_nested_mappings():
    """A forbidden key one level down is just as forbidden."""
    facts = {
        "detector": {
            "status": "ok",
            "best_distance": 0.1,
            "screen_rect": [0, 0, 10, 10],
        },
        "resource_type": "FOOD",
    }
    kept = strip_forbidden(facts)
    assert kept == {
        "detector": {"status": "ok", "best_distance": 0.1},
        "resource_type": "FOOD",
    }


def test_stripping_drops_non_string_keys_rather_than_passing_them_through():
    assert strip_forbidden({1: "x", "state": "CITY_VIEW"}) == {"state": "CITY_VIEW"}


def test_the_list_is_immutable():
    """A denylist that can be appended to at runtime is not a boundary."""
    assert isinstance(FORBIDDEN_KEY_PARTS, tuple)
    with pytest.raises((AttributeError, TypeError)):
        FORBIDDEN_KEY_PARTS.append("new")  # type: ignore[attr-defined]


def test_no_third_copy_of_the_list_exists():
    """Two copies drifted once. A third would drift again."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    pattern = re.compile(r'["\']bbox["\']\s*,')
    offenders = []
    for path in list(root.glob("harness/*.py")) + list(root.glob("autorok/**/*.py")):
        if path.name == "boundary.py":
            continue
        text = path.read_text(encoding="utf-8")
        if pattern.search(text) and "hwnd" in text:
            offenders.append(path.relative_to(root).as_posix())
    assert not offenders, (
        f"a second denylist reappeared in {offenders}; import "
        f"autorok.llm.boundary instead"
    )
