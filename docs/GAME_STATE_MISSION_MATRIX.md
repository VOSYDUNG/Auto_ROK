# Auto_ROK game-state / mission matrix

Updated 2026-09-19 (Asia/Ho_Chi_Minh).

This is the bounded knowledge map for the current product. It records what
the harness is allowed to claim from observed frames and trained mission
contracts; it is not a claim that every Rise of Kingdoms screen or mission has
already been automated. A branch stays out of acceptance until its own
observation, policy, action and verification contract exists.

## Authority and status vocabulary

The trained transition source is [`config/mission_flows.yaml`](../config/mission_flows.yaml).
Observed state coverage comes from the CPU corpus and live evidence listed in
the engineering graph, plus the field-recon packets at
`workspace/evidence/recon/recon-preflight-20260919-01/` and
`workspace/evidence/recon/recon-goal-20260919-02/`. `covered` means the current harness has a tested,
proven path; `partial` means the path exists but an acceptance gate remains;
`training_only` means the transition is a hypothesis or training material;
`not_covered_end_to_end` means it is deliberately outside the current
vertical slice. `UNKNOWN_STATE` and `NEEDS_DECISION` are runtime outcomes, not
permission to guess.

## GATHER_RESOURCE state matrix (active vertical slice)

| State / family | Evidence the harness may use | Allowed semantic actions | Expected next state / postcondition | Status and remaining proof |
|---|---|---|---|---|
| `CITY_VIEW` | CPU signature and current-frame provenance; corpus state exact match is 30/30 overall | `TOGGLE_CITY_MAP` | `WORLD_MAP_VIEW` | Covered for the trained 1366×768 client profile; live capture remains frame-bound. |
| `WORLD_MAP_VIEW` | CPU signature plus fresh HWND/PID/frame identity | `OPEN_SEARCH` | `RESOURCE_SEARCH_PANEL` | Covered as a trained transition; stale or ambiguous view is held. |
| `RESOURCE_SEARCH_PANEL` | `Barbarians`/`Level:` anchor, bounded category/level ROIs, OCR decisions | `SELECT_RESOURCE_TYPE`, optional `SET_RESOURCE_LEVEL`, `SEARCH_RESOURCE_NODE` | panel remains open, then `RESOURCE_POINT_DETAIL` | Corpus-ready: the canonical Windows OCR path remains a 22/60 diagnostic baseline, while the independently locked RapidOCR overlay reaches 56/60 OCR-only (0.9333 recall, 1.0 precision). Runtime promotion remains a separate proof. |
| `RESOURCE_POINT_DETAIL` | Fresh target/scene binding for the selected node and resource level | `GATHER_RESOURCE_NODE` | `TROOP_DISPATCH_DRAWER` | Training contract exists; a fresh target must be grounded before input. |
| `TROOP_DISPATCH_DRAWER` | Visible drawer and current occurrence identity | `CREATE_NEW_TROOP` | `NEW_TROOP_SETUP` | Covered in the safe recon and fresh `gather-goal-20260919-04`; dispatch receipt is not success. |
| `NEW_TROOP_SETUP` | Current visible commander/troop selection plus occurrence-bound approval | `MARCH_WITH_CURRENT_SELECTION` | `MARCH_IN_PROGRESS` or `WORLD_MAP_VIEW` | Fresh bounded E2E passed for `gather-goal-20260919-04`; the `Units` OCR holdout is repaired by a frame-bound crop. Unknown composition or owner/gatherer policy remains a hold. |
| `MARCH_IN_PROGRESS` | Fresh queue ROI (`visible_ocr_march_queue_region`) and same character identity | none; verify only | `COMPLETE` only when queue used count increases relative to the pre-dispatch baseline | One live Queue +1 proof passed. A receipt, route line or stale frame alone is not completion. |
| `UNKNOWN_STATE` | No trusted state projection | none | fresh observe or operator decision | Always fail closed; never select a coordinate or action. |
| `NEEDS_DECISION` | More than one already-grounded candidate or unresolved policy | local model may choose one existing candidate, otherwise abstain | candidate re-enters normal policy/guard path | Local LLM is a bounded chooser only; it cannot create state, target, policy or input. |

The transition authority is deterministic: the current classified state
selects outgoing actions from the mission contract. A model response can only
select from that already-filtered set and never changes the expected
postcondition.

## Latest live safe-pass observations

The 2026-09-19 direct-host packet confirms the following concrete chain on the
1366x768 client: `WORLD_MAP_VIEW` → native `F` → `RESOURCE_SEARCH_PANEL`
(`Cropland`, Level 6) → `SEARCH` → `RESOURCE_POINT_DETAIL` (Cropland Level 6,
reserves 1,260,000, gatherer `None`) → `GATHER` → `TROOP_DISPATCH_DRAWER`
(`Queue 1/5`, `New Troop`, 34,245 visible troops) → `Escape` safe close. The
queue is an existing baseline, not a new completion proof; `MARCH` was never
pressed. Launch/login, city view, march confirmation and recovery/unknown
states are represented as explicit `not_observed` records in
`workspace/evidence/recon/recon-goal-20260919-02/` and must not be inferred.

The subsequent bounded E2E occurrence `gather-goal-20260919-04` used the same
trained chain with FOOD/Level 6, opened `New Troop`, approved the visible
commander/troop selection for that exact occurrence, and dispatched one MARCH.
Fresh queue evidence verified `1/5 → 2/5`; no second MARCH was emitted.

## Observed state inventory outside the active mission

These states are present in the operator-trained UI registry
([`config/ui_states.yaml`](../config/ui_states.yaml)). Their presence in the
registry is game knowledge, not end-to-end mission acceptance.

| State / family | What is known from the trained frame | Product use and boundary |
|---|---|---|
| `MAIN_GAME_VIEW` | Family containing `CITY_VIEW` and `WORLD_MAP_VIEW`; top HUD and primary navigation are stable | Entry/return family for missions; do not treat family membership as a precise state when an action needs a view-specific anchor. |
| `KINGDOM_OVERVIEW` | Strategic map, region names, passes/structures, `Battle List` and `Filter` | Observation-only training; no accepted mission or action contract. |
| `SETTINGS_CONTROLS_MOUSE` | Settings/Controls/Mouse with cursor-size and mouse behavior facts | Calibration/reference only; no mission action. |
| `SETTINGS_CONTROLS_SHORTCUTS` | Settings/Controls/Shortcuts and native shortcut table | Source for shortcut hypotheses; a shortcut is not a target authorization. |
| `GOVERNOR_PROFILE` | Governor, civilization, alliance, power and kill-point facts | Identity observation; no account switch or action permission. |
| `ACCOUNT_CHARACTER_LIST` | Star/normal character cards and current-character checkmark | Trained entry for `SWITCH_CHARACTER`; end-to-end switching is not accepted yet. |
| `CHARACTER_LOGIN_CONFIRM` | “Log in as this character?” with `NO`/`YES` | Trained confirmation state; requires occurrence-bound approval and asynchronous fresh main-view verification. |
| `ALLIANCE_HOME` | Alliance shell with Territory, War, Holy Sites, Help and Gifts features | Trained entry for alliance maintenance; no automatic claim is accepted. |
| `ALLIANCE_TERRITORY` | Territory Resource Earnings and `Claim` surface | Before-claim evidence exists; exact after-claim detector is missing. |
| `MAIL_WINDOW` | Mail shell with Personal, Report, Alliance, System, Sent and Favorites tabs | Observation surface only; mail actions have no product contract yet. |
| `MAIL_SYSTEM` | System mail list/detail and claim availability | Read/claim behavior is not an accepted mission. |
| `MAIL_ALLIANCE` | Alliance messages and event-related message facts | Candidate input for future event coordination; no action inference. |
| `MAIL_PERSONAL_EMPTY` | Personal tab with “No messages.” | Negative observation; no action. |
| `EVENTS_WINDOW` | Event list/detail layout, dates, windows, countdowns and badges | Observation surface; values are time-bound facts, not permanent rules. |
| `EVENT_CHAMPIONS_OF_OLYMPIA` | Event detail with `UNRANKED`/`RANKED` and observed time windows | One observed example only; event automation is not covered. |

## Fixed ROI and signal pipeline

The current trained 1366×768 client profile uses client-relative CPU regions:

| ROI / signal | Client rectangle | Owner | Meaning |
|---|---:|---|---|
| `signature_canvas` | `[109, 61, 1148, 614]` | CPU visual detector | City/world signature; resize or lighting outside the trained profile fails closed. |
| `ocr_march_queue_region` | Logical ROI `[1240, 110, 125, 50]`; runtime acquisition crop `[1200, 90, 166, 100]`, with optional narrow CPU fallback `[1275, 120, 91, 30]` | Windows OCR adapter / bounded CPU fallback | Queue count such as `1/5`; plain ratios are accepted only with this provenance. The enlarged crop is an acquisition window, not an action coordinate. |
| `ocr_new_troop_summary_region` | Runtime acquisition crop `[600, 450, 435, 185]` at scale 4 | Windows OCR adapter | Repairs the small `Units` label holdout in `NEW_TROOP_SETUP`; boxes are deduplicated and remain current-frame evidence, never click permission. |
| Search panel/category crops | Declared in `scripts/windows_ocr.ps1`, `config/cpu_rois.yaml` and optional `harness/rapidocr_fixed_roi.py` | OCR adapter | Bounded anchors and diagnostic layout enrichment; not desktop click coordinates. RapidOCR is opt-in and remains unpromoted. |
| Resource-level control | Profiled typed control | `resource_level_control` | Produces a typed current-frame target only after state/anchor checks. |

The signal path is:

```text
current HWND frame
  -> hash/geometry/freshness
  -> fixed CPU ROI + Windows OCR
  -> observation projection / target provenance
  -> state and fact classification
  -> deterministic candidate filtering
  -> policy / occurrence approval
  -> guarded semantic action (if armed)
  -> fresh frame and typed verification
  -> checkpoint + immutable evidence
```

An ROI narrows computation; it never grants permission to click. Bounding
boxes expire on frame, geometry, state or target changes.

## Mission / branch matrix

| Mission or branch | Trained entry / state family | Completion contract | Current coverage | Required next evidence |
|---|---|---|---|---|
| `GATHER_RESOURCE` | `CITY_VIEW` or `WORLD_MAP_VIEW` through search, node detail and troop setup | `march_queue_used` increases relative to the fresh pre-dispatch baseline | Current bounded E2E passed; R3 registered set remains 2/10 | Eight additional live occurrences after explicit endurance authorization, with at least seven successes, then the registered scenario set. |
| `SWITCH_CHARACTER` | `ACCOUNT_CHARACTER_LIST` → `CHARACTER_LOGIN_CONFIRM` → main game shell | Fresh main-game state after asynchronous load | Not covered end-to-end | Capture and label both cards/login confirmation and prove occurrence-bound approval plus post-load verification. |
| `CLAIM_ALLIANCE_TERRITORY_RSS` | `MAIN_GAME_VIEW` → `ALLIANCE_HOME` → `ALLIANCE_TERRITORY` | Exact post-claim signature | Training only | Supply a fresh after-claim frame and train a completion detector; no claim from the before frame. |
| `BARBARIAN_FORT_RALLY` | No accepted product contract | Not defined | Training only | Define states, target grounding, policy and a fresh completion fact before implementation. |
| `EVENT_COORDINATION` | No accepted product contract | Not defined | Not covered end-to-end | Define a separate mission contract and evidence corpus; do not inherit GATHER policy. |
| `GPT_OSS_DECISION_PROVIDER` | Harness `NEEDS_DECISION` edge | Exact existing `ActionChoice` or `NEEDS_DECISION` | Partial; 12/12 frame-disjoint holdout measured, promotion pending reviewer | Independent review and a live postcondition proof at a real ambiguous branch. |
| `MISSION_SCHEDULER` | Offline data-driven timeline only | Reset/cooldown/event-window/queue due signals and SQLite fact provenance | Partial | No unattended live action; direct-host mission branches still need their own observation, policy and verification gates. |

## Harness ownership boundary

| Signal or responsibility | Harness authority | Local LLM visibility |
|---|---|---|
| Capture, HWND/PID/geometry, image hash and freshness | `live_capture`, `observation_projection` | Only symbolic provenance fields |
| Fixed client ROIs, CPU signature, OCR and target grounding | `windows_ocr`, `ocr_semantics`, visual detector and profiles | No raw desktop or free-form coordinates |
| State classification and outgoing candidate set | `state_classifier`, `state_adapter`, `deterministic_selector` | Current state, facts and existing candidate IDs only |
| Mission policy, troop approval, occurrence binding | mission contract, policy overlay and approval artifacts | No policy creation or override |
| Input isolation and guarded actuation | interference guard, screen mapping and Windows input adapter | No mouse/keyboard/tool surface |
| Post-action verification, checkpoint, recovery and evidence | engine, runner, store and runtime evidence | Never reports success; harness verifies it |

## Acceptance snapshot

| Gate | Current result | Evidence interpretation |
|---|---|---|
| G1 direct-host isolation | Pass for current occurrence | Target binding, foreground/integrity checks, stale-frame and zero-unintended-input trace are present. |
| G2 CPU/OCR/state R1a | Pass for locked corpus; runtime promotion pending | Independent visual review locks 12 frame/hash-bound search panels; RapidOCR overlay reaches 1.0 precision / 0.9333 OCR-only recall and 30/30 observation projections. The optional runtime backend still needs a fresh visible live remeasurement. |
| G3 local-LLM holdout | Measured, promotion pending | 12/12 bounded choices and zero input; reviewer acceptance is still required. |
| G4 B003 occurrence approval | Pass for current occurrence | Approval is bound to mission, run, character and visible selection; it cannot be reused. |
| G5 live GATHER postcondition | Pass for current occurrence | Queue used +1 was read from a fresh queue ROI after `gather-goal-20260919-04`; no duplicate input was emitted during delayed verification. |
| G6 endurance | Blocked | R3 has 2/10 registered and 2/9 required successes; explicit authorization for the remaining live repetitions is outstanding. |

## Evidence discipline and next edge

The next valid edge is the optional runtime backend remeasurement:
`observation_corpus_holdout → rapidocr_fixed_roi_backend → observation_projection`.
Until that edge is accepted, the Windows OCR path remains the default and the
RapidOCR overlay cannot silently change runtime grounding. No live input is
required to make this documentation progress, and no new live occurrence
should be replayed merely to improve a screening metric.

Graph handoff:

```text
owned_nodes: game_state_mission_matrix
upstream_dependencies: mission_contract, observation_corpus_holdout, live_replay_evidence
downstream_consumers: mission_engine, deterministic_selector, local_decision_provider, goal_readiness_audit
acceptance_evidence: docs/GAME_STATE_MISSION_MATRIX.md, python scripts/validate_engineering_graph.py
known_blockers: optional runtime backend acceptance; G3 promotion review; R3 repetition validator is 2/10; explicit endurance authorization
graph_delta_expected: keep the scoped state/mission knowledge map and current live occurrence evidence synchronized
```
