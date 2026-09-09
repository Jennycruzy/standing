# Standing

Standing remembers why a code decision was made and checks whether the facts it depended on still hold.

> **CONTROLLED DEMO DATA:** the current live verifier condition is an owner-controlled GitHub sandbox with a fictional value. It demonstrates the evidence path, but it is not vendor evidence and is not presented as an independent source.

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

The complete offline suite contains 81 Python tests and 4 TypeScript adapter tests. Both suites pass after the ACP resume-by-job-ID, evidence-ledger, provenance, freshness, lifecycle, evaluation-harness, and external-Provider changes.

Decision revisions, remediation, waivers, and time travel are pure lifecycle primitives in [`standing/lifecycle.py`](standing/lifecycle.py). A revision supersedes its predecessor at an explicit effective time; a remediation can end as `RESOLVED` or `SUPERSEDED` without erasing the prior decision; and an expiring waiver can permit a human-approved action without changing the evaluator's factual state. [`docs/audits/lifecycle.md`](docs/audits/lifecycle.md) records the boundary.

The source-linked evaluation harness is [`standing/evaluation.py`](standing/evaluation.py), with measurement in [`scripts/evaluate_dataset.py`](scripts/evaluate_dataset.py). Each case must link the repository decision and published ground truth, pin a source snapshot, record effective/capture times, and explicitly identify synthetic data. The current manifest at [`docs/evaluation/cases.json`](docs/evaluation/cases.json) is intentionally empty until real cases are hand-verified.

## Acceptance and observer history

The pure acceptance policy is [`standing/acceptance.py`](standing/acceptance.py#L176). Its thresholds live in [`config/policy.json`](config/policy.json), not in source. The configured policy requires a vendor-published observation, two independent observers with at least three confirmed readings and no contradictions, and human approval; otherwise the result is `CONTESTED`.

Observer independence is provenance-aware: strict mode requires distinct operator, source, and extractor identities for the observer addresses. Observation freshness is also policy-controlled; stale, missing, or future-dated evidence forces revalidation. Release gates in [`standing/release.py`](standing/release.py) keep real vendor cases and real evaluation ground truth separate from the controlled demo.

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

The ACP verifier client is [standing/acp.py](standing/acp.py#L105). It hires only when the acceptance result is not accepted, uses the configured job and spend caps in [config/acp.json](config/acp.json), and requires one typed verifier delivery signed by the selected observer address. Checked observations are persisted in the memory-backed evidence ledger so later runs evaluate accumulated evidence. Pass `--manual-approval` only after reviewing that evidence. ACP job mechanics remain in the official adapter under acp-adapter/.

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
