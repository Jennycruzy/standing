# Observation adapter audit

Date: 2026-09-08

## Result

The two external observation paths now have typed Python boundaries.

The Base reader loads its endpoint and EAS address from [`config/chain.json`](../../config/chain.json), reads `getAttestation(bytes32)` at a recorded block, caches the raw response with that block number, and decodes the condition observation schema only when the caller supplies the registered schema UID and value definition. It rejects an empty, revoked, expired, or wrong-schema record.

The ACP client builds the fixed verifier request, checks the configured per-job and daily spend limits before starting the bridge, and refuses to hire when acceptance already succeeded. A completed job is not enough: the result must contain exactly one JSON verifier delivery with the condition key, value, source URL, observation UID, effective date, note, and the selected observer address.

## Evidence

- `.preflight-venv/bin/python -m unittest discover -s tests -p 'test_*.py'` — 40 tests passed.
- `.preflight-venv/bin/mypy --strict standing` — no issues found.
- `python3 -m json.tool config/chain.json` and `python3 -m json.tool config/acp.json` — valid JSON.
- `git diff --check` — no whitespace errors.
- [`tests/test_eas.py`](../../tests/test_eas.py) replays the recorded Base `getAttestation` response and proves block-keyed caching.
- [`tests/test_acp_verifier.py`](../../tests/test_acp_verifier.py) proves spend checks, acceptance-triggered hiring, typed delivery validation, and rejection of a completed job without a delivery.

## Gaps recorded

- The product condition and observation schemas have not yet been registered; the current chain record is intentionally the earlier preflight schema and is rejected as a product observation.
- No new mainnet observation or ACP job was created by this increment.
- A successful live verifier delivery still needs to be recorded before the adapter can feed a real value into the acceptance policy.
- ERC-8004 reputation writing remains separate work.

## Exit statement

The real EAS read path and the real ACP bridge boundary are ready for the registered product schemas and a live verifier delivery.
