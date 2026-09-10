# Standing demo

The local demo tells one story: remember a decision, change the fact that
justified it, block dependent code, preserve the timeline, and replace the
expired decision.

## Start it

From the repository root:

```sh
date -u
git rev-parse --short HEAD
PROOF_DB=./standing-proof.db
.venv/bin/standing --memory-path "$PROOF_DB" demo-seed
.venv/bin/standing --memory-path "$PROOF_DB" boot
.venv/bin/standing --memory-path "$PROOF_DB" review src/archive.py
.venv/bin/standing dashboard --demo
```

The first command writes the controlled state and exits. The next two commands
are new OS processes that must recall the decision and block from the same
Sibyl-backed database. The dashboard then uses a separate temporary database;
it does not mutate the proof database.

Open `http://127.0.0.1:8787/`.

The page begins with:

```text
ACME-001 — STANDS
Use Acme because retention >= 365 days
Current: 365 days
```

The page always displays:

```text
CONTROLLED DEMO — Fictional Acme Corporation.
This control replays the source-change path locally; the separately completed
ACP → source extraction → Base EAS path is linked below.
```

## Walkthrough

1. Use the time-travel slider to compare `valid_as_of` and `known_as_of`.
2. Press **BREAK DEMO ASSUMPTION**. This constrained control deterministically
   replays the source change from 365 to 90 days locally, and the evidence
   chain retains both effective periods. It does not claim to start a new live
   ACP job.
3. Inspect the decision graph and provenance entries. The evaluator changes
   ACME-001 to `EXPIRED`; the exact `src/archive.py` path is shown as blocked.
4. Toggle **MEMORY OFF**. The external fact remains visible, but no governing
   decision or original assumption is recovered. The UI calls the historical
   protection unavailable rather than fabricating an approval.
5. Press **INSPECT DEMO WAIVER**. This is a preview only; no waiver is issued
   and no model action can approve one.
6. Press **RECORD REPLACEMENT DECISION**. ACME-001 becomes `SUPERSEDED` and
   STORAGE-002 becomes the active replacement. The old decision remains in
   history.
7. Press **RUN REVIEW AGAIN** and inspect the replacement's `STANDS` result.
8. Open **Live partner proof** and follow the completed Virtuals ACP job, Base
   EAS observation, and ERC-8004 feedback links. Those records prove the
   separate live source-extraction and onchain transport path.

**RESTORE DEMO** is a reset control for another run. It is not needed after the
replacement decision completes the story.

The public buttons are pre-authored local workflow actions. They do not accept
a destination address, calldata, value, schema, source URL, amount, or private
key from the browser.

## CLI proof

The deletion comparison runs the same changed-path scenario against a seeded
store and an empty store:

```sh
.venv/bin/standing deletion-test
```

Temporal evidence can be inspected directly:

```sh
.venv/bin/standing history vendor.acme.retention_days
.venv/bin/standing condition vendor.acme.retention_days --valid-as-of 2026-03-03
.venv/bin/standing condition vendor.acme.retention_days --known-as-of 2026-03-03
.venv/bin/standing decision current src/archive.py
```

## Disclosure

This is a deterministic controlled demonstration, not the real-world proof
case. The repository contains three operator-reviewed, source-linked real-world
cases. Production trust requirements are documented separately in the trust
model and limitations; they should not interrupt the product walkthrough.
