# Memory layer audit

Date: 2026-09-08

## Result

The first memory boundary is implemented against the real `sibyl-memory-client` 0.8.0 package. Standing uses one typed wrapper for normal storage and for an empty storage run.

The wrapper persists decisions, conditions, observer records, current standing, accepted condition references, and the standing-change journal. It finds decisions by their approved governed paths and can archive and restore a decision. The empty-storage setting creates a fresh local database through the same client interface.

## Evidence

- `.preflight-venv/bin/python -m unittest discover -s tests -p 'test_*.py'` — 11 tests passed.
- `.preflight-venv/bin/mypy --strict standing` — no issues found.
- `python3 -m json.tool docs/preflight.json` — valid JSON.
- `git diff --check` — no whitespace errors.
- [`standing/memory.py`](../../standing/memory.py) contains the single environment-flag read and all memory operations.
- [`tests/test_memory.py`](../../tests/test_memory.py) proves persistence, duplicate replacement, path search, archive/restore, empty storage, and the single read site.

## Historical gaps recorded (8 September snapshot)

- The wrapper does not yet evaluate a decision or publish a condition observation. Those belong to the evaluator and chain work that follows.
- The archive restore operation uses the narrow SQLite fallback in [`scripts/sibyl_archive.py`](../../scripts/sibyl_archive.py) because the installed client exposes archive but not restore.
- Test records are local fixtures for the storage boundary. They are not vendor observations and are not published to Base.

## Exit statement

The memory boundary is ready for the decision evaluator and reviewer wiring. No production vendor record is created by this increment.

## Current continuation addendum (10 September 2026)

The first historical gap above has since been closed. The reviewer now resolves
changed paths to remembered decisions, reads accepted temporal condition
references, evaluates standing, and journals the result. Accepted evidence is
promoted into those references and dependent decisions are re-evaluated. See
[`docs/audits/temporal-product.md`](temporal-product.md) for the current system
audit; the archive fallback and fixture boundaries remain accurately disclosed.
