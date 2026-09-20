"""The degradation ladder.

The invariant these protect: a blocked action demotes the loop, it never stops
it. The legacy Mouse_key.py froze on every exception because it had no way
down from its single plan.
"""
from datetime import datetime, timedelta, timezone

import pytest

from autorok.mission.ladder import (
    PURPOSE,
    Ladder,
    LadderError,
    Rung,
    Transition,
    is_persistently_degraded,
    summarise,
)

NOW = datetime(2026, 9, 20, 7, 0, tzinfo=timezone.utc)


def test_the_rungs_run_strongest_to_weakest():
    assert list(Rung) == [
        Rung.ORDER_WORK,
        Rung.DEFAULT_FARM,
        Rung.SCARCITY_FILL,
        Rung.DAILY_CITIZEN,
        Rung.OBSERVE_ONLY,
    ]
    assert Rung.ORDER_WORK < Rung.OBSERVE_ONLY


def test_every_rung_states_what_it_is_for():
    for rung in Rung:
        assert PURPOSE[rung].strip()


def test_only_the_floor_refuses_to_emit_input():
    assert not Rung.OBSERVE_ONLY.emits_input
    for rung in Rung:
        if rung is not Rung.OBSERVE_ONLY:
            assert rung.emits_input, rung


def test_a_fresh_ladder_starts_at_the_top():
    ladder = Ladder()
    assert ladder.current is Rung.ORDER_WORK
    assert ladder.depth == 0
    assert ladder.history == ()


def test_demotion_moves_exactly_one_rung():
    """Skipping would hide which goal was tried and why it failed."""
    ladder = Ladder()
    step = ladder.demote("no node at the preferred level", at=NOW)
    assert step.previous is Rung.ORDER_WORK
    assert step.current is Rung.DEFAULT_FARM
    assert ladder.depth == 1


def test_it_walks_all_the_way_down_one_step_at_a_time():
    ladder = Ladder()
    seen = [ladder.current]
    for index in range(4):
        ladder.demote(f"blocked {index}", at=NOW)
        seen.append(ladder.current)
    assert seen == list(Rung)


def test_there_is_never_a_state_without_a_goal():
    """LAD-009. The floor is a goal, not an absence of one."""
    ladder = Ladder()
    for index in range(20):
        ladder.demote(f"blocked {index}", at=NOW)
        assert ladder.current is not None
        assert isinstance(ladder.current, Rung)
    assert ladder.current is Rung.OBSERVE_ONLY
    assert ladder.at_floor


def test_demoting_at_the_floor_records_the_attempt_and_stays():
    ladder = Ladder(start=Rung.OBSERVE_ONLY)
    step = ladder.demote("still blocked", at=NOW)
    assert step.previous is Rung.OBSERVE_ONLY
    assert step.current is Rung.OBSERVE_ONLY
    assert not step.is_demotion
    assert len(ladder.history) == 1, "the attempt is still recorded"


def test_a_transition_without_a_reason_is_refused():
    """LAD-008. An unexplained demotion cannot be reviewed later."""
    for blank in ("", "   ", "\n"):
        with pytest.raises(LadderError, match="reason"):
            Transition(Rung.ORDER_WORK, Rung.DEFAULT_FARM, blank, NOW)


def test_a_naive_timestamp_is_refused():
    with pytest.raises(LadderError, match="timezone"):
        Transition(Rung.ORDER_WORK, Rung.DEFAULT_FARM, "why", datetime(2026, 9, 20))


def test_promotion_also_moves_one_rung_at_a_time():
    """Jumping back to the top assumes every blocker cleared at once."""
    ladder = Ladder(start=Rung.DAILY_CITIZEN)
    ladder.promote("nodes are available again", at=NOW)
    assert ladder.current is Rung.SCARCITY_FILL
    ladder.promote("preferred level found", at=NOW)
    assert ladder.current is Rung.DEFAULT_FARM


def test_promoting_at_the_top_stays_at_the_top():
    ladder = Ladder()
    ladder.promote("nothing to recover from", at=NOW)
    assert ladder.current is Rung.ORDER_WORK


def test_reset_returns_to_the_top_for_a_new_occurrence():
    ladder = Ladder(start=Rung.OBSERVE_ONLY)
    ladder.reset("new occurrence", at=NOW)
    assert ladder.current is Rung.ORDER_WORK
    assert ladder.history[-1].reason == "new occurrence"


def test_every_step_is_kept_in_order():
    ladder = Ladder()
    ladder.demote("first", at=NOW)
    ladder.demote("second", at=NOW + timedelta(minutes=1))
    ladder.promote("recovered", at=NOW + timedelta(minutes=2))
    assert [item.reason for item in ladder.history] == ["first", "second", "recovered"]
    assert [item.reason for item in ladder] == ["first", "second", "recovered"]


def test_time_below_top_is_measured_from_leaving_the_top():
    ladder = Ladder()
    assert ladder.time_below_top(NOW) == timedelta(0)

    ladder.demote("scarce", at=NOW)
    ladder.demote("still scarce", at=NOW + timedelta(minutes=10))
    assert ladder.time_below_top(NOW + timedelta(hours=2)) == timedelta(hours=2)


def test_returning_to_the_top_clears_the_elapsed_time():
    ladder = Ladder()
    ladder.demote("scarce", at=NOW)
    ladder.reset("recovered", at=NOW + timedelta(hours=1))
    assert ladder.time_below_top(NOW + timedelta(hours=5)) == timedelta(0)


def test_a_brief_dip_is_not_reported_but_a_long_one_is():
    """One scarce search is ordinary; an hour of it says something."""
    ladder = Ladder()
    ladder.demote("no node", at=NOW)

    assert not is_persistently_degraded(ladder, NOW + timedelta(minutes=5))
    assert is_persistently_degraded(ladder, NOW + timedelta(hours=2))


def test_demotions_can_be_counted_over_a_window():
    ladder = Ladder()
    ladder.demote("a", at=NOW)
    ladder.promote("b", at=NOW + timedelta(minutes=1))
    ladder.demote("c", at=NOW + timedelta(minutes=2))
    recent = ladder.demotions_since(NOW + timedelta(minutes=1))
    assert [item.reason for item in recent] == ["c"]


def test_the_summary_is_packet_sized_and_carries_no_geometry():
    from autorok.llm.boundary import is_forbidden_key

    ladder = Ladder()
    ladder.demote("no node at the preferred level", at=NOW)
    packet = summarise(ladder, NOW + timedelta(minutes=30))

    assert packet["rung"] == "DEFAULT_FARM"
    assert packet["depth"] == 1
    assert packet["emits_input"] is True
    assert packet["seconds_below_top"] == 1800
    assert packet["last_reason"] == "no node at the preferred level"
    for key in packet:
        assert not is_forbidden_key(key), key
