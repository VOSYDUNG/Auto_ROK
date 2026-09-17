# Auto_ROK reference set

This directory is the short, reviewable reference layer for the canonical
checkout. It records where the design came from without making caches, raw
transcripts or model weights part of the product source tree.

## Source checkouts

- `Auto_ROK-harness-review`: `agentic-harness-v1` harness contracts and the
  deterministic GATHER/observation work.
- `LLM-LOCAL`: local routing, DeepSeek Harness evaluation notes and the
  Qwen/GPT-OSS loopback model contract.

## Canonical local copies

- Product goal and 80/20 boundary: [`docs/GOAL.md`](../GOAL.md)
- Consolidation and ownership: [`docs/CONSOLIDATION.md`](../CONSOLIDATION.md)
- Local model contract: [`config/local-llm.json`](../../config/local-llm.json)
- Canonical one-tick entrypoint: [`scripts/run_autorok.py`](../../scripts/run_autorok.py)

## Imported design references

- [`DEEPSEEK_HARNESS.md`](DEEPSEEK_HARNESS.md)
- [`TOOLS_FIRST_MISSIONS.md`](TOOLS_FIRST_MISSIONS.md)
- [`LOCAL_HARNESS_PRD.md`](LOCAL_HARNESS_PRD.md)
- [`G002_EXECUTION_PLAN.md`](G002_EXECUTION_PLAN.md)
- [`M1_EXECUTION_PLAN.md`](M1_EXECUTION_PLAN.md)
- [`MISSION_LEDGER.md`](MISSION_LEDGER.md)
- [`TEMPLATE_ANCHORS.md`](TEMPLATE_ANCHORS.md)

## Deliberately excluded

Generated run directories, Python caches, pytest caches, raw model transcripts,
the vendored DeepSeek source tree and GGUF weights are not copied into the
canonical Git history. They remain local evidence or external dependencies and
must be imported only through a narrowly scoped, reviewed artifact.
