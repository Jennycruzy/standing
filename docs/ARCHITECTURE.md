# Standing architecture

Standing is a temporal system of record for engineering intent. Its core
decision is deterministic: a confirmed condition is evaluated from accepted
evidence, and the result is linked back to the exact governed paths that a
change touches.

## Causal flow

```text
Engineering artifact
        ↓
Advisory extraction proposal
        ↓
Explicit human confirmation
        ↓
Sibyl Memory: decisions, paths, conditions, journal
        ↓
Changed paths / PR
        ↓
Candidate lookup + exact governed-path validation
        ↓
Condition freshness check
        ↓ stale, missing, or scheduled recheck due
Virtuals ACP verifier request
        ↓
Allowed external source
        ↓
Typed source extraction
        ↓
Base EAS observation + local bitemporal ledger
        ↓
Temporal acceptance and canonical head
        ↓
Sibyl accepted condition reference
        ↓
Dependent decision re-evaluation
        ↓
STANDS / EXPIRED / UNKNOWN / CONTESTED
        ↓
ALLOW / BLOCK / human waiver
        ↓
Replacement decision and explicit supersession
```

## Boundaries

### Temporal evidence

[`standing/temporal.py`](../standing/temporal.py) owns the bitemporal model.
Every new governed observation has valid-time fields (`effective_from` and
optional `effective_until`) and knowledge-time fields (`observed_at` and
`recorded_at`). It also retains source, attester, operator, extraction,
identity, hash, revocation, and supersession metadata.

`TemporalEvidence` resolves a canonical head by effective time and explicit
`ref_uid` lineage. A later effective period is a change; incompatible values
in the same effective period are `CONTESTED`. Arrival time alone never wins.

The public queries are exposed through `ReviewerTools` and the CLI:

```text
current(condition_key)
valid_as_of(condition_key, date)
known_as_of(condition_key, date)
history(condition_key)
```

### Memory

[`standing/memory.py`](../standing/memory.py) is the only storage boundary.
It persists confirmed decisions, condition references, observations, standing
changes, revisions, waivers, remediations, approvals, and observer history
through the Sibyl client. The reviewer does not silently substitute an
in-memory dictionary for the configured store.

### Evaluator and reviewer

[`standing/evaluator.py`](../standing/evaluator.py) is pure and has no model,
filesystem, network, or write access. Required unsupported predicates and
incompatible units become `UNKNOWN` and can block. The reviewer performs
candidate search, exact path validation, freshness orchestration, acceptance
promotion, journal writes, and decision supersession around that pure core.

### Evidence adapters

The TypeScript worker in [`acp-adapter/`](../acp-adapter/) fetches an allowed
source and extracts the value from the fetched bytes using a versioned,
typed policy (`JSON_PATH`, narrow `HTML_SELECTOR`, or `REGEX`). It does not
accept a separately configured observation value. The Python bridge validates
the typed delivery, reads the Base EAS record, persists the complete temporal
observation, and invokes acceptance promotion.

The current live sandbox source is intentionally controlled fictional data. It is
labelled in the source, verifier configuration, observation notes, dashboard,
README, and sandbox documentation.

### Advisory model boundary

[`standing/model_review.py`](../standing/model_review.py) can propose review
targets or an extraction record from an engineering artifact. It cannot emit a
standing state, allow/block action, approval, waiver, or memory write. A
human must confirm an extraction against the exact captured source bytes before
it becomes eligible for persistence.

### Product surfaces

The product-centered local dashboard is served by
[`standing/dashboard.py`](../standing/dashboard.py). `standing dashboard
--sandbox` uses an isolated temporary Sibyl database and exposes only fixed
actions: break/reset the controlled source, inspect a waiver preview, and
record the pre-authored replacement decision. It has no user-controlled
destination, calldata, value, source URL, schema, or signer input.

The CLI is registered in `pyproject.toml` and provides boot, review, condition,
history, decision, waiver, dashboard, proof-seed, and memory-proof commands.

## State and history rules

An accepted condition reference is a derived current view, not a replacement
for the observation ledger. Historical observations remain queryable after a
new observation is promoted. A decision marked `SUPERSEDED` is excluded from
current path review but remains available to `decision_as_of` and the Sibyl
journal. Waivers authorize a temporary action; they do not change the factual
evaluator state and expire automatically.

## External trust dependencies

Sibyl preserves engineering intent and its journal. Virtuals ACP acquires
fresh verification when evidence is stale or insufficient. Base EAS gives
observations a public chain record. ERC-8004 records observer outcomes and
reputation signals. The repository includes eight human-reviewed public cases,
including vendor expiries. A public product walkthrough and third-party PMF
confirmation remain external publication tasks.
