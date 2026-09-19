from datetime import datetime, timedelta, timezone

import pytest

from autorok.mission import (
    DeliveryLedger,
    DeliveryPost,
    Order,
    OrderError,
    ResourceKind,
    shortfall_rate,
)

NOW = datetime(2026, 9, 19, 0, 0, tzinfo=timezone.utc)


def _order(**overrides):
    params = dict(
        order_id="war-prep-01",
        net_required={
            ResourceKind.FOOD: 3_000_000_000,
            ResourceKind.WOOD: 3_000_000_000,
            ResourceKind.STONE: 3_000_000_000,
            ResourceKind.GOLD: 5_000_000_000,
        },
        issued_at=NOW,
        horizon=timedelta(days=10),
        tax_rate=0.1,
    )
    params.update(overrides)
    return Order(**params)


def test_gross_required_exceeds_the_quoted_net_figures():
    order = _order()
    gross = order.gross_required
    for kind, net in order.net_required.items():
        assert gross[kind] > net, kind
    # 3b net at 10% tax needs 3.334b gross, rounded up so nothing lands short.
    assert gross[ResourceKind.FOOD] == 3_333_333_334


def test_zero_tax_means_gross_equals_net():
    order = _order(tax_rate=0.0)
    assert order.gross_required == dict(order.net_required)


def test_deadline_and_expiry_follow_the_horizon():
    order = _order()
    assert order.deadline == NOW + timedelta(days=10)
    assert not order.is_expired(NOW + timedelta(days=9))
    assert order.is_expired(NOW + timedelta(days=10, seconds=1))


def test_naive_timestamps_are_rejected():
    with pytest.raises(OrderError):
        _order(issued_at=datetime(2026, 9, 19, 0, 0))
    with pytest.raises(OrderError):
        _order().remaining_seconds(datetime(2026, 9, 19))


@pytest.mark.parametrize("tax_rate", [-0.1, 1.0, 1.5])
def test_impossible_tax_rates_are_rejected(tax_rate):
    with pytest.raises(OrderError):
        _order(tax_rate=tax_rate)


def test_ledger_aggregates_across_the_whole_fleet():
    order = _order(net_required={ResourceKind.GOLD: 1_000}, tax_rate=0.0)
    ledger = DeliveryLedger(order)
    for index in range(4):
        ledger.post(
            DeliveryPost(
                character_id=f"char-{index}",
                kind=ResourceKind.GOLD,
                gross_amount=250,
                posted_at=NOW,
                evidence_ref=f"evidence/{index}.json",
            )
        )
    assert ledger.delivered_gross()[ResourceKind.GOLD] == 1_000
    assert ledger.is_complete()
    assert len(ledger.contribution_by_character()) == 4


def test_order_is_not_complete_until_the_net_figure_is_met():
    order = _order(net_required={ResourceKind.GOLD: 1_000}, tax_rate=0.5)
    ledger = DeliveryLedger(order)
    # Sending exactly the net amount leaves half of it with the tax.
    ledger.post(
        DeliveryPost("char-0", ResourceKind.GOLD, 1_000, NOW, "evidence/a.json")
    )
    assert not ledger.is_complete()
    assert ledger.delivered_net()[ResourceKind.GOLD] == 500
    assert ledger.outstanding_net()[ResourceKind.GOLD] == 500
    assert ledger.outstanding_gross()[ResourceKind.GOLD] == 1_000

    ledger.post(
        DeliveryPost("char-1", ResourceKind.GOLD, 1_000, NOW, "evidence/b.json")
    )
    assert ledger.is_complete()


def test_a_delivery_without_evidence_is_refused():
    with pytest.raises(OrderError):
        DeliveryPost("char-0", ResourceKind.GOLD, 10, NOW, "")


def test_non_positive_delivery_amounts_are_refused():
    for amount in (0, -5):
        with pytest.raises(OrderError):
            DeliveryPost("char-0", ResourceKind.GOLD, amount, NOW, "evidence/a.json")


def test_posting_a_resource_outside_the_order_is_refused():
    ledger = DeliveryLedger(_order(net_required={ResourceKind.GOLD: 10}))
    with pytest.raises(OrderError):
        ledger.post(
            DeliveryPost("char-0", ResourceKind.FOOD, 10, NOW, "evidence/a.json")
        )


def test_shortfall_rate_reports_pace_and_flags_a_missed_deadline():
    order = _order(net_required={ResourceKind.GOLD: 1_000}, tax_rate=0.0)
    ledger = DeliveryLedger(order)
    assert shortfall_rate(ledger, NOW) > 0

    ledger.post(
        DeliveryPost("char-0", ResourceKind.GOLD, 1_000, NOW, "evidence/a.json")
    )
    assert shortfall_rate(ledger, NOW) == 0.0

    stalled = DeliveryLedger(order)
    assert shortfall_rate(stalled, NOW + timedelta(days=11)) == float("inf")
