# Standing

> **Standing remembers why code was written and blocks changes when the facts
> that justified that code are no longer true.**

Software repositories preserve code, but usually lose the assumptions behind
it. A vendor changes a guarantee, an API is deprecated, or a policy expires—and
the code that depended on the old fact continues as if nothing happened.

Standing is a temporal system of record for engineering intent. It connects
decisions to their assumptions, external evidence, and governed code paths. It
revalidates stale facts and deterministically returns `STANDS`, `EXPIRED`,
`UNKNOWN`, or `CONTESTED` before a change is allowed.

```text
Decision     Use Acme for archives because retention >= 365 days
Then         365 days ✓
Now          90 days ✕
Changed code src/archive.py
Standing     EXPIRED — BLOCK
```

## Proof snapshot

- **Persistent memory:** separate processes reconstruct the decision and its
  governed path from Sibyl Memory.
- **Memory Proof:** the same review with a fresh store keeps the external fact
  but loses the remembered engineering reason and historical protection.
- **Public evidence:** three human-reviewed repository/vendor cases are kept
  separate from the controlled scenarios.
- **Live historical proof:** completed ACP job `77748`, source extraction, Base
  EAS observation, Sibyl readback, and ERC-8004 outcome are linked above.
- **Verification:** the repository carries temporal, reviewer, source-boundary,
  and adapter tests; [`make verify`](evidence/LATEST.md) records an immutable
  run artifact.

## Start here

[Open Standing](https://standing.onrender.com/) ·
[Open Console](https://standing.onrender.com/console) ·
[Product walkthrough](docs/WALKTHROUGH.md) ·
[Public evaluation](docs/EVALUATION.md) ·
[Source](https://github.com/Jennycruzy/standing) ·
[Run locally](#run-standing) ·
[Deploy](https://render.com/deploy?repo=https://github.com/Jennycruzy/standing) ·
[Architecture](docs/ARCHITECTURE.md) ·
[Trust model](docs/TRUST-MODEL.md) ·
[Evaluation](docs/EVALUATION.md)

Live integration evidence:

- [Virtuals ACP platform](https://app.virtuals.io/) — completed verifier job `77748` (the technical API record is credential-gated)
- [Virtuals ACP agent directory](https://app.virtuals.io/acp/agents) — `Standing Verifier` profile `139452` and `Standing Requestor` profile `139450`
- [ERC-8004 Standing identity registration](https://basescan.org/tx/0xb1a5586929a8b02fb6a4527551124ce290328eda684aa18a424a78e2de64e733) — agent ID `84973`
- [Base EAS observation transaction](https://basescan.org/tx/0xfa23b10158da3723d28508d51c8acd6916696cd0a609e4fce741c989e5573eff)
- [ERC-8004 verifier feedback transaction](https://basescan.org/tx/0xb12f670d1c643556b7bb6c45cec12462f9c7f7e41775681b4c1f9b0278146954)
- [Registered Base EAS schemas](docs/audits/schema-registration.md)
- [Complete verifier-loop audit](docs/audits/verifier-loop.md)

The public service is an engineering workspace, not a blockchain analytics
page. Start with the product finding at `/console`; the **Sandbox** navigation
item is the controlled Fictional Acme scenario, while **Evidence** contains the
separate live historical verification path.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Jennycruzy/standing)

## What makes Standing different

### It remembers engineering intent, not just text

A decision records its human-approved justification, conditions, source
artifact, and exact governed paths. Search retrieves candidates, but only exact
path validation can affect a review.

### It separates truth from knowledge

Every observation has two timelines:

- **Valid time:** when the fact was true in the outside world.
- **Knowledge time:** when Standing observed and recorded it.

That lets Standing answer both:

```text
What do we now believe was true on March 3?
What evidence did the team actually have on March 3?
```

Later evidence can correct reconstructed history without rewriting what the
team could reasonably have known at the time.

### It distinguishes change from conflict

`365 days → 90 days` across different effective periods is supersession, not a
dispute. Incompatible values for the same effective period are `CONTESTED`.
Canonical evidence selection accounts for effective time, supersession,
acceptance, source trust, revocation, validity, and knowledge time.

### It finishes the engineering lifecycle

```text
remember → verify → detect drift → block → waive or replace → supersede → allow
```

Old decisions and evidence remain historically queryable after replacement.

## Run Standing

Requirements: Python 3.12 and [`uv`](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/Jennycruzy/standing.git
cd standing
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python .
```

Start the isolated product workspace:

```sh
.venv/bin/standing boot
.venv/bin/standing dashboard --sandbox
```

Open `http://127.0.0.1:8787/` for the product landing page, then select
**Open console** or visit `http://127.0.0.1:8787/console` for the interactive
review surface.

Prove recall across separate processes with one persistent proof database:

```sh
PROOF_DB=./standing-proof.db
.venv/bin/standing --memory-path "$PROOF_DB" proof-seed
.venv/bin/standing --memory-path "$PROOF_DB" boot
.venv/bin/standing --memory-path "$PROOF_DB" review src/archive.py
```

Each invocation exits before the next begins. The final process blocks
`src/archive.py` using the decision and temporal evidence recalled from the
same Sibyl-backed store.

The console provides:

- the highest-priority current engineering finding;
- a code → decision → assumption → evidence → standing graph;
- bitemporal time travel for world truth and contemporaneous knowledge;
- exact-path PR review and explicit human confirmation;
- a backend comparison with memory present versus memory removed;
- evidence provenance and three reviewed real-world cases;
- fixed source-change, reset, waiver-policy, and replacement controls; and
- direct Virtuals ACP, Base EAS, and ERC-8004 proof links.

The Acme interaction is visibly labelled as a controlled fictional scenario.
The sandbox control replays the source change locally; it does not pretend to
start a new live transaction. Genuine verifier source extraction and the
ACP → Base EAS → Sibyl path are proven separately by the linked live records.
The fixed controls do not expose keys, arbitrary URLs, transaction destinations,
calldata, or spend amounts.

## The load-bearing memory proof

```sh
.venv/bin/standing memory-proof
```

```text
                         MEMORY PRESENT  MEMORY REMOVED
Decision found           ACME-001        none
Assumption recovered     >= 365 days     none
Current external fact    90 days         90 days
Expiry identified        yes             no
Protection               BLOCK           historical protection unavailable
```

The external fact survives memory removal. What disappears is the engineering
reason that connects the fact to the changed code. Without Sibyl, Standing cannot know
why that file depended on the vendor guarantee, so its core protection fails.

Critical memory paths:

- Writes: [`standing/memory.py`](standing/memory.py#L41)
- Fresh-process reads: [`standing/memory.py`](standing/memory.py#L47)
- Governed-path lookup: [`standing/memory.py`](standing/memory.py#L148)
- Archive and restore: [`standing/memory.py`](standing/memory.py#L163)
- Deletion proof: [`tests/test_memory.py`](tests/test_memory.py#L75)
- Review orchestration: [`standing/reviewer.py`](standing/reviewer.py#L59)

Sibyl stores confirmed decisions, assumptions, accepted condition references,
observer histories, standing-change journals, waivers, and supersession links.
A fresh process reconstructs the review from those records instead of relying
on conversation context.

## Temporal CLI

```sh
.venv/bin/standing review
.venv/bin/standing review --base main
.venv/bin/standing review --sample-pr 12
.venv/bin/standing history vendor.acme.retention_days
.venv/bin/standing condition vendor.acme.retention_days --valid-as-of 2026-03-03
.venv/bin/standing condition vendor.acme.retention_days --known-as-of 2026-03-03
.venv/bin/standing decision current src/archive.py
.venv/bin/standing waiver list
```

Unsupported required predicates return `UNKNOWN`; wrong units and untrusted
sources are rejected; expired waivers automatically restore the block.

## How verification works

```text
Changed code
    ↓
Decision recalled from Sibyl Memory
    ↓
Condition freshness checked
    ↓ stale or insufficient
Virtuals ACP hires verifier
    ↓
Verifier fetches the source and extracts the actual value
    ↓
Base EAS records the observation
    ↓
Temporal acceptance promotes the canonical condition
    ↓
Dependent decisions are re-evaluated
    ↓
ALLOW / BLOCK / HUMAN WAIVER / REPLACEMENT
```

The seller cannot publish a separately configured answer: its extraction code
validates the bound source, fetches it, extracts from JSON or HTML, validates
type and unit, records extraction metadata, and only then publishes the
observation. See [`acp-adapter/src/verifier.ts`](acp-adapter/src/verifier.ts)
and [`acp-adapter/src/extraction.ts`](acp-adapter/src/extraction.ts).

## Partner stack

| Stack | Product responsibility | Verifiable implementation |
| --- | --- | --- |
| Sibyl Memory | Persists intent across fresh processes and makes historical review possible | [`standing/memory.py`](standing/memory.py) |
| Virtuals ACP | Acquires fresh verification when evidence is stale or insufficient | [`standing/acp.py`](standing/acp.py), [ACP platform](https://app.virtuals.io/), job `77748` |
| Base EAS | Provides public observation identity, timestamps, references, and revocation state | [`standing/eas.py`](standing/eas.py), [observation transaction](https://basescan.org/tx/0xfa23b10158da3723d28508d51c8acd6916696cd0a609e4fce741c989e5573eff) |
| ERC-8004 | Records verifier outcomes for reputation history | [`standing/reputation.py`](standing/reputation.py), [feedback transaction](https://basescan.org/tx/0xb12f670d1c643556b7bb6c45cec12462f9c7f7e41775681b4c1f9b0278146954) |

## Evidence and evaluation

Standing keeps two evaluation sets separate:

- [Three human-reviewed real-world cases](docs/evaluation/cases.json), linking
  public engineering artifacts to primary vendor history.
- [Seventeen controlled adversarial cases](docs/evaluation/adversarial.json),
  covering supersession, same-period conflict, late evidence, wrong units,
  revocation, spoofed domains, stale evidence, unsupported predicates, exact-path
  false matches, waiver expiry, decision supersession, and memory deletion.

Real and controlled results are never merged into one score. The
[methodology](docs/EVALUATION.md), [review packet](docs/evaluation/REVIEW-PACKET.md),
and [trust model](docs/TRUST-MODEL.md) define the evidence boundaries.

## Verification

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
npm --prefix acp-adapter test
npm --prefix acp-adapter run typecheck
```

Current verified result: **152 Python tests and 9 TypeScript tests pass**, and
the TypeScript adapter passes `tsc --noEmit`.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Product walkthrough](docs/WALKTHROUGH.md)
- [Trust model](docs/TRUST-MODEL.md)
- [Evaluation methodology](docs/EVALUATION.md)
- [Limitations](docs/LIMITATIONS.md)

## Team

Built by **Jennycruzy** / **Jenny builds** for the Sibyl Labs Hackathon.

## Prior work

Standing is original work created during the hackathon build window. It uses
the published Sibyl Memory SDK, the official Virtuals ACP v2 client at the
external adapter boundary, Base EAS, and ERC-8004 registries. Prior public
scaffolding and preflight records are identified in the repository history and
[`docs/preflight.json`](docs/preflight.json). No third-party project or source
is represented as an endorsement.

## License

[MIT](LICENSE)
