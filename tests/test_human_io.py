from harness.human_io import (
    HUMAN_INTERFACE_BOUNDARY,
    MotorChannel,
    SensoryChannel,
)


def test_only_screen_pixels_are_allowed_for_game_sensing() -> None:
    HUMAN_INTERFACE_BOUNDARY.validate_sensor_channel(SensoryChannel.SCREEN_PIXELS)
    assert HUMAN_INTERFACE_BOUNDARY.sensory_channels == (SensoryChannel.SCREEN_PIXELS,)


def test_only_mouse_and_keyboard_are_allowed_for_game_actuation() -> None:
    HUMAN_INTERFACE_BOUNDARY.validate_motor_channel(MotorChannel.MOUSE)
    HUMAN_INTERFACE_BOUNDARY.validate_motor_channel(MotorChannel.KEYBOARD)
    assert set(HUMAN_INTERFACE_BOUNDARY.motor_channels) == {
        MotorChannel.MOUSE,
        MotorChannel.KEYBOARD,
    }
