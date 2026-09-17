# Auto_ROK — canonical local-LLM harness

## Objective

Build one bounded harness that lets a local Qwen or GPT-OSS model operate Rise
of Kingdoms through the same visible screen and ordinary mouse/keyboard surface
available to a human player.

The harness owns the game work. The model is only a small decision edge:

- harness: capture, OCR/CV, frame provenance, game knowledge, mission graph,
  policy, target grounding, input guards, checkpoints, retries and visible
  postcondition verification;
- local LLM: choose one action from an already-valid candidate set when the
  deterministic mission graph leaves more than one meaningful choice;
- default reasoning budget: approximately 10–20% of the interaction loop;
- model output is untrusted and must match one existing `ActionChoice` exactly.

## Canonical entrypoint

Use `scripts/run_autorok.py` for new bounded mission work. It delegates to the
GATHER_RESOURCE runner and can optionally load `config/local-llm.json` with
`--local-llm-config`. The config is disabled by default while the local model
server is unavailable.

`main.py`, `Avatar.py`, `Human.py`, `Mouse_key.py` and related files are retained
as legacy evidence that the original Python scripts could drive ROK. They are
not imported by the new harness and are not an acceptance path.

## Current vertical slice

The first accepted product slice is one-character `GATHER_RESOURCE`. Other
missions remain separate until their observation, policy, action and verification
contracts are implemented independently.

## Safety and acceptance

The harness must fail closed on stale, missing or ambiguous evidence; it must
not read process memory, inject into the game, invent coordinates or treat a
dispatch receipt as visible success. A local-model run is not accepted merely
because HTTP transport succeeds: the run needs bounded candidate selection,
fresh post-action observation and a durable verification record.
