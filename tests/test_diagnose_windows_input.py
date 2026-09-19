from pathlib import Path
import ast


SCRIPT = Path(__file__).parents[1] / "scripts" / "diagnose_windows_input.py"


def _called_attribute_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


def test_input_diagnostic_has_no_mutating_desktop_or_pointer_calls():
    source = SCRIPT.read_text(encoding="utf-8")
    calls = _called_attribute_names(source)

    assert "SetCursorPos" not in calls
    assert "SetThreadDesktop" not in calls
    assert "OpenInputDesktop" in calls
    assert "GetCursorPos" in calls


def test_input_diagnostic_declares_no_input_emitted_contract():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "'input_emitted': False" in source
