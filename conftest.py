"""Make the repository importable for tests, from any working directory.

``pyproject.toml`` already sets ``pythonpath = ["."]``, which covers the normal
case. This file covers the ones it does not: an editor or IDE that collects
tests with its own runner and skips the ini file, and any invocation where the
working directory is not the repository root.

It is deliberately the only sys.path manipulation in the test tree - the tests
themselves contain none, and should not gain any.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import pytest


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """The repository root, for tests that need a file on disk.

    Tests must not reach for a path relative to the working directory: seven
    of them did, and the suite only passed because it was always launched from
    the root. Running it from anywhere else raised FileNotFoundError.
    """
    return ROOT
