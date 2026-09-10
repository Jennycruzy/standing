# Advisory model boundary audit

## Result

Standing now has an optional model boundary for two narrow tasks: selecting
remembered decisions that need human review and proposing a value extracted
from a supplied source snapshot. The deterministic evaluator and memory-backed
writer remain outside the boundary. Model output is structured, checked
against known decision/condition identifiers, and cannot contain a standing
state, action, or approval.

An extraction proposal is not evidence. `confirm_extraction` requires an
explicit human identity, review note, effective timestamp, and the exact
non-empty source bytes; it hashes those bytes and returns condition-reference
and observation payloads for a separate caller-controlled write.

## Evidence

- [`standing/model_review.py`](../../standing/model_review.py) contains the
  typed transport, review proposal, extraction proposal, and confirmation
  boundary.
- [`scripts/run_model_review.py`](../../scripts/run_model_review.py) performs a
  read-only model review over local memory and never writes a standing change.
- [`tests/test_model_review.py`](../../tests/test_model_review.py) covers
  structured output, identifier validation, source binding, human confirmation,
  snapshot hashing, and missing credentials.
- `.preflight-venv/bin/python -m unittest discover -s tests -p 'test_*.py'` — 100 tests passed.
- `.preflight-venv/bin/python -m mypy --strict standing` — no issues found.

## Boundary

The live model call is intentionally not claimed by this audit. It requires a
working `OPENAI_API_KEY`; the checked-in configuration is not a credential.
The current controlled-scenario evidence and release gates remain unchanged.

## Current validation addendum (10 September 2026)

The model boundary remains advisory, but the persistence handoff is now wired:
[`ReviewerTools.record_confirmed_extraction`](../../standing/reviewer.py) writes
the human-confirmed, source-hashed bitemporal observation and journals the
confirmation. It does not bypass acceptance or promote a condition. The
remaining live-model, external-review, and release claims still require the
inputs described in the README's [trust boundaries](../../README.md#trust-boundaries).
