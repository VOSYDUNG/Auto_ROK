from __future__ import annotations

from scripts.probe_guest_host import build_probe


def _runner(command: str):
    if "Get-ComputerInfo" in command:
        return 0, '{"WindowsProductName":"Windows 10 Pro","WindowsVersion":"2009","OsBuildNumber":"19045","HyperVisorPresent":false}', ""
    if "Get-Command Get-VM" in command:
        return 1, "", ""
    if "Get-Process -Name" in command:
        return 0, "[]", ""
    raise AssertionError(command)


def test_probe_is_explicitly_not_ready_without_guest():
    report = build_probe(runner=_runner)
    assert report["status"] == "not_ready"
    assert report["environment"] == "windows_host"
    assert report["guest"]["trace_available"] is False
    assert report["input_emitted"] is False
    assert any("hypervisor" in reason for reason in report["reasons"])
    assert any("guest trace" in reason for reason in report["reasons"])
