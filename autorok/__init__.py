"""Auto_ROK - a local LLM operating Rise of Kingdoms through a bounded harness.

Three pillars, per docs/PROJECT_DECLARATION.md:

    harness   - 80% deterministic: capture, OCR, state, candidate filtering,
                guarded actuation, verification, evidence.  Still lives in the
                top-level ``harness`` package.
    llm       - 20% decision edge.
    mission   - the work process: what the farm fleet is actually for.

``autorok.mission`` is the first module written under the rewritten structure.
It is pure domain logic: no capture, no OCR, no input, no game dependency, so
it is fully testable offline.
"""

__all__ = ["mission"]
