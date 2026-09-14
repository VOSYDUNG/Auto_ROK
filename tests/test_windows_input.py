import pytest

from harness.human_io import KeyboardAction, MouseAction
from harness.windows_input import WindowsHumanInputActuator, WindowsInputError


class FakeBackend:
    def __init__(self):
        self.events = []

    def move_to(self, x, y):
        self.events.append(("move", x, y))

    def left_click(self):
        self.events.append(("click",))

    def key_down(self, key):
        self.events.append(("down", key))

    def key_up(self, key):
        self.events.append(("up", key))


def test_click_is_bounded_move_then_left_click():
    backend = FakeBackend()
    WindowsHumanInputActuator(backend).perform(MouseAction("click", x=10, y=20, button="left"))
    assert backend.events == [("move", 10, 20), ("click",)]


def test_keyboard_combo_presses_then_releases_in_reverse_order():
    backend = FakeBackend()
    WindowsHumanInputActuator(backend).perform(KeyboardAction(("CTRL", "A")))
    assert backend.events == [
        ("down", "CTRL"),
        ("down", "A"),
        ("up", "A"),
        ("up", "CTRL"),
    ]


def test_unsupported_mouse_action_fails_closed():
    backend = FakeBackend()
    with pytest.raises(WindowsInputError):
        WindowsHumanInputActuator(backend).perform(MouseAction("drag", x=1, y=2, x2=3, y2=4))
    assert backend.events == []
