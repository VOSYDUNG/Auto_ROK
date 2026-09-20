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
    MarchPurpose,
)
from autorok.mission.ladder import (
    PURPOSE,
    Ladder,
    LadderError,
    Rung,
    Transition,
    is_persistently_degraded,
    summarise,
)
from autorok.mission.transport import (
    LEVEL_25,
    TradingPost,
    TransportError,
    TransportLoad,
    plan_runs,
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
    "PURPOSE",
    "LEVEL_25",
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
    "Ladder",
    "LadderError",
    "FleetError",
    "March",
    "MarchPurpose",
    "Order",
    "OrderError",
    "ResourceKind",
    "Rung",
    "SlotAssignment",
    "Transition",
    "TradingPost",
    "TransportError",
    "TransportLoad",
    "allocate_by_ratio",
    "is_degraded",
    "is_persistently_degraded",
    "plan_runs",
    "plan_slots",
    "shortfall_rate",
    "summarise",
]
