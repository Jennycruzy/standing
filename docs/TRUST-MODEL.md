# Standing trust model

Standing treats evidence as constrained input to a deterministic evaluator.
It does not trust a label, wallet count, model suggestion, or latest arrival
by itself.

## What Standing trusts

An observation may enter the governed evidence path only when it has the
required bitemporal fields and passes these checks:

- the source URL is valid and its domain is allowed by the condition's source
  binding;
- the source type, value type, and unit match the condition definition;
- the attester, operator, extraction method, extraction version, and evidence
  identity are recorded;
- the observation is not revoked and its effective/knowledge timestamps are
  coherent;
- acceptance requirements are met, including configured history,
  independence, freshness, and human approval; and
- same-period incompatible evidence is not silently selected as canonical.

For a source-bound condition, declaring `vendor_primary` is not enough. The
URL and, where configured, the canonical publisher identity must also match.
Units are first-class: `365 hours` cannot satisfy `365 days`, and no implicit
conversion is performed.

## Temporal trust

`effective_from` answers when a fact applies in the outside world.
`observed_at` and `recorded_at` answer when Standing observed and recorded it.
The resolver therefore supports both:

- `valid_as_of`: what current evidence reconstructs as true at a valid date;
- `known_as_of`: what evidence Standing had recorded by a knowledge cutoff.

An observation with a later effective period can supersede an earlier period
through an explicit `ref_uid`. It is a change, not a conflict. Two incompatible
accepted candidates for the same effective period are `CONTESTED`; the system
does not choose by arrival time.

## Independence dimensions

Standing records three dimensions separately:

- **Operator independence:** different people or organizations control the
  observers.
- **Source independence:** observers use independent source documents or
  domains.
- **Method independence:** observers use meaningfully different extraction
  methods and versions.

Multiple wallet addresses under one operator do not prove operator
independence. The current controlled sandbox has one owner/operator and therefore
does not qualify as independent factual evidence.

Freshness has both a maximum age and an optional scheduled recheck interval.
Accepted condition references expose `last_verified_at`, `max_age_seconds`,
`recheck_interval_seconds`, and `next_check_at`; a due schedule is treated as
unknown until fresh evidence is accepted.

## Acceptance and reputation

The policy in [`config/policy.json`](../config/policy.json) remains
conservative: the current configured threshold requires vendor-primary
evidence, two independent observers with sufficient confirmed history, zero
contradictions, and a persisted evidence-bound human approval. Failed jobs and
unaccepted observations remain visible in the ledger but do not become
accepted condition references.

Transport integrity is distinct from factual reliability. A completed ACP job
proves a request, funded job, seller delivery, EAS publication, readback, and
feedback path. It does not prove that the value was factually correct until
the verifier has extracted it from an external source and an independent check
confirms it. Observer outcome categories are intended to distinguish
`confirmed`, `contradicted`, `unverifiable`, `stale`, `invalid_source`, and
`invalid_extraction`.

## Human authority

The model is advisory. It cannot create a blocking assumption, approve
evidence, issue a waiver, or record a replacement decision. Blocking conditions
enter governance only after explicit human confirmation. A waiver requires a
human issuer, a non-empty reason, an expiration, and a Sibyl journal record;
expiration restores the block automatically.

## Revocation and failure

Revoked EAS observations are excluded from temporal heads. Stale, missing,
wrong-unit, unsupported-required, or unverifiable evidence does not become
`STANDS`; it becomes `UNKNOWN` or `CONTESTED` according to the failure mode.
Failed ACP jobs are retained as diagnostic history and are not presented as
successful product evidence.

## Controlled sandbox disclosure

The interactive sandbox uses Fictional Acme Corporation data from a source
operated by Standing for deterministic product walkthrough. The verifier genuinely
fetches and extracts the published JSON, but the source is not a vendor and
does not establish independent factual reliability. The dashboard and
observation metadata mark this as `controlled_scenario: true`.
