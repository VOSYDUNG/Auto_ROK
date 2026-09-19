# Game field reconnaissance

This packet is the first phase of the active Goal. It records what is actually
visible in one real Rise of Kingdoms client before we freeze the next harness
contract. It is not a mission runner and it is not permission to dispatch a
march.

## Survey boundary

The survey uses one direct Windows host, one visible elevated `MASS.exe`, CPU/RAM
capture and fixed client geometry. It may inspect safe panels and return to a
known safe state. It must not press `MARCH`, spend resources, use speedups,
change account/character, send chat, submit a form or otherwise create an
irreversible game-side effect. If a transition is not observed, record
`UNKNOWN_STATE` or `NEEDS_DECISION`; do not infer it from a label or old frame.

The required states and fields are machine-readable in
`config/game_field_reconnaissance_plan.json`.

## Capture packet

Each state gets one directory under
`workspace/evidence/recon/<survey-id>/<state-id>/` containing:

- `rok-client.png` — the bounded client image;
- `capture.json` — HWND/PID, geometry, frame id, hash and capture time;
- `ocr.json` or equivalent semantic extraction, when available;
- `observation.json` — visible labels, landmarks/ROI candidates, safe entry and
  exit, observed transitions, side effects, unknowns and confidence.

The image hash and frame id are the provenance edge. A screenshot without those
fields is a note, not acceptance evidence. Keep capture time separate from
ingestion time, and preserve unavailable telemetry as `null`.

## Distillation output

After the single survey pass, distill only confirmed observations into:

1. `docs/GAME_STATE_MISSION_MATRIX.md` for state/transition scope;
2. the relevant ROI/profile or mission contract when a new producer and
   consumer are both identified;
3. a short list of explicit unknowns and operator decisions still required.

Do not add a coordinate, action, completion criterion or local-LLM candidate
merely because it looks plausible. The harness owns grounding, policy,
approval, actuation and verification; the local model receives only the
already-filtered semantic candidates.

## Handoff gate

Reconnaissance is complete only when every planned state has a capture packet or
an explicit `not_observed` reason, the matrix is updated, and the graph points
to the packet as evidence. Only then do we resume E2E testing of the compiled
`GATHER_RESOURCE` slice.

## Latest safe packet

`workspace/evidence/recon/recon-goal-20260919-02/` records a bounded live
pass with CPU/RAM frame provenance. It covers `CITY_VIEW`, `WORLD_MAP_VIEW`,
`RESOURCE_SEARCH_PANEL`, `RESOURCE_LEVEL_CONTROL`, `RESOURCE_NODE_DETAIL`,
`TROOP_DRAWER` and a safe queue baseline. `LAUNCH_OR_SETTLED`,
`MARCH_CONFIRMATION` and `RECOVERY_OR_UNKNOWN` are explicit `not_observed`
records; they are not inferred from historical screenshots. The packet ends on
a clean world-map baseline and contains no MARCH input.
