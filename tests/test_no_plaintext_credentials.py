"""No account credentials in the repository - SRS SAF-006.

The operator intends the agent to sign accounts in and rotate between them.
That is a real requirement and it is not in dispute. What is in dispute is
where the secret lives: a password committed to a repository is a password
published, and it stays published after it is deleted because git keeps the
history.

So the rule is narrow and mechanical. The repository may talk about
credentials, name the fields, and describe the login flow. It may not contain
a value. When account login is built, the secret belongs in Windows
Credential Manager, entered once by the operator, and read at runtime - never
committed, never logged, never put in a mission fact where the boundary would
then have to strip it.

Same shape as ``test_no_virtualization``: a per-file, per-substring exemption
list, so a new violation cannot hide behind an existing one.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

SCANNED_DIRS = (
    "autorok",
    "harness",
    "scripts",
    "tests",
    "config",
    "operator_layer",
    "knowledge",
    "docs",
)

SCANNED_SUFFIXES = {".py", ".yaml", ".yml", ".json", ".ps1", ".toml", ".cfg", ".md"}

#: An assignment of a secret to a literal value. The point is the VALUE - a
#: bare mention of the word "password" is documentation, not a leak.
ASSIGNMENT = re.compile(
    r"""(?ix)
    \b(pass(word|wd)?|secret|token|api[_-]?key|credential)s?\b
    \s* [:=] \s*
    (?P<value>["'][^"']{3,}["'])
    """,
)

#: Values that are obviously not secrets: placeholders, type annotations and
#: the names of the safe mechanisms.
PLACEHOLDERS = re.compile(
    r"""(?ix)
    ^["'](
        \s* |
        (x|\*|\.){1,} |
        none | null | todo | tbd | example | placeholder | redacted |
        changeme | your[_ -]?password | <[^>]*> |
        str | int | bool | float |
        windows[ _-]?credential[ _-]?manager |
        operator[_ -]?supplied.* |
        .*\{[^}]*\}.*
    )["']$
    """,
)


#: (path suffix, substring on the same line) pairs allowed because the line
#: exists to talk ABOUT credentials rather than to hold one.
EXEMPTIONS = (
    # This file spells the patterns out in order to search for them.
    ("tests/test_no_plaintext_credentials.py", ""),
)


def _is_exempt(relative: str, line: str) -> bool:
    return any(
        relative.endswith(suffix) and required in line
        for suffix, required in EXEMPTIONS
    )


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
            and path.suffix.lower() in SCANNED_SUFFIXES
            and "__pycache__" not in path.parts
        )
    return sorted(files)


def test_the_scan_actually_looks_at_something():
    """A guard that scans nothing passes forever."""
    files = _scanned_files()
    assert len(files) > 50, f"only {len(files)} files scanned; the globs are wrong"


def test_no_secret_is_assigned_a_literal_value_anywhere_in_the_repository():
    offenders: list[str] = []
    for path in _scanned_files():
        relative = path.relative_to(ROOT).as_posix()
        for number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            match = ASSIGNMENT.search(line)
            if not match or _is_exempt(relative, line):
                continue
            if PLACEHOLDERS.match(match.group("value")):
                continue
            offenders.append(f"{relative}:{number}: {line.strip()[:110]}")
    assert not offenders, (
        "a credential value appears in the repository:\n  "
        + "\n  ".join(offenders)
        + "\n\nSecrets belong in Windows Credential Manager, entered once by "
        "the operator and read at runtime. Committing one publishes it, and "
        "git history keeps it published after the deletion."
    )


@pytest.mark.parametrize(
    "line",
    [
        'password = "hunter2correct"',
        "PASSWORD: 'rok-account-live'",
        'api_key = "sk-live-9f2b7c1d"',
        'token: "ghp_abcdefghijklmnop"',
    ],
)
def test_the_pattern_catches_a_real_leak(line):
    """Otherwise the guard above could be passing for the wrong reason."""
    match = ASSIGNMENT.search(line)
    assert match is not None
    assert not PLACEHOLDERS.match(match.group("value"))


@pytest.mark.parametrize(
    "line",
    [
        'password: "<operator supplies this>"',
        "password = None",
        'password: str = ""',
        'secret = "TODO"',
        'password = f"{prompt_operator()}"',
        'credential_store: "Windows Credential Manager"',
    ],
)
def test_the_pattern_does_not_fire_on_a_placeholder_or_a_description(line):
    match = ASSIGNMENT.search(line)
    assert match is None or PLACEHOLDERS.match(match.group("value"))


def test_the_declaration_still_says_where_secrets_belong():
    """A rule that only lives in a test can be deleted with the test."""
    text = (ROOT / "docs" / "SRS.md").read_text(encoding="utf-8")
    assert "SAF-006" in text
