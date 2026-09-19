"""The no-virtualization boundary, enforced instead of promised.

docs/PROJECT_DECLARATION.md puts Docker, virtual machines and Hyper-V out of
scope: one agent, one real Windows machine.  That rule was already written down
and virtualization got in anyway - a guest/VM validator, a hidden CLI flag, and
two CI workflows running on rented Linux VMs.

A rule nobody checks is a wish.  This test is the check.  If the vocabulary
comes back, the suite goes red on the commit that introduced it, not six months
later.

Sites that name a hypervisor *in order to reject it* are legitimate and are
listed explicitly below.  The allowlist is deliberately per-file and
per-substring so a new violation cannot hide behind an existing exemption.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Directories that hold product source.  ``workspace/`` is runtime evidence and
#: ``docs/archive/`` is retired history; neither can execute anything.
SCANNED_DIRS = ("autorok", "harness", "scripts", "tests", "config", "operator_layer")

SCANNED_SUFFIXES = {".py", ".yaml", ".yml", ".json", ".ps1", ".toml", ".cfg", ".txt"}

#: Terms that mean "this runs somewhere other than the operator's machine".
FORBIDDEN_TERMS = (
    "docker",
    "hyper-v",
    "hypervisor",
    "virtual machine",
    "virtualbox",
    "vmware",
    "runs-on",
    "ubuntu-latest",
    "windows-latest",
    "guest isolation",
    "guest_isolation",
)

#: (path suffix, substring that must appear on the same line) pairs that are
#: allowed, because the line exists to REFUSE the thing it names.
GUARD_EXEMPTIONS = (
    ("harness/host_input_isolation.py", "out of product scope"),
    ("harness/host_input_isolation.py", "deliberately does not mention"),
    ("scripts/assess_host_input_isolation.py", "never starts a VM"),
    # This file names every forbidden term in order to search for them.
    ("tests/test_no_virtualization.py", ""),
)


def _is_exempt(relative: str, line: str) -> bool:
    for path_suffix, required in GUARD_EXEMPTIONS:
        if relative.endswith(path_suffix) and required in line:
            return True
    return False


def _scanned_files() -> list[Path]:
    files: list[Path] = []
    for directory in SCANNED_DIRS:
        base = ROOT / directory
        if not base.exists():
            continue
        files.extend(
            path
            for path in base.rglob("*")
            if path.is_file()
            and path.suffix in SCANNED_SUFFIXES
            and "__pycache__" not in path.parts
        )
    files.extend(
        path
        for path in ROOT.glob("*")
        if path.is_file() and path.suffix in SCANNED_SUFFIXES
    )
    return files


def test_no_continuous_integration_workflows_exist():
    """CI ran the project's tests on rented Linux VMs.

    The operator removed it deliberately: one agent, one machine, and the
    296-test suite runs locally in about nine seconds.
    """
    workflows = ROOT / ".github" / "workflows"
    present = sorted(p.name for p in workflows.glob("*.yml")) if workflows.exists() else []
    present += sorted(p.name for p in workflows.glob("*.yaml")) if workflows.exists() else []
    assert not present, (
        f"CI workflow files reappeared: {present}. Hosted runners are virtual "
        f"machines; run scripts/check_local.py on the operator's machine instead."
    )


def test_no_virtualization_vocabulary_in_product_source():
    violations: list[str] = []

    for path in _scanned_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        relative = path.relative_to(ROOT).as_posix()
        for number, line in enumerate(text.splitlines(), start=1):
            lowered = line.casefold()
            for term in FORBIDDEN_TERMS:
                if term in lowered and not _is_exempt(relative, line):
                    violations.append(f"{relative}:{number}: {term!r} in {line.strip()[:90]}")

    assert not violations, (
        "Virtualization vocabulary reappeared in product source.\n"
        "docs/PROJECT_DECLARATION.md scopes this project to one agent on one\n"
        "real Windows machine. If a line names a hypervisor in order to refuse\n"
        "it, add it to GUARD_EXEMPTIONS with the refusing substring.\n\n"
        + "\n".join(violations)
    )


def test_the_removed_guest_isolation_island_stays_removed():
    """The legacy guest/VM validator and its probes.

    They were a feasibility experiment that outlived the decision, and
    ``docs/HOST_INPUT_ISOLATION.md`` already called the guest gate "not a
    product requirement" while the code stayed.
    """
    removed = (
        "harness/guest_isolation.py",
        "scripts/assess_guest_isolation.py",
        "scripts/probe_guest_host.py",
        "tests/test_guest_isolation.py",
        "tests/test_guest_host_probe.py",
    )
    still_present = [name for name in removed if (ROOT / name).exists()]
    assert not still_present, f"guest/VM path reappeared: {still_present}"


def test_evidence_writer_cannot_record_guest_isolation():
    """New evidence must not be writable under the retired key."""
    from harness.gather_replay_evidence import build_gather_tick_evidence

    import inspect

    signature = inspect.signature(build_gather_tick_evidence)
    assert "guest_isolation" not in signature.parameters, (
        "build_gather_tick_evidence regained a guest_isolation parameter; "
        "direct-host runs record host_input_isolation"
    )


@pytest.mark.parametrize(
    "document",
    ["docs/PROJECT_DECLARATION.md", "docs/GOAL.md"],
)
def test_the_boundary_is_still_written_down(document):
    """The check and the declaration have to agree.

    If someone relaxes the declaration, this test should be what makes that a
    visible decision rather than a quiet one.
    """
    text = (ROOT / document).read_text(encoding="utf-8").casefold()
    assert "docker" in text and "hyper-v" in text, (
        f"{document} no longer states the no-virtualization boundary that "
        f"this test enforces"
    )
