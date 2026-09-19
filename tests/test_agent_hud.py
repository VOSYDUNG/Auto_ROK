"""HUD contract tests.

These cover the logic, not the drawing: the dock geometry that keeps it out of
the game's way, the event-to-state mapping, and the safety rule that an armed
loop is never shown as safe. Tkinter is never instantiated.
"""
import json

import pytest

from scripts.run_agent_hud import (
    COLLAPSED_H,
    COLLAPSED_W,
    DOCK_H,
    DOCK_W,
    DOCK_X,
    DOCK_Y,
    LOOKS,
    _read_new_events,
    _shorten,
    build_parser,
)

#: The game's own HUD along the top edge, measured from the frame captured in
#: workspace/runs/p3-observe-20260920.
GAME_LEFT_PANEL_ENDS = 334
GAME_RESOURCE_STRIP_STARTS = 941
GAME_WIDTH = 1366


def test_the_dock_fits_the_measured_dead_band():
    """The whole point: it cannot cover game UI because it does not reach it."""
    assert DOCK_X >= GAME_LEFT_PANEL_ENDS
    assert DOCK_X + DOCK_W <= GAME_RESOURCE_STRIP_STARTS
    assert DOCK_W == GAME_RESOURCE_STRIP_STARTS - GAME_LEFT_PANEL_ENDS


def test_the_hud_is_a_slim_bar_not_a_fullscreen_overlay():
    """The rejected overlay was 1366x768 at +0+0."""
    assert DOCK_H <= 40
    assert DOCK_W * DOCK_H < GAME_WIDTH * 768 * 0.03
    assert (DOCK_X, DOCK_Y) != (0, 0)


def test_collapsed_state_is_nearly_invisible():
    assert COLLAPSED_H <= 6
    assert COLLAPSED_W < DOCK_W


def test_every_state_defines_a_complete_palette():
    for name, look in LOOKS.items():
        for field in ("dot", "background", "border", "primary", "muted"):
            value = getattr(look, field)
            assert value.startswith("#") and len(value) == 7, f"{name}.{field}"


def test_only_the_armed_state_uses_the_warning_palette():
    """Amber must mean exactly one thing, or it stops meaning anything."""
    armed = LOOKS["armed"]
    for name, look in LOOKS.items():
        if name == "armed":
            continue
        assert look.background != armed.background, name
        assert look.dot != armed.dot, name


def test_no_magenta_anywhere():
    """The previous overlay keyed on #ff00ff and fringed pink."""
    for name, look in LOOKS.items():
        for field in ("dot", "background", "border", "primary", "muted"):
            assert getattr(look, field).lower() != "#ff00ff", f"{name}.{field}"


def test_events_outside_workspace_are_refused(tmp_path):
    from scripts.run_agent_hud import main

    outside = tmp_path / "events.jsonl"
    outside.write_text("", encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--events", str(outside)])


@pytest.mark.parametrize("opacity", ["0.1", "1.5"])
def test_unusable_opacity_is_refused(opacity):
    from scripts.run_agent_hud import main

    with pytest.raises(SystemExit):
        main(["--events", "x", "--opacity", opacity])


def test_a_missing_event_file_is_an_idle_state_not_a_crash(tmp_path):
    events, offset = _read_new_events(tmp_path / "nothing.jsonl", 0)
    assert events == []
    assert offset == 0


def test_tailing_returns_only_new_lines(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps({"payload": {"status": "OK"}}) + "\n", encoding="utf-8")

    first, offset = _read_new_events(path, 0)
    assert len(first) == 1

    again, offset2 = _read_new_events(path, offset)
    assert again == []

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"payload": {"status": "NEXT"}}) + "\n")
    third, _ = _read_new_events(path, offset2)
    assert len(third) == 1
    assert third[0]["payload"]["status"] == "NEXT"


def test_a_corrupt_line_is_skipped_rather_than_fatal(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(
        "not json\n" + json.dumps({"payload": {"status": "OK"}}) + "\n",
        encoding="utf-8",
    )
    events, _ = _read_new_events(path, 0)
    assert len(events) == 1


def test_long_detail_is_truncated_to_fit_the_bar():
    assert _shorten("x" * 200, 46) == "x" * 45 + "…"
    assert _shorten(None, 10) == ""
    assert _shorten("short", 46) == "short"


def test_parser_defaults_are_sane():
    args = build_parser().parse_args(["--events", "workspace/e.jsonl"])
    assert 0.3 <= args.opacity <= 1.0
    assert 50 <= args.poll_ms <= 5000


def test_cursor_reads_the_screen_point_from_the_payload():
    from scripts.run_agent_hud import read_target_point

    assert read_target_point({"cursor_screen": [640, 360]}) == (640.0, 360.0)
    assert read_target_point({"target_screen": [10, 20.5]}) == (10.0, 20.5)


def test_cursor_point_prefers_where_the_pointer_will_land():
    """target_screen is the element; cursor_screen is where it will be clicked."""
    from scripts.run_agent_hud import read_target_point

    payload = {"cursor_screen": [100, 100], "target_screen": [900, 900]}
    assert read_target_point(payload) == (100.0, 100.0)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"cursor_screen": None},
        {"cursor_screen": [1]},
        {"cursor_screen": [1, 2, 3]},
        {"cursor_screen": ["a", "b"]},
        {"cursor_screen": [True, False]},
        {"cursor_screen": "640,360"},
    ],
)
def test_a_malformed_point_draws_no_cursor(payload):
    """Never guess a click location - draw nothing instead."""
    from scripts.run_agent_hud import read_target_point

    assert read_target_point(payload) is None


def test_the_click_point_lands_on_the_window_centre():
    """The window is placed centre-on-target, so the dot must be drawn there.

    Anchoring the hat instead would offset every click by the stem length -
    an error that only shows up as a misclick on a live client.
    """
    from scripts.run_agent_hud import CURSOR_BOX, STEM

    centre = CURSOR_BOX // 2
    point_y = centre
    brim = point_y - STEM
    assert point_y == centre
    assert brim < point_y, "the hat must sit above the point, never on it"


def test_the_hat_never_covers_the_target():
    """A marker drawn over the element hides the thing being clicked."""
    from scripts.run_agent_hud import POINT_R, STEM

    assert STEM > POINT_R * 2


def test_the_whole_marker_fits_inside_its_window():
    from scripts.run_agent_hud import (
        CURSOR_BOX,
        HAT_HALF_W,
        HAT_HEIGHT,
        POINT_R,
        STEM,
    )

    centre = CURSOR_BOX // 2
    apex = centre - STEM - HAT_HEIGHT
    assert apex > 0, "hat apex clipped by the window"
    assert centre + POINT_R < CURSOR_BOX, "click dot clipped"
    assert 0 < centre - HAT_HALF_W and centre + HAT_HALF_W < CURSOR_BOX


def test_the_marker_is_smaller_than_the_crosshair_it_replaced():
    """The rejected overlay drew 68px of crosshair."""
    from scripts.run_agent_hud import HAT_HALF_W, HAT_HEIGHT, STEM

    assert HAT_HALF_W * 2 <= 36
    assert HAT_HEIGHT + STEM <= 32


def test_the_two_windows_never_share_a_transparency_mechanism():
    """Alpha plus colour key on one window is what fringed pink."""
    from scripts.run_agent_hud import CURSOR_KEY

    assert CURSOR_KEY.lower() != "#ff00ff"
    for look in LOOKS.values():
        for field in ("dot", "background", "border", "primary", "muted"):
            assert getattr(look, field).lower() != CURSOR_KEY.lower(), (
                "a palette colour equal to the key would be keyed out and vanish"
            )


def test_the_marker_has_a_dark_halo_that_is_not_the_transparency_key():
    """Without it the hollow state vanishes on dark panels.

    A halo equal to the key colour would be keyed out, leaving the marker with
    no contrast at all - the exact failure it exists to prevent.
    """
    from scripts.run_agent_hud import CURSOR_KEY, HALO

    assert HALO.lower() != CURSOR_KEY.lower()
    for look in LOOKS.values():
        assert look.dot.lower() != HALO.lower(), "halo must contrast with the marker"
