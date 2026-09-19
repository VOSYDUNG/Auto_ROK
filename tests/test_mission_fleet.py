from datetime import datetime, timedelta, timezone

import pytest

from autorok.mission import (
    MARCHES_PER_CHARACTER,
    OPERATOR_BASELINE_STRONG,
    OPERATOR_BASELINE_WEAK,
    Account,
    Character,
    CycleEstimate,
    CycleSource,
    Fleet,
    FleetError,
    March,
    ResourceKind,
)

NOW = datetime(2026, 9, 19, 0, 0, tzinfo=timezone.utc)


def _character(char_id="char-1", account_id="acc-1", cycle=OPERATOR_BASELINE_STRONG):
    return Character(character_id=char_id, account_id=account_id, cycle=cycle)


def _fleet(accounts=2, per_account=4):
    built = []
    for a in range(accounts):
        account_id = f"acc-{a}"
        chars = [
            _character(f"{account_id}-char-{c}", account_id)
            for c in range(per_account)
        ]
        built.append(Account(account_id=account_id, characters=chars))
    return Fleet(built)


def _march(slot, minutes, kind=ResourceKind.GOLD, at=NOW):
    return March(
        slot=slot,
        kind=kind,
        dispatched_at=at,
        expected_home_at=at + timedelta(minutes=minutes),
    )


def test_operator_baselines_are_labelled_as_estimates_not_measurements():
    for baseline in (OPERATOR_BASELINE_STRONG, OPERATOR_BASELINE_WEAK):
        assert baseline.source is CycleSource.OPERATOR_BASELINE
        assert baseline.assumes_gather_buff is True
    assert OPERATOR_BASELINE_STRONG.duration < OPERATOR_BASELINE_WEAK.duration


def test_a_measured_cycle_must_carry_at_least_one_sample():
    with pytest.raises(FleetError):
        CycleEstimate(timedelta(hours=2), CycleSource.MEASURED, sample_count=0)
    measured = CycleEstimate(timedelta(hours=2), CycleSource.MEASURED, sample_count=3)
    assert measured.source is CycleSource.MEASURED


def test_a_character_holds_exactly_five_marches():
    character = _character()
    for slot in range(MARCHES_PER_CHARACTER):
        character.dispatch(_march(slot, 60 + slot))
    assert character.is_queue_full
    with pytest.raises(FleetError):
        character.dispatch(_march(0, 60))


def test_a_slot_cannot_be_double_booked():
    character = _character()
    character.dispatch(_march(2, 60))
    with pytest.raises(FleetError):
        character.dispatch(_march(2, 90))


def test_the_batch_is_amortised_against_the_slowest_march():
    character = _character()
    character.dispatch(_march(0, 30))
    character.dispatch(_march(1, 200))
    character.dispatch(_march(2, 75))
    assert character.batch_home_at() == NOW + timedelta(minutes=200)
    # The idle tail is the gap the rotation has to absorb.
    assert character.idle_tail() == timedelta(minutes=170)


def test_a_character_is_re_entered_only_when_every_march_is_home():
    character = _character()
    character.dispatch(_march(0, 30))
    character.dispatch(_march(1, 200))

    assert not character.is_eligible(NOW + timedelta(minutes=100))
    assert not character.is_eligible(NOW + timedelta(minutes=199))
    assert character.is_eligible(NOW + timedelta(minutes=200))


def test_an_idle_character_is_always_eligible():
    assert _character().is_eligible(NOW)
    assert _character().batch_home_at() is None


def test_returned_marches_are_collected_and_leave_the_queue():
    character = _character()
    character.dispatch(_march(0, 30))
    character.dispatch(_march(1, 200))

    returned = character.collect_returned(NOW + timedelta(minutes=60))
    assert len(returned) == 1
    assert character.free_slots == MARCHES_PER_CHARACTER - 1


def test_fleet_geometry_matches_the_operator_two_by_four_layout():
    fleet = _fleet()
    assert len(fleet.accounts) == 2
    assert len(fleet.characters) == 8
    assert fleet.total_slots == 40


def test_queue_occupancy_is_measured_across_the_fleet_not_one_character():
    fleet = _fleet()
    assert fleet.queue_occupancy() == 0.0

    first = fleet.characters[0]
    for slot in range(MARCHES_PER_CHARACTER):
        first.dispatch(_march(slot, 120 + slot))

    # One saturated character is still only an eighth of the fleet: a single
    # character draining is expected, the fleet is what should stay full.
    assert fleet.occupied_slots() == 5
    assert fleet.queue_occupancy() == pytest.approx(5 / 40)


def test_rotation_prefers_the_account_already_open():
    fleet = _fleet()
    chosen = fleet.next_character(NOW, current_account_id="acc-1")
    assert chosen is not None
    assert chosen.account_id == "acc-1"


def test_rotation_moves_on_when_the_open_account_is_exhausted():
    fleet = _fleet()
    for character in fleet.accounts[0].characters:
        for slot in range(MARCHES_PER_CHARACTER):
            character.dispatch(_march(slot, 240))

    chosen = fleet.next_character(NOW, current_account_id="acc-0")
    assert chosen is not None
    assert chosen.account_id == "acc-1"


def test_rotation_tops_up_the_emptiest_eligible_character_first():
    fleet = _fleet(accounts=1, per_account=2)
    partly, empty = fleet.characters
    partly.dispatch(_march(0, 10))
    # Both are eligible well after the only march is home.
    later = NOW + timedelta(minutes=30)
    assert fleet.next_character(later) is empty


def test_no_eligible_character_is_a_waiting_state_not_an_error():
    fleet = _fleet(accounts=1, per_account=1)
    character = fleet.characters[0]
    character.dispatch(_march(0, 120))

    assert fleet.next_character(NOW) is None
    assert fleet.next_eligible_at() == NOW + timedelta(minutes=120)
    assert fleet.next_character(NOW + timedelta(minutes=120)) is character


def test_a_character_cannot_be_filed_under_the_wrong_account():
    with pytest.raises(FleetError):
        Account(account_id="acc-1", characters=[_character(account_id="acc-2")])


def test_duplicate_accounts_are_refused():
    account = Account(account_id="acc-1", characters=[])
    with pytest.raises(FleetError):
        Fleet([account, Account(account_id="acc-1", characters=[])])


def test_a_march_must_arrive_after_it_leaves():
    with pytest.raises(FleetError):
        March(
            slot=0,
            kind=ResourceKind.GOLD,
            dispatched_at=NOW,
            expected_home_at=NOW - timedelta(minutes=1),
        )
