# Mission occurrence ledger

`harness/mission_ledger.py` supplies a deterministic daily occurrence and restart ledger. A plan names a fixed UTC offset, local due time, bounded attempts/backoff, and scene target for each step. The occurrence ID is `mission_id:local-date`, so repeated ticks and process restarts reopen the same occurrence.

The CLI reads an existing observer `scene.json` without importing its implementation:

```powershell
python scripts/mission_tick.py --plan workspace/runs/ledger-demo/plan.json --scene workspace/runs/g005-live-e2e-repair1/scene.json --ledger workspace/runs/ledger-demo/ledger.json --now 2026-09-14T02:00:00Z
```

Ticks only write a typed proposal with `issued: false`. A missing or ambiguous target yields `NEEDS_DECISION`, bounded backoff, then `FAILED`. `--cancel` records `CANCELLED`. No background schedule is installed.

`VERIFIED` requires a separate receipt with the exact mission, occurrence, step, proposal before-frame reference, and a distinct after-frame reference. The CLI reloads both scene files from `workspace/runs` and requires their frame IDs and image hashes to equal the receipt, both when accepting the receipt and on every verified restart. A proposal alone, typed hashes without the scene files, a repeated tick, or an asserted checkpoint cannot complete a mission. Ledger persistence is atomic at tick boundaries; it is not an event database and cannot prove an action happened.
