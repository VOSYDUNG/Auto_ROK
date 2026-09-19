"""Run every project check on the operator's own machine.

This replaces the two hosted CI workflows removed on 2026-09-19.  They ran the
suite on rented Linux runners, which contradicted the project's own boundary:
one agent, one real Windows machine, nothing rented and nothing emulated.

The whole suite takes about nine seconds locally, so there is nothing to gain
from running it somewhere else.  Run this before every commit:

    python scripts/check_local.py

It emits no game input and touches no client window.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHECKS: tuple[tuple[str, list[str]], ...] = (
    ("test suite", [sys.executable, "-m", "pytest", "-q"]),
    ("engineering graph", [sys.executable, "scripts/validate_engineering_graph.py"]),
)


def _run(label: str, command: list[str]) -> tuple[bool, float, str]:
    started = time.perf_counter()
    completed = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, check=False
    )
    elapsed = time.perf_counter() - started
    output = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode == 0, elapsed, output.strip()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    verbose = "--verbose" in argv

    failures: list[str] = []
    print(f"Auto_ROK local checks - {ROOT}\n")

    for label, command in CHECKS:
        ok, elapsed, output = _run(label, command)
        status = "PASS" if ok else "FAIL"
        tail = output.splitlines()[-1] if output else ""
        print(f"  [{status}] {label:24s} {elapsed:5.1f}s  {tail[:60]}")
        if not ok:
            failures.append(label)
            print("\n" + output + "\n")
        elif verbose and output:
            print("\n" + output + "\n")

    print()
    if failures:
        print(f"FAILED: {', '.join(failures)}")
        return 1
    print("All local checks passed. Safe to commit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
