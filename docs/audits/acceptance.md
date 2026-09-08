# Acceptance and observer history audit

Date: 2026-09-08

## Result

The acceptance policy is a pure function. It reads observation records and observer histories supplied by the caller, then returns `ACCEPTED` only when every configured requirement is met. Any missing source, insufficient history, missing human approval, or disagreement returns `CONTESTED` with plain reasons.

The policy values are loaded at runtime from [`config/policy.json`](../../config/policy.json). Observer selection is deterministic: fewer contradictions first, then more confirmed readings, then more total readings, then address order. The reviewer reads and updates those records through the real Sibyl client.

## Evidence

- `.preflight-venv/bin/python -m unittest discover -s tests -p 'test_*.py'` — 32 tests passed.
- `.preflight-venv/bin/mypy --strict standing` — no issues found.
- `python3 -m json.tool config/policy.json` — valid JSON.
- `git diff --check` — no whitespace errors.
- [`tests/test_acceptance.py`](../../tests/test_acceptance.py) covers policy loading, acceptance, disagreement, missing history, selection, and outcome counting.
- [`tests/test_reviewer_acceptance.py`](../../tests/test_reviewer_acceptance.py) proves that observer records are read and updated through real local Sibyl storage.

## Gaps recorded

- Observer outcomes currently update the local reliability record only; the matching ERC-8004 reputation signal is not written yet.
- The policy receives observations directly; the EAS observation reader and ACP verifier still need to feed it.
- The current configured rule intentionally requires two independent observer addresses in addition to the vendor-published observation. That is a configuration choice and can be changed only in `config/policy.json`.

## Exit statement

The acceptance decision and memory-driven observer choice are ready to receive real EAS and ACP observations.
