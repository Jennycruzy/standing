# Decision evaluator audit

Date: 2026-09-08

## Result

Standing now has a pure evaluator. Given one decision record and its current condition records, it returns one of four states without reading a file, calling a model, or writing to a service.

The evaluator supports exactly these checks:

- retention in days is at least a threshold;
- a named region is present;
- single sign-on support is true;
- an end-of-life date is after a specified date.

Only conditions marked `EXPLICIT` or `CONFIRMED` can block. A failed `INFERRED` or `EXTERNAL` condition is still shown to the engineer but leaves the decision standing. Missing values produce `UNKNOWN`; disagreeing observations produce `CONTESTED`.

## Evidence

- `.preflight-venv/bin/python -m unittest discover -s tests -p 'test_*.py'` — 18 tests passed.
- `.preflight-venv/bin/mypy --strict standing` — no issues found.
- `git diff --check` — no whitespace errors.
- [`standing/evaluator.py`](../../standing/evaluator.py) contains no memory, network, file, or model calls.
- [`tests/test_evaluator.py`](../../tests/test_evaluator.py) covers the four checks, four states, provenance limits, unsupported rules, and stable fingerprints.

## Historical gaps recorded (8 September snapshot)

- The evaluator currently receives condition records directly; the reviewer agent has not yet been wired to choose which decisions to review.
- Acceptance of observations and the external verifier still need to be connected to the evaluator's condition records.
- The evaluator does not publish a standing change. The caller must write the result and its fingerprint to memory.

## Exit statement

The deterministic decision check is ready for reviewer-agent tools and acceptance-policy wiring.

## Current continuation addendum (10 September 2026)

The historical gaps above have since been closed in the workspace. The
reviewer now selects decisions from changed paths, validates exact stored
governed paths, reads the accepted condition reference, and records standing
changes. Acceptance promotion updates that reference and automatically
re-evaluates every dependent decision. Unsupported required predicates,
stale evidence, wrong units, and contested temporal heads remain conservative
`UNKNOWN`/`CONTESTED` outcomes rather than implicit standing. See
[`docs/audits/temporal-product.md`](temporal-product.md) for the current
validation record.
