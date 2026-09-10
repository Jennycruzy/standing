# Temporal product audit

Date: 2026-09-10

## Result

The workspace implementation now covers the product-side temporal evidence
foundation and its local review path. The release proof is intentionally still
closed where it depends on external people, credentials, or deployment.

## Temporal evidence

[`standing/temporal.py`](../../standing/temporal.py) stores valid time and
knowledge time separately. A governed observation includes effective and
expiry dates, observation and recording times, source identity, attester and
operator identity, extraction method/version, value type, unit, hashes,
revocation, acceptance, and an optional `ref_uid` supersession edge.

The resolver is deterministic and does not use arrival order as a proxy for
truth:

- later effective periods are changes and may link to an earlier observation;
- incompatible observations for the same effective period are `CONTESTED`;
- late-arriving historical observations do not replace a newer current period;
- revoked observations are excluded from heads but retained in history; and
- knowledge cutoffs exclude observations recorded after the cutoff.

Product-facing `current`, `valid_as_of`, and `known_as_of` queries default to
accepted evidence. Acceptance and promotion explicitly inspect the wider
ledger before making an accepted reference. This prevents unaccepted evidence
from appearing as governed current truth while still allowing the policy to
evaluate newly received evidence.

[`standing/memory.py`](../../standing/memory.py) persists observations,
accepted condition references, decision revisions, standing changes, and
waivers. [`standing/reviewer.py`](../../standing/reviewer.py) exposes temporal
condition and decision queries, automatically links a new effective period to
its predecessor when safe, promotes accepted evidence, and re-evaluates every
dependent decision.

## Evidence and review correctness

The TypeScript seller in
[`acp-adapter/src/verifier.ts`](../../acp-adapter/src/verifier.ts) fetches the
configured source and extracts the value from the fetched bytes through
[`acp-adapter/src/extraction.ts`](../../acp-adapter/src/extraction.ts). It no
longer accepts a separately configured observation value. The typed delivery
records source URL/domain, effective/publication dates, value type, unit,
snapshot/evidence hashes, extraction method/version, disclosure, and
supersession reference. The Python boundary validates those fields and keeps
the seller observation time separate from Standing's local receipt time.

The acceptance boundary validates trusted source bindings, exact domains,
types, units, freshness, scheduled rechecks, revocation, provenance, observer
history, and human approval. Condition references carry
`last_verified_at`, `max_age_seconds`, `recheck_interval_seconds`, and
`next_check_at`; a due scheduled recheck is blocking until fresh evidence is
accepted. Wrong units and unsupported required predicates cannot become
`STANDS`; they return a conservative blocking `UNKNOWN`. Exact governed-path
checks happen after candidate retrieval, so full-text search cannot create a
false block. Temporary waivers are human-only, reasoned, expiring, journalled,
and do not rewrite the factual state.

Artifact ingestion and the model boundary are also connected. A model may
propose a decision or extraction from a bounded, hashed artifact; a human must
confirm it. [`ReviewerTools.record_confirmed_extraction`](../../standing/reviewer.py)
then persists the complete source-hashed observation without accepting or
promoting it automatically.

## Product surfaces

The `standing` console entry point is declared in
[`pyproject.toml`](../../pyproject.toml) and provides `boot`, `review`,
`condition`, `history`, `decision`, `waiver`, `dashboard`, and
`deletion-test`. The dashboard is a local isolated controlled demo with a
landing finding, clickable decision graph, bitemporal time travel, provenance,
fixed PR review, memory on/off comparison, source break/restore, replacement
decision, human-confirmation controls, waiver inspection, and a visible
real-world candidate panel. It contains no arbitrary transaction-signing
surface.

The demo source is explicitly Fictional Acme Corporation data operated by
Standing. The verifier genuinely reads and extracts it, but it is not vendor
evidence and is not counted as independent factual proof.

## Evaluation and release status

[`docs/evaluation/cases.json`](../evaluation/cases.json) and
[`docs/evaluation/adversarial.json`](../evaluation/adversarial.json) are
separate. The former contains three source-linked public candidates pending
human review; the latter contains 17 controlled adversarial fixtures. The
multi-arm harness has Standing, no-memory, grep, stateless-model, and
current-docs-only arms, with per-case miss explanations. No real-world metric
is published while the real corpus has no reviewed ground truth.

The current release check reports:

```text
1 pending real candidate
0 reviewed real cases
0 real vendor-expiry cases
1 supplied operator identity
release ready: false
```

Those remaining gates require independent human review, at least two more
genuine reviewed cases, a genuinely external second operator with a fresh
source-derived observation, and human approval where configured. Maintainer
PMF confirmation, a deployed URL, video, and public submission evidence are
also external deliverables. The failed ACP job `77515` remains retained and
labelled as a diagnostic failure.

## Validation

The following checks pass in the current workspace:

- `.preflight-venv/bin/python -m unittest discover -s tests -p 'test_*.py'` —
  151 tests passed;
- `.preflight-venv/bin/python -m mypy --strict standing` — no issues;
- `npm test` in `acp-adapter/` — 9 tests passed;
- `npm run typecheck -- --pretty false` in `acp-adapter/` — passed;
- `standing deletion-test` — memory-on detects the expired dependency and
  memory-off reports historical protection unavailable; and
- `git diff --check` — no whitespace errors.

This audit distinguishes implementation integrity from the still-unmet
external factual-reliability and product-market-fit claims.
