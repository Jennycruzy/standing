# Reviewer tools audit

Date: 2026-09-08

## Result

The reviewer tools now connect the real Sibyl store to the pure standing evaluator. A review searches the approved governed paths, reads the matching decisions, loads accepted condition references, evaluates them, and returns a typed review item. A fresh start can read the standing-change journal before receiving new input. The reviewer also persists checked ACP/EAS observations so acceptance can evaluate accumulated evidence across runs.

The write operation stores the evaluator result and journal record, but it refuses to block a decision whose evaluator result is `STANDS`. It also refuses to allow a decision whose result is not `STANDS`. The reviewer cannot replace the evaluator's result with its own verdict.

## Evidence

- `.preflight-venv/bin/python -m unittest discover -s tests -p 'test_*.py'` — 22 tests passed.
- `.preflight-venv/bin/mypy --strict standing` — no issues found.
- `git diff --check` — no whitespace errors.
- [`standing/reviewer.py`](../../standing/reviewer.py) contains the typed memory-backed tools.
- [`tests/test_reviewer.py`](../../tests/test_reviewer.py) runs against temporary real Sibyl SQLite stores and covers path search, condition references, standing writes, journal reads, unknown values, and the no-invented-block rule.

## Historical gaps recorded (8 September snapshot)

- The reviewer currently receives an already selected set of changed paths; pull-request extraction is not connected yet.
- The live verifier path now feeds checked observations into the acceptance rule; the configured policy still needs independent observer and vendor inputs before it can return `ACCEPTED`.
- The explanation is supplied by the caller for now; the model-based reviewer will choose what to raise after the tool boundary is complete.

## Exit statement

The reviewer performs the memory read → evidence accumulation → acceptance evaluation → checked write loop against real local storage. The remaining integration is the model-driven review and extraction confirmation.

## Current continuation addendum (10 September 2026)

The changed-path and acceptance integrations described as remaining above are
implemented now. `standing review` accepts working-tree, base, commit, and
fixed sandbox PR inputs; exact governed-path validation happens before a block;
stale dependencies can explicitly trigger ACP revalidation; and the model
boundary persists advisory artifact proposals until a human confirms or
rejects them. The dashboard exposes the same confirmation and remediation
workflow. The current remaining work is external release evidence, not an
unwired reviewer path.
