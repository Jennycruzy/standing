# Decision lifecycle audit

Date: 2026-09-09

## Result

Standing now has a pure lifecycle layer for the part of the product that the
four-state evaluator cannot express by itself:

- `DecisionRevision` records an immutable decision body, an effective time, and
  the revision it supersedes. The chain validator rejects missing parents,
  forks, duplicate IDs, and backwards effective times.
- `decision_at` combines the revision chain with the standing journal so a
  caller can ask what governed at a historical timestamp and what the last
  recorded action was then.
- `Remediation` allows only explicit transitions and preserves a terminal
  `SUPERSEDED` record when a new decision replaces the old one.
- `Waiver` can be issued only with a human issuer role, requires a reason and
  expiry, and never changes the evaluator's factual state. Once it expires,
  `check_waiver` reports that the normal gate is restored.

## Boundary

The domain functions remain pure. `MemoryStore` persists revisions,
remediations, and waivers in dedicated categories, while `ReviewerTools`
validates and journals every mutation. A waiver's `permits_action` result is an
action-gate signal, not an `ACCEPTED` standing result.

## Evidence

- `.preflight-venv/bin/python -m unittest discover -s tests -p 'test_*.py'` — 92 tests passed.
- `.preflight-venv/bin/python -m mypy --strict standing` — no issues found.
- [`tests/test_lifecycle.py`](../../tests/test_lifecycle.py) covers revision
  time travel, invalid chains, remediation transitions, human-only waivers,
  expiry restoration, and deterministic journal projection.
- [`standing/lifecycle.py`](../../standing/lifecycle.py) has no memory,
  network, or model calls.

## Current validation addendum (10 September 2026)

This is a 9 September lifecycle snapshot. The current reviewer/dashboard
integration records replacement decisions, exact-path review outcomes,
human-confirmation proposals, and waiver visibility while preserving the
immutable prior records. Current suite totals and the remaining external
release blockers are in [`temporal-product.md`](temporal-product.md).
