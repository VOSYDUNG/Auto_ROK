"""Record historical read-only host capability facts from the old guest plan.

This probe never enables Windows features, starts a VM, reboots, captures the
desktop, or emits keyboard/mouse input. Its output is historical feasibility
evidence only; the product gate is direct-host input isolation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = (ROOT / "workspace" / "evidence").resolve()


class GuestHostProbeError(ValueError):
    """Raised when the probe cannot produce a bounded evidence record."""


Runner = Callable[[str], tuple[int, str, str]]


def _run_powershell(command: str) -> tuple[int, str, str]:
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def _json_probe(runner: Runner, command: str) -> Mapping[str, Any] | None:
    code, stdout, _stderr = runner(command)
    if code != 0 or not stdout:
        return None
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, Mapping) else None


def _bool_probe(runner: Runner, command: str) -> bool:
    code, _stdout, _stderr = runner(command)
    return code == 0


def _host_facts(runner: Runner) -> dict[str, Any]:
    computer = _json_probe(
        runner,
        "Get-ComputerInfo | Select-Object WindowsProductName,WindowsVersion,OsBuildNumber,HyperVisorPresent | ConvertTo-Json -Compress",
    )
    if computer is None:
        computer = {}
    vm_cmdlet = _bool_probe(
        runner,
        "if (Get-Command Get-VM -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }",
    )
    vm_processes = _json_probe(
        runner,
        "@(Get-Process -Name vmms,vmcompute -ErrorAction SilentlyContinue | Select-Object -ExpandProperty ProcessName) | ConvertTo-Json -Compress",
    )
    if vm_processes is None:
        vm_processes = []
    elif isinstance(vm_processes, str):
        vm_processes = [vm_processes]
    elif not isinstance(vm_processes, list):
        vm_processes = []
    return {
        "os": {
            "product_name": computer.get("WindowsProductName"),
            "version": computer.get("WindowsVersion"),
            "build_number": computer.get("OsBuildNumber"),
            "hypervisor_present": computer.get("HyperVisorPresent"),
        },
        "virtualization": {
            "vm_cmdlet_available": vm_cmdlet,
            "vm_management_processes": sorted({str(item) for item in vm_processes}),
        },
    }


def _storage_facts() -> list[dict[str, Any]]:
    anchor = Path.cwd().anchor or "."
    usage = shutil.disk_usage(anchor)
    gib = 1024**3
    return [{
        "root": anchor,
        "total_gib": round(usage.total / gib, 2),
        "free_gib": round(usage.free / gib, 2),
    }]


def build_probe(*, runner: Runner = _run_powershell) -> dict[str, Any]:
    host = _host_facts(runner)
    storage = _storage_facts()
    reasons: list[str] = []
    os_facts = host["os"]
    virtualization = host["virtualization"]
    if os_facts.get("hypervisor_present") is not True:
        reasons.append("no active Windows hypervisor is observed")
    if virtualization.get("vm_cmdlet_available") is not True:
        reasons.append("Hyper-V Get-VM management cmdlet is unavailable")
    if not virtualization.get("vm_management_processes"):
        reasons.append("vmms/vmcompute management processes are not observed")
    if not storage or storage[0].get("free_gib", 0) < 70:
        reasons.append("current local free space is below the 70 GiB guest-capacity planning floor")
    reasons.append("no instrumented guest trace is present for the current R2 occurrence")
    return {
        "schema_version": 1,
        "evidence_id": "host-capability-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "environment": "windows_host",
        "status": "not_ready",
        "host": host,
        "storage": storage,
        "guest": {
            "named_guest_present": False,
            "instrumented_guest_present": False,
            "trace_available": False,
        },
        "reasons": reasons,
        "input_emitted": False,
    }


def _output_path(value: str) -> Path:
    path = Path(value).resolve()
    if not path.is_relative_to(EVIDENCE_ROOT) or path == EVIDENCE_ROOT:
        raise GuestHostProbeError("output must stay under workspace/evidence")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(EVIDENCE_ROOT / "guest" / "host-capability-latest.json"),
    )
    args = parser.parse_args(argv)
    try:
        output = _output_path(args.output)
        payload = build_probe()
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(output.name + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output)
        printed = dict(payload)
        printed["evidence_path"] = str(output)
        print(json.dumps(printed, ensure_ascii=False))
        return 0
    except (OSError, GuestHostProbeError) as exc:
        print(json.dumps({
            "schema_version": 1,
            "status": "invalid",
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "input_emitted": False,
        }, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
