# Repository consolidation

`Auto_ROK` is now the canonical implementation checkout for the local-LLM
ROK harness.

## Imported responsibility map

| Source | Kept in Auto_ROK | Treatment |
| --- | --- | --- |
| `Auto_ROK` legacy scripts | root legacy files and knowledge | preserved as evidence only |
| `Auto_ROK-harness-review` | mission compiler, graph/runtime contracts, observation bridge, anchors and ledger | active harness code/config/tests |
| `LLM-LOCAL` | 80/20 goal, local model boundary, loopback/OpenAI-compatible contract | distilled into `docs/GOAL.md` and `config/local-llm.json` |
| raw `workspace/`, caches and generated runs | no production import | evidence stays outside the canonical source path until explicitly selected |
| DeepSeek Harness source and model weights | no vendoring | use as external reference/runtime dependency; do not copy weights into Git |

## 80/20 boundary

Deterministic code performs perception, knowledge lookup, mission transitions,
policy checks, target grounding, guarded actuation and verification. The local
model is called only for `NEEDS_DECISION` and can return only one candidate that
the harness has already exposed. A failed or slow endpoint returns
`NEEDS_DECISION`; it never authorizes a guessed click.

## Cleanup rule

The two source checkouts are archive inputs, not additional product authorities.
Do not delete or reset them until their desired evidence has been committed or
copied into this repository. Do not stage generated `workspace/`, `__pycache__`
or `.pytest_cache` content as product code.
