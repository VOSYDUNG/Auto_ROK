"""The work process the harness is used for.

Pure domain logic - no capture, no OCR, no input, no game dependency.  It is
the layer the legacy ``Mouse_key.py`` never had: that script encoded clicks and
had no concept of a goal, so any exception froze the lifecycle.

Recorded in ``knowledge/farming_workflow_2026-09-19.yaml``.
"""
from autorok.mission.allocation import (
    AllocationError,
    AllocationMode,
    SlotAssignment,
    allocate_by_ratio,
    is_degraded,
    plan_slots,
)
from autorok.mission.fleet import (
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
)
from autorok.mission.order import (
    DEFAULT_RATIO,
    DeliveryLedger,
    DeliveryPost,
    Order,
    OrderError,
    ResourceKind,
    shortfall_rate,
)

__all__ = [
    "DEFAULT_RATIO",
    "MARCHES_PER_CHARACTER",
    "OPERATOR_BASELINE_STRONG",
    "OPERATOR_BASELINE_WEAK",
    "Account",
    "AllocationError",
    "AllocationMode",
    "Character",
    "CycleEstimate",
    "CycleSource",
    "DeliveryLedger",
    "DeliveryPost",
    "Fleet",
    "FleetError",
    "March",
    "Order",
    "OrderError",
    "ResourceKind",
    "SlotAssignment",
    "allocate_by_ratio",
    "is_degraded",
    "plan_slots",
    "shortfall_rate",
]
