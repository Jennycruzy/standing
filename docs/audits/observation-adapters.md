# Observation adapter audit

Date: 2026-09-09

## Result

The two external observation paths now have typed Python boundaries. Product EAS schemas are registered, the seller worker and ERC-8004 feedback writer are implemented, and the remaining live proof is explicitly recorded as unfinished below.

The Base reader loads its endpoint and EAS address from [`config/chain.json`](../../config/chain.json), reads `getAttestation(bytes32)` at a recorded block, caches the raw response with that block number, and decodes the condition observation schema only when the caller supplies the registered schema UID and value definition. It rejects an empty, revoked, expired, or wrong-schema record.

The ACP client builds the fixed verifier request, checks the configured per-job and daily spend limits before starting the bridge, and refuses to hire when acceptance already succeeded. A completed job is not enough: the result must contain exactly one JSON verifier delivery with the condition key, value, source URL, observation UID, effective date, note, and the selected observer address.

## Evidence

- `.preflight-venv/bin/python -m unittest discover -s tests -p 'test_*.py'` — 47 tests passed in the last recorded run.
- `npm test` in `acp-adapter/` — 4 tests passed in the last recorded run.
- `.preflight-venv/bin/mypy --strict standing` — no issues found.
- `python3 -m json.tool config/chain.json`, `config/acp.json`, `config/reputation.json`, and `config/verifier.json` — valid JSON.
- `git diff --check` — no whitespace errors.
- [`tests/test_eas.py`](../../tests/test_eas.py) replays the recorded Base `getAttestation` response and proves block-keyed caching.
- [`tests/test_acp_verifier.py`](../../tests/test_acp_verifier.py) proves spend checks, acceptance-triggered hiring, typed delivery validation, and rejection of a completed job without a delivery.

## Gaps recorded

- The registered product schemas are recorded in [config/eas.json](../../config/eas.json) and [docs/audits/schema-registration.md](schema-registration.md).
- ACP job 77515 was a real capped diagnostic. It reached FUNDED but expired before delivery; no product observation or verifier-outcome reputation signal was accepted from it.
- A successful live verifier delivery still needs to be recorded before the adapter can feed a real value into the acceptance policy.
- The verifier-outcome ERC-8004 writer is implemented, but its successful transaction and readback remain to be captured.

## Exit statement

The real EAS read path, registered product schemas, ACP boundary, seller worker, and reputation writer are ready for one fresh live verifier delivery. The live proof is not yet complete.
