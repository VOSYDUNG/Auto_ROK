from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Protocol, Sequence


class SensoryChannel(str, Enum):
    SCREEN_PIXELS = "screen_pixels"


class MotorChannel(str, Enum):
    MOUSE = "mouse"
    KEYBOARD = "keyboard"


@dataclass(frozen=True)
class ScreenFrame:
    """Visible observation available to the harness.

    This object represents only pixels a human could see on the screen. It must
    never be populated from game-process memory, private game APIs, engine
    objects, packet inspection, or injected telemetry.
    """

    frame_id: str
    timestamp: float
    width: int
    height: int
    image_ref: str
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class MouseAction:
    kind: str  # move | click | drag | scroll
    x: int | None = None
    y: int | None = None
    x2: int | None = None
    y2: int | None = None
    button: str | None = None
    amount: int | None = None
    duration_s: float | None = None


@dataclass(frozen=True)
class KeyboardAction:
    keys: Sequence[str]
    duration_s: float | None = None


HumanInputAction = MouseAction | KeyboardAction


class VisualSensor(Protocol):
    def capture(self) -> ScreenFrame: ...


class HumanInputActuator(Protocol):
    def perform(self, action: HumanInputAction) -> None: ...


@dataclass(frozen=True)
class HumanInterfaceBoundary:
    """Architectural contract for computer-use-only game interaction.

    The game is treated as an external visual environment. The harness may
    observe visible pixels and may act through ordinary OS mouse/keyboard input.
    Everything else is outside the architecture.
    """

    sensory_channels: tuple[SensoryChannel, ...] = (SensoryChannel.SCREEN_PIXELS,)
    motor_channels: tuple[MotorChannel, ...] = (MotorChannel.MOUSE, MotorChannel.KEYBOARD)

    def validate_sensor_channel(self, channel: SensoryChannel) -> None:
        if channel not in self.sensory_channels:
            raise PermissionError(f"sensory channel {channel!r} is outside the human-interface boundary")

    def validate_motor_channel(self, channel: MotorChannel) -> None:
        if channel not in self.motor_channels:
            raise PermissionError(f"motor channel {channel!r} is outside the human-interface boundary")


HUMAN_INTERFACE_BOUNDARY = HumanInterfaceBoundary()
