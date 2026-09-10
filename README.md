# Standing

> **Standing remembers why code was written and blocks changes when the facts that justified that code are no longer true.**

```text
Decision: Use Acme because retention >= 365 days
Then:     365 days ✓
Now:      90 days ✕
PR:       touches dependent code
Standing: BLOCKED
```

Standing is a temporal system of record for engineering intent. It separates
what was true from what Standing knew at the time, preserves supersession and
conflict history, and records what eventually replaced an expired decision.

## Judge it in three minutes

```sh
git clone https://github.com/Jennycruzy/standing.git
cd standing
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python .
date -u
git rev-parse --short HEAD
.venv/bin/standing boot
.venv/bin/standing dashboard --demo
```

Then open `http://127.0.0.1:8787/` and follow one story:

1. A fresh process recalls ACME-001 and the code it governs.
2. **BREAK DEMO ASSUMPTION** changes the observed retention from 365 to 90.
3. Standing identifies the exact dependent path and blocks the PR.
4. **MEMORY OFF** removes the decision and its protection while the external
   fact remains—proving memory is load-bearing.
5. **RECORD REPLACEMENT DECISION** supersedes ACME-001 and restores ALLOW.
6. **Live partner proof** links the completed Virtuals ACP job, Base EAS
   observation, and ERC-8004 feedback used by the verification path.

### Why Sibyl Memory makes this possible

Current vendor documentation can reveal a fact, but it cannot explain why a
particular file depends on that fact or what engineers knew when they approved
the decision. Sibyl persists that engineering intent, governed-path mapping,
accepted evidence references, standing changes, waivers, and supersession
history across fresh processes. Delete it and Standing can no longer connect
the changed fact to the code, so the expiry protection disappears.

### Team and partner stacks

- Builder: **Jennycruzy** / **Jenny builds**.
- **Sibyl Memory:** critical-path decision, condition, journal, and reference
  persistence.
- **Virtuals ACP:** completed verifier jobs that acquire fresh observations.
- **Base EAS:** immutable observation records and schema registrations.
- **ERC-8004:** verifier outcome feedback.

## Try the product

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Jennycruzy/standing)

The Render blueprint launches the isolated controlled demo without credentials
or arbitrary signing. For the final presentation and public-post copy, use the
[submission kit](docs/SUBMISSION.md).

Run the isolated, disclosure-first dashboard:

```sh
standing dashboard --demo
```

Open `http://127.0.0.1:8787/`, then use the fixed **BREAK DEMO ASSUMPTION**,
time-travel, **MEMORY OFF**, waiver preview, replacement, and restore controls.
The fictional source is labelled throughout the product; it is a controlled
demonstration, not vendor evidence.

Run the command-line deletion comparison:

```sh
standing deletion-test
```

The same entry points also expose temporal queries:

```sh
standing history vendor.acme.retention_days
standing condition vendor.acme.retention_days --valid-as-of 2026-03-03
standing condition vendor.acme.retention_days --known-as-of 2026-03-03
standing decision current src/archive.py
```

Product documentation: [architecture](docs/ARCHITECTURE.md),
[trust model](docs/TRUST-MODEL.md), [demo](docs/DEMO.md),
[limitations](docs/LIMITATIONS.md), and [evaluation](docs/EVALUATION.md).

> **CONTROLLED DEMO:** the fictional Acme source makes the complete workflow safe, repeatable, and judge-operated. The verifier genuinely reads the published source; three separate human-reviewed public cases demonstrate the real-world temporal model.

## Memory

Sibyl Memory is the local store behind Standing. It is a database file on the machine, not a separate service.

- Decisions, conditions, and observer histories are written in [`standing/memory.py`](standing/memory.py#L41).
- A fresh process reads them through the same file at [`standing/memory.py`](standing/memory.py#L47).
- Decisions governing changed files are found by path at [`standing/memory.py`](standing/memory.py#L148).
- Archive and restore use the real Sibyl client plus its documented restore fallback at [`standing/memory.py`](standing/memory.py#L163).
- The memory-off test uses the same interface and starts with a new empty store at [`tests/test_memory.py`](tests/test_memory.py#L75).

The direct Python client is installed with:

```sh
uv pip install --python .preflight-venv/bin/python sibyl-memory-client==0.8.0
```

Run the tests with:

```sh
.preflight-venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

The local memory database is ignored by Git. Secrets remain in the environment and are never written into memory records.

## Decision evaluation

The pure evaluator is [`standing/evaluator.py`](standing/evaluator.py#L101). It checks only the four supported rules, returns `STANDS`, `EXPIRED`, `UNKNOWN`, or `CONTESTED`, and produces a repeatable fingerprint for the result.

Only `EXPLICIT` and `CONFIRMED` conditions can block. An `INFERRED` or `EXTERNAL` condition remains visible as a note but cannot stop a change. The evaluator never reads files, calls a model, or writes to memory.

Run the complete test suite with:

```sh
.preflight-venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

## Reviewer tools

The memory-backed reviewer tools are in [`standing/reviewer.py`](standing/reviewer.py#L59). They search approved paths, read decisions and current condition values, run the evaluator, read the boot journal, and write a checked standing change.

The write tool rejects a block when the evaluator returned `STANDS`, so the reviewer cannot invent a block. The real-storage tests are in [`tests/test_reviewer.py`](tests/test_reviewer.py#L12).

The complete offline suite is run with the commands above; its current test
counts are reported by the validation audit rather than hard-coded here. The
TypeScript adapter suite also covers source extraction and typed metadata.

## Advisory model boundary

The optional model boundary is [`standing/model_review.py`](standing/model_review.py). [`scripts/run_model_review.py`](scripts/run_model_review.py) gives the model only changed paths, remembered candidate decisions, and the boot journal. Structured output may select known review targets and ask questions, but it cannot return a standing state, allow/block action, or approval. The extraction path returns a proposal only; [`confirm_extraction`](standing/model_review.py) requires an explicit human, the exact source snapshot bytes, and its SHA-256. [`ReviewerTools.record_confirmed_extraction`](standing/reviewer.py) can then persist the complete bitemporal observation and confirmation journal, but it deliberately does not accept or promote the condition; a separate acceptance check and explicit promotion are still required.

The Responses transport uses structured JSON output and reads `OPENAI_API_KEY` from the environment. The model IDs and endpoint are in [`config/model.json`](config/model.json); no key or model response is written to the repository.

Decision revisions, remediation, waivers, and time travel are pure lifecycle primitives in [`standing/lifecycle.py`](standing/lifecycle.py). A revision supersedes its predecessor at an explicit effective time; a remediation can end as `RESOLVED` or `SUPERSEDED` without erasing the prior decision; and an expiring waiver can permit a human-approved action without changing the evaluator's factual state. [`docs/audits/lifecycle.md`](docs/audits/lifecycle.md) records the boundary.

The source-linked evaluation harness is [`standing/evaluation.py`](standing/evaluation.py), with measurement in [`scripts/evaluate_dataset.py`](scripts/evaluate_dataset.py). Each case links the repository decision and published ground truth, pins historical/current source excerpts, records effective/capture times, and explicitly identifies synthetic data. The manifest at [`docs/evaluation/cases.json`](docs/evaluation/cases.json) contains three operator-reviewed public cases checked with the [`review packet`](docs/evaluation/REVIEW-PACKET.md). Operator review is not represented as maintainer confirmation or independent evaluation.

The read-only console renderer is [`standing/console.py`](standing/console.py), exposed by [`scripts/render_console.py`](scripts/render_console.py). It places the controlled-demo disclosure in the page itself, shows release blockers, and supports a historical `--as-of` view; lifecycle events cannot hide the latest standing result.

## Acceptance and observer history

The pure acceptance policy is [`standing/acceptance.py`](standing/acceptance.py#L176). Its thresholds live in [`config/policy.json`](config/policy.json), not in source. The configured policy requires a vendor-published observation, two independent observers with at least three confirmed readings and no contradictions, and an evidence-bound human approval record; otherwise the result is `CONTESTED`.

Observer independence is provenance-aware: strict mode requires distinct operator, source, and extractor identities for the observer addresses. Observation freshness is also policy-controlled; stale, missing, future-dated, or scheduled-recheck-due evidence forces revalidation. Release gates in [`standing/release.py`](standing/release.py) keep real vendor cases and real evaluation ground truth separate from the controlled demo.

Observer selection reads the reliability records from memory and favors fewer contradictions, then more confirmed readings. A checked outcome updates the local record through [standing/reviewer.py](standing/reviewer.py#L137). The ERC-8004 feedback writer is implemented in [standing/reputation.py](standing/reputation.py) and is called by the live-loop command below; its live transaction and readback are recorded in [the verifier-loop audit](docs/audits/verifier-loop.md).

## Base product schemas

Standing's condition-definition and observation schemas are registered in the configured Base SchemaRegistry. Their UIDs, registration transaction hashes, and definitions are recorded in [`config/eas.json`](config/eas.json); the live registration and readback evidence is [`docs/audits/schema-registration.md`](docs/audits/schema-registration.md).

The idempotent command is:

```sh
.preflight-venv/bin/python scripts/register_product_schemas.py --write
```

It reads the registry first and writes only missing schemas. With both schemas present, it performs no transaction.

## Base and Virtuals adapters

The Base reader is [`standing/eas.py`](standing/eas.py#L177). It reads the direct EAS record, decodes the six-field observation payload, rejects revoked or mismatched records, and caches each chain response with its block number. The replay test uses a recorded Base mainnet response at [`tests/fixtures/eas_reference_read.json`](tests/fixtures/eas_reference_read.json).

The ACP verifier client is [standing/acp.py](standing/acp.py#L105). It hires only when the acceptance result is not accepted, uses the configured job and spend caps in [config/acp.json](config/acp.json), and requires one typed verifier delivery signed by the selected observer address. Checked observations are persisted in the memory-backed evidence ledger so later runs evaluate accumulated evidence. The approval workflow is separate from hiring: review the ledger, record an approval with [`scripts/approve_evidence.py`](scripts/approve_evidence.py), then run [`scripts/check_acceptance.py`](scripts/check_acceptance.py). The verifier job cannot manufacture its own approval, and changing any observation invalidates the approval fingerprint. ACP job mechanics remain in the official adapter under acp-adapter/.

## ACP verifier loop

The buyer is Standing and the seller is a separately keyed ACP agent using the existing published_condition_check offering. The seller reads the configured sandbox page, publishes its own EAS observation on Base, and returns that observation through ACP. The end-to-end command is [scripts/run_verifier_loop.py](scripts/run_verifier_loop.py); the seller worker is [acp-adapter/src/verifier.ts](acp-adapter/src/verifier.ts).

Each verifier delivery includes a visible disclosure plus operator, source, and extractor provenance. The source binding for the controlled demo is configured beside the condition in [config/verifier.json](config/verifier.json); a real release must replace it with a hand-verified vendor source.

An external marketplace Provider can be targeted without local seller credentials by supplying its public address and offering name. The adapter then sends the same structured requirement and waits for the remote Provider's typed EAS delivery:

```sh
.preflight-venv/bin/python scripts/run_verifier_loop.py \\
  --provider-address 0xProviderAddress \\
  --offering-name published_condition_check \\
  --spent-today-usdc 0.03
```

The remote Provider must already support the required condition, Base EAS schema, disclosure, and provenance fields; hiring cannot add those capabilities after the fact.

The paused live attempt created ACP job 77515, reached FUNDED, and expired before delivery; it remains an unsuccessful diagnostic, not product evidence. Fresh capped jobs 77736, 77742, 77743, and 77748 completed through the live Python↔TypeScript bridge. The seller published and returned its own Base EAS observations, the Python loop read them back, accumulated the evidence, updated the Sibyl observer record to 4 confirmed readings with no contradictions, and wrote/read ERC-8004 feedback. The full evidence is in [the verifier-loop audit](docs/audits/verifier-loop.md). Acceptance remains intentionally `CONTESTED` because the configured policy still requires vendor evidence, two independent observers, and human approval. No vendor.* observation has been published.

## Prior Work

Standing is original work for the Sibyl Labs Hackathon by Jennycruzy. It uses the published Sibyl Memory SDK, the official Virtuals ACP v2 client at the external adapter boundary, Base EAS, and ERC-8004 registries. Prior public scaffolding and preflight records are identified in the repository history and [docs/preflight.json](docs/preflight.json); no third-party project is represented as an endorsement.
