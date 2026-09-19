from collections import Counter

import pytest

from autorok.mission import (
    DEFAULT_RATIO,
    AllocationError,
    AllocationMode,
    ResourceKind,
    allocate_by_ratio,
    is_degraded,
    plan_slots,
)


def test_the_default_ratio_weights_gold_double():
    assert DEFAULT_RATIO[ResourceKind.GOLD] == 2
    for kind in (ResourceKind.FOOD, ResourceKind.WOOD, ResourceKind.STONE):
        assert DEFAULT_RATIO[kind] == 1


def test_five_slots_land_on_the_one_one_one_two_mix():
    counts = Counter(allocate_by_ratio(5))
    assert counts[ResourceKind.GOLD] == 2
    assert counts[ResourceKind.FOOD] == 1
    assert counts[ResourceKind.WOOD] == 1
    assert counts[ResourceKind.STONE] == 1


def test_a_full_fleet_of_forty_slots_holds_the_ratio():
    counts = Counter(allocate_by_ratio(40))
    assert counts[ResourceKind.GOLD] == 16
    assert counts[ResourceKind.FOOD] == 8
    assert counts[ResourceKind.WOOD] == 8
    assert counts[ResourceKind.STONE] == 8


def test_allocation_tops_up_toward_the_ratio_instead_of_resetting_it():
    # Gold is already over-represented, so the free slots go elsewhere.
    assignments = allocate_by_ratio(
        3, in_flight={ResourceKind.GOLD: 7, ResourceKind.FOOD: 0}
    )
    assert ResourceKind.GOLD not in assignments


def test_allocation_is_deterministic():
    assert allocate_by_ratio(7) == allocate_by_ratio(7)


def test_zero_free_slots_allocates_nothing():
    assert allocate_by_ratio(0) == []
    assert plan_slots(0, available_levels=[6, 5]) == []


@pytest.mark.parametrize("bad", [-1, "3", 2.5, True])
def test_invalid_slot_counts_are_refused(bad):
    with pytest.raises(AllocationError):
        allocate_by_ratio(bad)


def test_a_ratio_with_no_positive_weight_is_refused():
    with pytest.raises(AllocationError):
        allocate_by_ratio(3, ratio={ResourceKind.GOLD: 0})


def test_plentiful_nodes_keep_every_slot_in_normal_mode():
    plan = plan_slots(
        3, available_levels=[6, 6, 5, 5, 4], preferred_min_level=4
    )
    assert len(plan) == 3
    assert all(item.mode is AllocationMode.NORMAL for item in plan)
    assert not is_degraded(plan)
    # Highest nodes are consumed first.
    assert [item.min_node_level for item in plan] == [6, 6, 5]


def test_a_picked_clean_kingdom_degrades_instead_of_stalling():
    plan = plan_slots(5, available_levels=[], preferred_min_level=5)

    assert len(plan) == 5, "an empty search must still fill every slot"
    assert all(item.mode is AllocationMode.SCARCITY for item in plan)
    assert is_degraded(plan)
    assert all(item.min_node_level == 1 for item in plan)


def test_partial_scarcity_degrades_only_the_slots_that_need_it():
    plan = plan_slots(5, available_levels=[6, 5], preferred_min_level=5)

    modes = [item.mode for item in plan]
    assert modes.count(AllocationMode.NORMAL) == 2
    assert modes.count(AllocationMode.SCARCITY) == 3
    assert is_degraded(plan)


def test_nodes_below_the_preferred_level_do_not_count_as_preferred():
    plan = plan_slots(2, available_levels=[3, 2], preferred_min_level=5)
    assert all(item.mode is AllocationMode.SCARCITY for item in plan)


def test_degrading_may_never_tighten_the_requirement():
    with pytest.raises(AllocationError):
        plan_slots(
            1,
            available_levels=[],
            preferred_min_level=4,
            scarcity_floor_level=6,
        )


def test_the_scarcity_floor_is_configurable():
    plan = plan_slots(
        2, available_levels=[], preferred_min_level=6, scarcity_floor_level=3
    )
    assert all(item.min_node_level == 3 for item in plan)


def test_every_assignment_states_why_it_was_made():
    plan = plan_slots(2, available_levels=[6], preferred_min_level=5)
    assert all(item.reason for item in plan)
