"""Transport capacity, pinned to what the client actually showed.

The numbers in test_capacity_is_measured_in_what_arrives come straight off the
Resource Assistance panel on 2026-09-20. They are here so the semantics cannot
quietly invert later: capacity counts what ARRIVES, not what is sent.
"""
from collections import Counter

import pytest

from autorok.mission import ResourceKind
from autorok.mission.transport import (
    LEVEL_25,
    TradingPost,
    TransportError,
    TransportLoad,
    plan_runs,
)


def test_capacity_is_measured_in_what_arrives():
    """The observed panel, reproduced exactly.

    Slider 10,869,565 · tax line -869,565 · capacity 10,000,000/10,000,000 full.
    """
    observed_slider = 10_869_565
    observed_tax_line = 869_565

    assert LEVEL_25.net_capacity == 10_000_000
    assert LEVEL_25.tax_percent == 8

    # What the sender pays for one full run is the slider figure.
    assert LEVEL_25.gross_for_full_load == observed_slider
    # And the deduction shown is the difference.
    assert observed_slider - LEVEL_25.net_capacity == observed_tax_line
    # Reproduced by the client's own integer rule, not by a float multiply.
    assert LEVEL_25.tax_on(observed_slider) == observed_tax_line
    assert int(observed_slider * 0.92) != LEVEL_25.net_capacity
    # Round trip.
    assert LEVEL_25.net_from_gross(observed_slider) == LEVEL_25.net_capacity


def test_run_count_divides_by_net_capacity_not_the_grossed_up_target():
    """The mistake this guards against inflates the plan by about 8 percent."""
    net_order = 14_000_000_000

    assert LEVEL_25.runs_for_net(net_order) == 1_400

    naive = -(-LEVEL_25.gross_for_net(net_order) // LEVEL_25.net_capacity)
    assert naive == 1_522
    assert naive > LEVEL_25.runs_for_net(net_order)


def test_stock_needed_is_grossed_up_even_though_run_count_is_not():
    """Both facts are true at once and they are easy to confuse.

    The exact figure is one unit below what ``ceil(net / 0.92)`` gives, because
    the client's tax is integral. That one unit is why this module does not use
    float arithmetic anywhere.
    """
    net_order = 14_000_000_000
    exact = LEVEL_25.gross_for_net(net_order)

    assert exact == 15_217_391_304
    assert LEVEL_25.net_from_gross(exact) >= net_order
    assert LEVEL_25.net_from_gross(exact - 1) < net_order
    assert LEVEL_25.runs_for_net(net_order) == 1_400


def test_gross_for_net_never_lands_short():
    for net in (1, 999, 10_000, 10_000_000, 3_000_000_000):
        assert LEVEL_25.net_from_gross(LEVEL_25.gross_for_net(net)) >= net


def test_zero_net_needs_nothing():
    assert LEVEL_25.gross_for_net(0) == 0
    assert LEVEL_25.runs_for_net(0) == 0
    assert plan_runs({}) == []


def test_capacity_is_one_pool_shared_by_all_four_resources():
    """Filling it with food alone leaves nothing for the rest."""
    full_of_food = TransportLoad({ResourceKind.FOOD: 10_000_000}, LEVEL_25)
    assert full_of_food.is_full
    assert full_of_food.net_total == LEVEL_25.net_capacity

    with pytest.raises(TransportError):
        TransportLoad(
            {ResourceKind.FOOD: 10_000_000, ResourceKind.WOOD: 1},
            LEVEL_25,
        )


def test_a_mixed_load_shares_the_same_pool():
    load = TransportLoad(
        {
            ResourceKind.FOOD: 4_000_000,
            ResourceKind.WOOD: 3_000_000,
            ResourceKind.STONE: 3_000_000,
        },
        LEVEL_25,
    )
    assert load.is_full
    assert load.gross_total == LEVEL_25.gross_for_full_load


def test_planned_runs_deliver_exactly_what_is_outstanding():
    outstanding = {
        ResourceKind.FOOD: 25_000_000,
        ResourceKind.GOLD: 12_000_000,
        ResourceKind.STONE: 3_000_000,
    }
    runs = plan_runs(outstanding)

    delivered = Counter()
    for run in runs:
        delivered.update(run.amounts)
    assert dict(delivered) == outstanding

    total = sum(outstanding.values())
    assert len(runs) == LEVEL_25.runs_for_net(total)


def test_every_run_but_the_last_is_full():
    runs = plan_runs({ResourceKind.FOOD: 25_000_000})
    assert [run.is_full for run in runs] == [True, True, False]


def test_no_run_can_exceed_capacity():
    runs = plan_runs(
        {ResourceKind.FOOD: 7_000_000, ResourceKind.WOOD: 7_000_000}
    )
    assert all(run.net_total <= LEVEL_25.net_capacity for run in runs)
    assert len(runs) == 2


def test_a_different_trading_post_level_changes_the_arithmetic():
    weaker = TradingPost(level=20, net_capacity=5_000_000, tax_percent=10)
    assert weaker.net_from_gross(weaker.gross_for_full_load) == 5_000_000
    assert weaker.runs_for_net(10_000_000) == 2


def test_gross_for_net_is_the_smallest_that_works():
    for net in (1, 12_345, 10_000_000, 3_000_000_000):
        gross = LEVEL_25.gross_for_net(net)
        assert LEVEL_25.net_from_gross(gross) >= net
        assert LEVEL_25.net_from_gross(gross - 1) < net


@pytest.mark.parametrize("tax", [-1, 100, 150, 8.0])
def test_impossible_tax_rates_are_refused(tax):
    with pytest.raises(TransportError):
        TradingPost(level=25, net_capacity=10_000_000, tax_percent=tax)


def test_negative_amounts_are_refused():
    with pytest.raises(TransportError):
        TransportLoad({ResourceKind.FOOD: -1}, LEVEL_25)
    with pytest.raises(TransportError):
        LEVEL_25.gross_for_net(-1)
