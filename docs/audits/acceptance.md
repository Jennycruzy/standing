# Acceptance and observer history audit

Date: 2026-09-09

## Result

The acceptance policy is a pure function. It reads observation records and observer histories supplied by the caller, then returns `ACCEPTED` only when every configured requirement is met. Any missing source, insufficient history, missing human approval, or disagreement returns `CONTESTED` with plain reasons.

The policy values are loaded at runtime from [`config/policy.json`](../../config/policy.json). Observer selection is deterministic: fewer contradictions first, then more confirmed readings, then more total readings, then address order. The reviewer reads and updates those records through the real Sibyl client.

## Evidence

- `.preflight-venv/bin/python -m unittest discover -s tests -p 'test_*.py'` — 47 tests passed in the last recorded run.
- `.preflight-venv/bin/mypy --strict standing` — no issues found.
- `python3 -m json.tool config/policy.json` — valid JSON.
- `git diff --check` — no whitespace errors.
- [`tests/test_acceptance.py`](../../tests/test_acceptance.py) covers policy loading, acceptance, disagreement, missing history, selection, and outcome counting.
- [`tests/test_reviewer_acceptance.py`](../../tests/test_reviewer_acceptance.py) proves that observer records are read and updated through real local Sibyl storage.

## Gaps recorded

- Observer outcomes update the local reliability record through the reviewer. The matching ERC-8004 verifier-outcome writer is implemented in [scripts/run_verifier_loop.py](../../scripts/run_verifier_loop.py), but a successful live signal is not yet recorded.
- The policy receives typed observations from the EAS/ACP loop in code; the live end-to-end delivery still needs to be captured.
- The current configured rule intentionally requires two independent observer addresses in addition to the vendor-published observation. That is a configuration choice and can be changed only in `config/policy.json`.

## Exit statement

The acceptance decision and memory-driven observer choice are ready to receive real EAS and ACP observations.
