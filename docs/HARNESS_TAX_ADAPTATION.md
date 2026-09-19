# Harness tax adaptation for Auto_ROK

Updated 2026-09-19.  This is a design and measurement contract, not a claim
that the local model is ready for unattended play.

## Decision

The Arena/UC Berkeley harness result is directly relevant to Auto_ROK: a model
and the program that supplies its context, tools, control flow and recovery are
one system.  The useful question for us is therefore not “which model is
stronger?” but “with the same local model and the same frame-bound case, which
harness spends less CPU, RAM, context and time while preserving a verified
postcondition?” The public report measured the same model across harnesses and
found much larger cost/context differences than success differences; its
intervals are wide, so we should copy the *measurement design*, not its exact
ranking.

Auto_ROK already has the correct safety direction: deterministic perception,
policy, grounding, guarded input, verification and persistence remain harness
authority; the local model receives only an existing semantic candidate set.
The new machine-readable contract is
`config/harness_benchmark_matrix.json`.

## What was inspected

### Pi (`@earendil-works/pi-coding-agent` 0.85.1)

Pi is intentionally a small coding harness.  Its default model surface is four
tools (`read`, `write`, `edit`, `bash`), and the supported extension seam can
register tools, intercept a call, add context, persist an entry or replace
compaction.  Sessions are append-only JSONL trees with branch navigation and
structured compaction.  These are good examples of keeping the default context
small and making the extension boundary explicit.

Pi also states that it has no built-in sandbox or permission boundary: tools and
extensions run with the host user's permissions.  That is acceptable for its
local coding use case only with an operator or an external isolation boundary;
it is not a safe game actuator for our direct-host product.  We must not expose
Pi's `bash`/filesystem surface to the local game model.

### DeepSeek Harness (`dsh`)

DeepSeek makes the whole runtime composable from plugins and ordered profiles.
Its useful architectural ideas are capability seams, explicit profile
composition, durable session events, “model-visible means logged”, and
package-owned runtime invariants that check event/state relationships.  Its
minimal preset is also a useful benchmark warning: removing runtime context and
tools changes the experiment, so every harness variant must state exactly what
the model sees.

The rest of that system is a general coding product: shell, filesystem, web,
computer-use, subagents, sandbox and workflow packages.  Copying that runtime
into Auto_ROK would add a second authority and a large amount of latency and
surface area without evidence that it improves GATHER_RESOURCE.

## Keep, adapt, reject

| Source idea | Decision for Auto_ROK | Distillation |
|---|---|---|
| Pi's four-tool/minimal default | **Keep as a principle** | The local model gets one structured request and no desktop/tool API. Measure request bytes/tokens instead of assuming a larger prompt helps. |
| Pi extensions and interceptors | **Adapt** | Use narrow Python protocol seams around existing graph authorities. A selector adapter may reject malformed output; it may not become a new policy or input authority. |
| Pi JSONL tree, branch and compaction | **Adapt selectively** | Keep typed `MissionCheckpoint`/evidence as truth. Use branch/replay concepts for offline cases; never replace typed facts with a prose summary. |
| DeepSeek ordered profiles/presets | **Keep** | Add explicit fail-closed profiles: passive replay, decision-holdout, dry-run, and live-armed. Profile resolution must be visible in the evidence. |
| DeepSeek “model-visible means logged” | **Keep now** | Record a request SHA-256, byte size, token usage and latency, without retaining raw prompt text in incidental telemetry. The provider now exposes these fields. |
| DeepSeek package-owned invariants | **Keep now** | Assert real relationships: candidate identity, frame freshness, guard authorization, `DISPATCHED != VERIFIED`, and checkpoint occurrence. Existing graph tests remain the authority. |
| DeepSeek compaction/pruning | **Defer** | GATHER requests are intentionally small. Add compaction only after a measured context-pressure failure; it must preserve raw evidence and typed provenance. |
| Generic shell/filesystem/computer-use/subagent stack | **Reject** | It violates the local-LLM boundary and the one-user direct-host safety model. No model-generated coordinates, tools or input. |
| Copying Pi/dsh source wholesale | **Reject for now** | The projects are useful references, but their runtimes and trust models do not match the Python/Windows graph. Reuse contracts and tests, not a parallel framework. |

## Benchmark contract

The benchmark must hold the following fixed: model artifact/quantization,
endpoint, sampling, CPU limits, mission case, capture/OCR hashes, candidate
order policy and acceptance oracle.  Only the harness variant changes.  Run
frame-disjoint replay cases with no live input; counterbalance or seed the order
to avoid warm-cache/order effects; repeat each case at least three times for a
pilot.  A result is not a success merely because the model returned JSON.

Record these separately:

1. bounded-choice accuracy and safe abstention;
2. invalid-choice rejection and transport/timeout failures;
3. fresh-frame `VERIFIED` completion versus merely `DISPATCHED`;
4. input emitted (must be zero in replay), request bytes/tokens, model latency,
   harness latency, CPU time, RAM and replay determinism.

The exact acceptance rules are in
`config/harness_benchmark_matrix.json`.  The current G3 holdout remains
`measured_pending_reviewer`; this document does not promote it.  G2's CPU/OCR
corpus is now R1a-ready, while optional runtime promotion remains separate.

The first offline comparison is now reproducible with
`scripts/run_harness_tax_benchmark.py` over the 12-case frame-disjoint holdout
(`workspace/evidence/local_llm/harness-tax-benchmark-latest.json`). H0 safely
abstains on all 12 ambiguous cases with zero invented choices; H1 reproduces
12/12 bounded semantic choices. This is a harness/model screening result,
not a verified live completion claim. Provider request bytes/fingerprint and
CPU/RAM counters are retained as `null` when the historical holdout artifact
does not contain them.

A single live loopback canary then exposed a useful boundary condition. With
the historical 256-token cap, GPT-OSS consumed the cap in reasoning and
returned empty JSON content; the selector failed closed and emitted no input
(`workspace/evidence/local_llm/local-llm-tax-live-20260919-01.json`). A second
observation-only run using a separate 512-token experiment profile produced
the expected existing candidate, with request bytes and digest recorded, in
44.0 seconds and 279 completion tokens
(`workspace/evidence/local_llm/local-llm-tax-live-20260919-03b.json`). This is
not a production-default change or a promotion claim: the enabled profile
remains opt-in, and the failure evidence is retained because a bounded local
model must fail closed when its response budget is insufficient.

## Graph handoff

```text
owned_nodes: harness_comparison_protocol
upstream_dependencies: game_state_mission_matrix, observation_corpus_holdout, local_decision_provider
downstream_consumers: goal_readiness_audit, future local-LLM benchmark runner
acceptance_evidence: config/harness_benchmark_matrix.json, scripts/run_harness_tax_benchmark.py, tests/test_harness_benchmark_contract.py, tests/test_harness_tax_benchmark.py, workspace/evidence/local_llm/harness-tax-benchmark-latest.json
known_blockers: G3 still needs independent review and a live postcondition; optional OCR runtime promotion; R3 repetition
graph_delta_expected: add a partial comparison/measurement node; do not change the runtime action authority
```
