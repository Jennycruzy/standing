# Standing product walkthrough

This walkthrough tells one product story: Standing remembers a decision,
tracks the fact behind it, blocks code when that fact expires, preserves the
timeline, and records the replacement decision.

## Start it

From the repository root:

```sh
date -u
git rev-parse --short HEAD
PROOF_DB=./standing-proof.db
.venv/bin/standing --memory-path "$PROOF_DB" proof-seed
.venv/bin/standing --memory-path "$PROOF_DB" boot
.venv/bin/standing --memory-path "$PROOF_DB" review src/archive.py
.venv/bin/standing dashboard --sandbox
```

`proof-seed`, `boot`, and `review` are separate OS processes. The first writes
the controlled state; the next processes reconstruct it from the same
Sibyl-backed store. The dashboard then uses a separate isolated sandbox store;
it does not mutate the proof database.

Open `http://127.0.0.1:8787/` for the product landing page, then open
`http://127.0.0.1:8787/console` for the interactive console.

The page begins with:

```text
ACME-001 — STANDS
Use Acme because retention >= 365 days
Current: 365 days
```

The page always displays:

```text
CONTROLLED SCENARIO — FICTIONAL ACME
This sandbox uses fictional Acme data operated by Standing so the lifecycle
can be reproduced safely. The control replays the source change locally.
Completed Virtuals ACP → source extraction → Base EAS records are shown
separately as live historical proof.
```

## Walkthrough

1. Use the time-travel slider to compare `valid_as_of` and `known_as_of`.
2. Open **Sandbox** and press **BREAK ASSUMPTION**. This fixed control
   deterministically replays the source change from 365 to 90 days locally,
   and the evidence chain retains both effective periods. It does not claim to
   start a new ACP job.
3. Inspect the decision graph and provenance entries. The evaluator changes
   ACME-001 to `EXPIRED`; the exact `src/archive.py` path is shown as blocked.
4. Press **RUN MEMORY PROOF**. The backend runs the same changed-path review
   with Sibyl present and with a fresh empty store. The fact remains visible,
   but no governing decision or original assumption is recovered in the second
   arm. The UI calls the historical protection unavailable rather than
   fabricating an approval.
5. Press **VIEW WAIVER POLICY**. This is a preview only; no waiver is issued
   and no model action can approve one.
6. Press **RECORD REPLACEMENT DECISION**. ACME-001 becomes `SUPERSEDED` and
   STORAGE-002 becomes the active replacement. The old decision remains in
   history.
7. Press **RUN REVIEW AGAIN** and inspect the replacement's `STANDS` result.
8. Open **Live partner proof** and follow the completed Virtuals ACP job, Base
   EAS observation, and ERC-8004 feedback links. Those records prove the
   separate live source-extraction and onchain transport path.

**RESET SANDBOX** is a reset control for another run. It is not needed after the
replacement decision completes the story.

The public buttons are pre-authored local workflow actions. They do not accept
a destination address, calldata, value, schema, source URL, amount, or private
key from the browser.

## CLI proof

The deletion comparison runs the same changed-path scenario against a seeded
store and an empty store:

```sh
.venv/bin/standing memory-proof
```

Temporal evidence can be inspected directly:

```sh
.venv/bin/standing history vendor.acme.retention_days
.venv/bin/standing condition vendor.acme.retention_days --valid-as-of 2026-03-03
.venv/bin/standing condition vendor.acme.retention_days --known-as-of 2026-03-03
.venv/bin/standing decision current src/archive.py
```

## Disclosure

This is a deterministic controlled scenario, not the real-world proof
case. The repository contains three human-reviewed, source-linked real-world
cases. Production trust requirements are documented separately in the trust
model and limitations; they should not interrupt the product walkthrough.
