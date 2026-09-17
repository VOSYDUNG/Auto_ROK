# Consolidation source manifest

This is the provenance index for the canonical Auto_ROK harness checkpoint.

| Source | Snapshot inspected | Imported into Auto_ROK |
| --- | --- | --- |
| `Auto_ROK-harness-review` | `agentic-harness-v1 @ 6e3e09e7c47282c31e14753969115d7fcbe8f9dc` | mission compiler/runtime, observation bridge, template anchors, mission ledger, focused tests and docs |
| `LLM-LOCAL` | `building-v0.1 @ 4fa26a71f41453f66fde7ddcc32158bc70673f99` plus local uncommitted G002/M1 artifacts | goal/PRD/execution references, tools-first boundary and DeepSeek/GPT-OSS contract distilled into the Auto_ROK goal and local provider config |
| `Auto_ROK` legacy | `gpt-gather-03 @ 0a83173942237fcbfe6ccc356246670033bbaeb0` | original Python automation remains in place as historical evidence; current runtime changes are preserved in the canonical branch |

## Not copied into product source

`workspace/`, `.pytest_cache/`, `__pycache__/`, raw transcripts, the vendored
DeepSeek source tree and GGUF weights remain local evidence/external runtime
dependencies. They are intentionally excluded from the canonical Git history.

## Canonical checkpoint

The consolidation is recorded locally by commit `6d1bff8` and generated-artifact
hygiene by `7fd0c2a`. No remote push or branch deletion has been performed.
