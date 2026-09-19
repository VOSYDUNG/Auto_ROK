# Data-driven mission layer

`main.py` is retained as a historical reference only.  Its fixed coordinates,
character switching, `sleep(30)` calls and fixed resource order are not a
mission scheduler and are not imported into the canonical harness.

## Ownership

The harness owns the game graph, freshness, time arithmetic, preconditions,
semantic grounding, policy, guarded input, post-action observation and
verification.  The local LLM service is always-on as an observer, but receives
no mission stream by default.  It receives one bounded packet only when a
current signal is `NEEDS_DECISION` or `UNKNOWN_STATE`; it may choose from
existing candidates, abstain, or report that a trained surface changed.

The model never receives coordinates, HWND/PID, paths, screenshots or raw OCR.
It cannot schedule work, mark a task complete, spend currency, or turn
`DISPATCHED` into `VERIFIED`.

## Timeline and knowledge

`config/mission_layer.yaml` defines mission/task identities and cadence.  The
timeline in `harness/mission_timeline.py` derives signals from current semantic
facts:

- one daily boundary: `00:00 UTC`, displayed as `07:00 Asia/Ho_Chi_Minh`;
- interval tasks from `last_success_at`/`cooldown_until`, not a sleeping loop;
- event-window tasks from observed `next_refresh_at`/`window_expires_at`;
- continuous farm from queue slots and verified march `return_at` values;
- unknown or changed UI capability becomes `UNKNOWN_STATE`/`NEEDS_DECISION` and
  a retraining signal.

`harness/mission_knowledge.py` stores semantic facts, occurrence statuses,
change signals and evidence references in a local SQLite database.  Values are
time-bounded and remain absent after expiry; the store does not infer a fresh
state from an old frame.

`harness/mission_scheduler.py` is the caller-driven bridge: one tick records a
semantic fact packet, evaluates all task signals and returns only bounded
decision packets for unknown/ambiguous states. It has no action backend and no
sleep loop, so it can run while the local model is idle or unavailable.

## Farm timing rule

`compute_farm_plan` keeps mining completion separate from travel.  The effective
mining finish is the earliest of nominal gather completion, node depletion, buff
expiry and task deadline.  The return time adds travel-back; table productivity
counts only `mining_duration_seconds`.  This lets the scheduler refill a march
slot at the observed return boundary and prevents a hardcoded “8-hour” loop
from creating gaps.

## Current task inventory

The first data-driven inventory covers VIP claim, VIP gifts, Courier Station
free-claim plus a separately gated purchase review, continuous resource farming and alliance
contribution every 30 minutes up to 20 observed contributions per reset.  Paid
station items and live claims remain risk-bearing actions requiring their own
current-frame policy/approval; the offline acceptance does not spend or click.

Run the five non-interactive acceptance cases with:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python scripts/run_mission_layer_acceptance.py
```

The resulting artifact is
`workspace/evidence/mission_layer/acceptance-latest.json`.  It is a harness
readiness result, not evidence that the live game has executed every mission.

The first live deterministic pass is recorded in
`workspace/evidence/mission_layer/live-pass-20260919-01-report.json` and its
SQLite database. It observed the current `2/5` troop queue, two active march
ETAs, VIP claim surfaces, the completed Courier Station `5/5` daily trade
counter and Alliance badges. It intentionally emitted no gameplay input.
The contribution cooldown, exact Courier prices/free claim and boost expiry
remain unknown and therefore produce `UNKNOWN_STATE` decision packets.
