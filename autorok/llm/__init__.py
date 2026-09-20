"""The 20% decision edge, and the boundary that protects it.

``boundary`` is the single place that decides what may leave the harness
toward a model. Both decision tiers import it; neither keeps its own copy.
"""
from autorok.llm.boundary import (
    FORBIDDEN_KEY_PARTS,
    forbidden_parts_in,
    is_forbidden_key,
    strip_forbidden,
)

__all__ = [
    "FORBIDDEN_KEY_PARTS",
    "forbidden_parts_in",
    "is_forbidden_key",
    "strip_forbidden",
]
