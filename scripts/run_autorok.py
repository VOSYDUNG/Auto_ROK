"""Canonical Auto_ROK entrypoint for one bounded mission tick.

The old root ``main.py`` remains preserved as legacy proof of the original
Python automation.  New work should enter through this wrapper and the
guarded mission runner instead of importing legacy click scripts.
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_gather_tick import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
