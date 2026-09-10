# Acceptance and observer history audit

Date: 2026-09-09

## Result

The acceptance policy is a pure function. It reads observation records and observer histories supplied by the caller, then returns `ACCEPTED` only when every configured requirement is met. Any missing source, insufficient history, missing human approval, or disagreement returns `CONTESTED` with plain reasons.

The policy values are loaded at runtime from [`config/policy.json`](../../config/policy.json). Observer selection is deterministic: fewer contradictions first, then more confirmed readings, then more total readings, then address order. The reviewer reads and updates those records through the real Sibyl client.

Strict acceptance now requires each observer reading to carry operator, source, and extractor provenance. The condition source binding also constrains observation URLs and, for vendor-primary evidence, the canonical URL and publisher identity. Evidence older than the configured freshness window or due for its configured recheck interval cannot be reused.

## Evidence

- `.preflight-venv/bin/python -m unittest discover -s tests -p 'test_*.py'` — 92 tests passed.
- `.preflight-venv/bin/mypy --strict standing` — no issues found.
- `python3 -m json.tool config/policy.json` — valid JSON.
- `git diff --check` — no whitespace errors.
- [`tests/test_acceptance.py`](../../tests/test_acceptance.py) covers policy loading, acceptance, disagreement, missing history, selection, and outcome counting.
- [`tests/test_reviewer_acceptance.py`](../../tests/test_reviewer_acceptance.py) proves that observer records are read and updated through real local Sibyl storage.
- [`tests/test_provenance.py`](../../tests/test_provenance.py) covers structured provenance and lookalike-domain rejection.
- [`tests/test_freshness.py`](../../tests/test_freshness.py) covers stale, missing, future-dated, and scheduled-recheck evidence.

## Gaps recorded

- Observer outcomes update the local reliability record through the reviewer. The matching ERC-8004 verifier-outcome writer is implemented in [scripts/run_verifier_loop.py](../../scripts/run_verifier_loop.py), and its successful live signal is recorded in [the verifier-loop audit](verifier-loop.md).
- Checked typed observations from the EAS/ACP loop are persisted in the evidence ledger and are available to later acceptance evaluations. The live bootstrap result remains `CONTESTED` until the configured independent evidence and approval requirements are met.
- The current configured rule intentionally requires two independent observer addresses in addition to the vendor-published observation. That is a configuration choice and can be changed only in `config/policy.json`.
- The current live records predate strict provenance fields and remain same-owner controlled-scenario evidence; they are intentionally not upgraded into independent or vendor-primary evidence.
- A second observer is only independent when its operator, source, and extractor identities are distinct. The live loop now supports a remote Provider address; a second wallet or parser under the same operator remains contested.

## Exit statement

The acceptance decision, memory-backed evidence ledger, and observer choice are ready for the second independent observer and the hand-verified vendor evidence required by the configured policy.

## Current validation addendum (10 September 2026)

This 9 September section is a historical audit snapshot. The current temporal
implementation and validation are recorded in
[`temporal-product.md`](temporal-product.md). The latest offline run is 151
Python tests, strict mypy, and the acceptance/reviewer paths include explicit
accepted-only product queries, supersession-aware promotion, dependent
re-evaluation, bitemporal timestamps, and persisted observer identity
metadata. The configured policy remains conservative and the controlled sandbox
remains `CONTESTED` until external vendor evidence, independent operators, and
human approval exist.
