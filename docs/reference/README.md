# Auto_ROK reference set

This directory is the short, reviewable reference layer for the canonical
checkout. It records where the design came from without making caches, raw
transcripts or model weights part of the product source tree.

## Source checkouts

- `Auto_ROK-harness-review`: `agentic-harness-v1` harness contracts and the
  deterministic GATHER/observation work.
- `LLM-LOCAL`: local routing, DeepSeek Harness evaluation notes and the
  Qwen/GPT-OSS loopback model contract.

## Authoritative documents

This directory is a reference layer, not a definition layer. Scope, goal and
status are defined only by:

- Project declaration (highest): [`docs/PROJECT_DECLARATION.md`](../PROJECT_DECLARATION.md)
- Goal and the G1-G6 definition of done: [`docs/GOAL.md`](../GOAL.md)
- Product requirements: [`docs/PRD.md`](../PRD.md)
- Measured coverage: [`docs/COVERAGE.md`](../COVERAGE.md)

## Canonical local copies

- Consolidation and ownership: [`docs/CONSOLIDATION.md`](../CONSOLIDATION.md)
- Local model contract: [`config/local-llm.json`](../../config/local-llm.json)
- Canonical one-tick entrypoint: [`scripts/run_gather_tick.py`](../../scripts/run_gather_tick.py)

## Imported design references

- [`TOOLS_FIRST_MISSIONS.md`](TOOLS_FIRST_MISSIONS.md)
- [`G002_EXECUTION_PLAN.md`](G002_EXECUTION_PLAN.md)
- [`LOCAL_LLM_USER_STORIES.md`](LOCAL_LLM_USER_STORIES.md)
- [`MISSION_LEDGER.md`](MISSION_LEDGER.md)
- [`TEMPLATE_ANCHORS.md`](TEMPLATE_ANCHORS.md)
- [`SOURCE_MANIFEST.md`](SOURCE_MANIFEST.md)

Superseded references now live in [`docs/archive/`](../archive/README.md).

## Deliberately excluded

Generated run directories, Python caches, pytest caches, raw model transcripts,
the vendored DeepSeek source tree and GGUF weights are not copied into the
canonical Git history. They remain local evidence or external dependencies and
must be imported only through a narrowly scoped, reviewed artifact.
