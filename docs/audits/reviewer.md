# Reviewer tools audit

Date: 2026-09-08

## Result

The reviewer tools now connect the real Sibyl store to the pure standing evaluator. A review searches the approved governed paths, reads the matching decisions, loads accepted condition references, evaluates them, and returns a typed review item. A fresh start can read the standing-change journal before receiving new input.

The write operation stores the evaluator result and journal record, but it refuses to block a decision whose evaluator result is `STANDS`. It also refuses to allow a decision whose result is not `STANDS`. The reviewer cannot replace the evaluator's result with its own verdict.

## Evidence

- `.preflight-venv/bin/python -m unittest discover -s tests -p 'test_*.py'` — 22 tests passed.
- `.preflight-venv/bin/mypy --strict standing` — no issues found.
- `git diff --check` — no whitespace errors.
- [`standing/reviewer.py`](../../standing/reviewer.py) contains the typed memory-backed tools.
- [`tests/test_reviewer.py`](../../tests/test_reviewer.py) runs against temporary real Sibyl SQLite stores and covers path search, condition references, standing writes, journal reads, unknown values, and the no-invented-block rule.

## Gaps recorded

- The reviewer currently receives an already selected set of changed paths; pull-request extraction is not connected yet.
- It does not yet call an outside verifier or apply the acceptance rule to multiple observations.
- The explanation is supplied by the caller for now; the model-based reviewer will choose what to raise after the tool boundary is complete.

## Exit statement

The reviewer can now perform the memory read → evaluation → checked write loop against real local storage. The next integration is the acceptance rule and observer records.
