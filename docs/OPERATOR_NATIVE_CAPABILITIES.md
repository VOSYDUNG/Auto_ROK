# AUTO_ROK Operator Native Capabilities

## Scope

The Operator Layer records native capabilities that are visibly available to a specific account. These are account facts, not workflow decisions.

AUTO_ROK should distinguish three different things:

1. **Advertised capability** — a store/offer visibly says the feature exists.
2. **Entitled capability** — the current account visibly has access to the feature.
3. **Mission usage decision** — a later runtime decides whether using the native feature is appropriate for the active mission.

These states must not be collapsed.

## Current trained commercial snapshot

An operator-provided screenshot on 2026-09-14 shows a visible `30-Day Gem Supply` offer with:

- observed price text: `USD 4.99`;
- visible validity: `30 Days`;
- reward text including `RECEIVE 2,200`;
- daily supply reset text at `00:00 UTC`;
- advertised exclusive features:
  - Auto Peacekeeping;
  - Auto Help;
  - Auto Translation.

This is stored as a dated offer snapshot. It is not a permanent price or permanent bundle contract.

## Operator acquisition target

The harness should later navigate visible UI and answer, for the current account:

```text
AUTO_PEACEKEEPING: enabled / disabled / unknown
AUTO_HELP: enabled / disabled / unknown
AUTO_TRANSLATION: enabled / disabled / unknown
```

Each observation must retain:

```text
observed_at
source_surface
confidence
entitlement_source (when visible)
```

## Why this belongs to Operator Layer

A native feature changes the capability envelope of the account. Two otherwise similar governors may expose different execution options because one account has an active entitlement and the other does not.

The Operator Layer therefore answers:

> What can this account natively do?

It does **not** answer:

> Which method should this mission use right now?

That second question belongs to mission/harness runtime after branch integration.

## Merge contract with Harness

Operator Layer should eventually export a compact context similar to:

```json
{
  "native_capabilities": {
    "AUTO_PEACEKEEPING": true,
    "AUTO_HELP": true
  },
  "advertised_native_capabilities": [
    "AUTO_PEACEKEEPING",
    "AUTO_HELP",
    "AUTO_TRANSLATION"
  ]
}
```

The harness may then expose native execution routes only when entitlement is actually observed.

Advertising alone must never unlock an execution route.
