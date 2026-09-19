# Auto_ROK — Goal

## Product goal

Build and validate a CPU/RAM-only Auto_ROK harness for one real Windows
machine, one signed-in user and one visible Rise of Kingdoms client. Docker,
virtual machines and Hyper-V are explicitly out of scope.

The harness is the product around which the local LLM is trained and tested.
It must turn a bounded game situation into a small, trustworthy decision
problem, execute only a guarded action, and prove the visible result. The
system is successful only when that loop is deterministic, measurable and
fail-closed.

## Local-LLM user story

When the harness has a fresh, provenance-bound observation and more than one
valid next step, the local LLM receives only the minimal structured context
and the already-filtered candidate actions. It selects exactly one existing
`ActionChoice`, or returns `NEEDS_DECISION` when the evidence is insufficient.
The model never sees an unrestricted desktop-control surface, never invents
coordinates, and never sends mouse or keyboard input.

The target model is a local Qwen or GPT-OSS class model. Its reasoning is a
small decision edge (approximately 10–20% of the loop); deterministic harness
logic owns the remaining work and all safety decisions.

The local model service is kept available as an idle observer. “Always on”
does not mean “always assigned a mission”: the harness sends a bounded packet
only for a real `NEEDS_DECISION`/`UNKNOWN_STATE` signal. The model may choose an
existing candidate, abstain, or report a changed game surface; it cannot own a
clock, schedule, completion flag, currency spend or input dispatch.

## Harness contract

The harness owns:

- fixed, trained client ROIs and CPU-only capture/perception;
- OCR/CV, state projection and frame provenance;
- mission graph, policy and candidate filtering;
- target grounding, input isolation and guarded actuation;
- occurrence-bound approvals, checkpoints, retry/recovery and cancellation;
- fresh postcondition verification and immutable evidence.
- data-driven mission timeline and a local knowledge store for reset,
  cooldown, event-window and queue-driven task facts.

Coordinates are an observation/performance constraint, not permission to click.
Every action must still be grounded to the current frame, current occurrence
and current approval state.

## First accepted slice

Ship one-character `GATHER_RESOURCE` as the reference vertical slice. Keep
other missions out of acceptance until they have their own observation,
policy, action and verification contracts. Use `scripts/run_autorok.py` as the
canonical entrypoint; legacy Python scripts remain historical evidence only.
The evidence-bounded state and mission inventory is maintained in
[`docs/GAME_STATE_MISSION_MATRIX.md`](GAME_STATE_MISSION_MATRIX.md); it is the
scope guard for understanding the game without promoting unverified branches.

## Active phase — reconnaissance frozen for GATHER; bounded E2E verified

Before adding another action or claiming end-to-end coverage, run one bounded
field-recon pass over the visible ROK client. The pass collects screenshots and
capture metadata for the planned states in
[`config/game_field_reconnaissance_plan.json`](../config/game_field_reconnaissance_plan.json),
then distills only observed labels, landmarks, transitions, side effects and
unknowns into [`docs/GAME_FIELD_RECONNAISSANCE.md`](GAME_FIELD_RECONNAISSANCE.md)
and the state/mission matrix. This is game knowledge acquisition, not a live
mission run.

Reconnaissance may open and close safe panels and inspect controls, but it must
not press MARCH, spend resources, use speedups, change account/character,
send chat or submit any irreversible action. Every capture remains bound to the
real client frame; unobserved behavior stays `UNKNOWN_STATE` or `NEEDS_DECISION`.
Only after the survey packet is complete do we freeze the knowledge map and
resume E2E tests against the compiled harness.

The latest bounded safe pass is
`workspace/evidence/recon/recon-goal-20260919-02/`. It observed the live city
and world-map, resource-search, level-control, node-detail and troop-drawer
path, and explicitly records launch/login, march-confirmation and recovery as
`not_observed` rather than inferring them. The packet is useful field evidence,
and is now the knowledge boundary for the accepted GATHER slice. Those three
unobserved states remain outside the product claim.

After that safe pass, a fresh bounded occurrence
`gather-goal-20260919-04` completed the compiled CPU-only path on the real
elevated `MASS.exe`: `WORLD_MAP_VIEW` → search → Level 6 FOOD node → troop
setup → occurrence-bound MARCH. The fresh queue proof is `1/5 → 2/5`, with
target/foreground guards, a verified receipt and immutable evidence. The live
path exposed a Windows OCR holdout for the small `Units` label; a fixed CPU
crop plus duplicate-box rejection was added to `scripts/windows_ocr.ps1` and
verified on the same frame before MARCH.

The next product layer is implemented as an offline/data-driven mission
inventory. `config/mission_layer.yaml` and `harness/mission_timeline.py` model
the single `00:00 UTC`/`07:00 Vietnam` reset, VIP tasks, Courier Station event
windows, continuous farm queue returns and 30-minute alliance contribution
cooldown (maximum 20 per reset). `harness/mission_knowledge.py` persists
time-bounded semantic facts and change/retraining signals in SQLite. The five
case acceptance artifact is
`workspace/evidence/mission_layer/acceptance-latest.json`; it passes without
emitting game input.

## Definition of done

Acceptance proceeds in this order:

1. Complete the bounded field-recon survey and freeze the evidence-bounded
   state/mission knowledge map.
2. Direct-host input isolation and passive capture are evidenced on the real
   Windows desktop, including target binding, stale-frame rejection,
   cancellation/recovery and zero unintended input.
3. CPU/corpus and OCR/state holdouts meet their measured thresholds without
   changing runtime grounding to fuzzy or GPU-dependent behavior.
4. The local-LLM `NEEDS_DECISION` contract is measured on frame-disjoint
   holdout cases; transport success alone is not acceptance.
5. B003 approval is explicitly bound to the current mission occurrence,
   character and visible troop/commander selection.
6. One bounded live GATHER tick proves the visible postcondition `Queue used
   +1`, with cancel/resume/recovery evidence and no out-of-scope replay. **Met
   for the current occurrence; R3 endurance is still separate.**
7. The data-driven mission layer passes its five offline acceptance cases and
   records semantic facts before any new live mission branch is armed. **Met.**
8. Only after the preceding gates pass may endurance testing begin.

Any stale, missing, ambiguous, mismatched or unverifiable evidence stops the
loop. No live input is emitted before the relevant gate and approval are
present.

R3 repetition is separately operator-authorized: the readiness audit accepts
only `workspace/evidence/gather/R3_ENDURANCE_AUTHORIZATION.json` scoped to the
active GATHER occurrence contract and bounded by `max_additional_runs`.
Per-tick runtime evidence is append-only; a generated-path collision fails
closed instead of overwriting an earlier record.

## Non-goals

- no Docker, VM, Hyper-V or GPU execution path;
- no unrestricted autonomous desktop agent;
- no process-memory reading or game injection;
- no acceptance based only on HTTP/model transport, a dispatch receipt, or a
  generic OCR ratio;
- no reuse of an old approval or replay outside the current occurrence.
