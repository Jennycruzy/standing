# Observation adapter audit

Date: 2026-09-09

## Result

The two external observation paths now have typed Python boundaries. Product EAS schemas are registered, the seller worker and ERC-8004 feedback writer are implemented, and four fresh live verifier deliveries have been read back and recorded below.

The Base reader loads its endpoint and EAS address from [`config/chain.json`](../../config/chain.json), reads `getAttestation(bytes32)` at a recorded block, caches the raw response with that block number, and decodes the condition observation schema only when the caller supplies the registered schema UID and value definition. It rejects an empty, revoked, expired, or wrong-schema record.

The ACP client builds the fixed verifier request, checks the configured per-job and daily spend limits before starting the bridge, and refuses to hire when acceptance already succeeded. A completed job is not enough: the result must contain exactly one JSON verifier delivery with the condition key, value, source URL, observation UID, effective date, note, and the selected observer address.

Verifier deliveries now also carry a controlled-demo disclosure and structured operator/source/extractor provenance. The Python acceptance boundary binds observation URLs to the condition's trusted source policy and forces revalidation when the configured freshness window expires.

## Evidence

- `.preflight-venv/bin/python -m unittest discover -s tests -p 'test_*.py'` — 84 tests passed.
- `npm test` in `acp-adapter/` — 4 tests passed in the last recorded run.
- `.preflight-venv/bin/mypy --strict standing` — no issues found.
- `python3 -m json.tool config/chain.json`, `config/acp.json`, `config/reputation.json`, and `config/verifier.json` — valid JSON.
- `git diff --check` — no whitespace errors.
- [`tests/test_eas.py`](../../tests/test_eas.py) replays the recorded Base `getAttestation` response and proves block-keyed caching.
- [`tests/test_acp_verifier.py`](../../tests/test_acp_verifier.py) proves spend checks, acceptance-triggered hiring, typed delivery validation, and rejection of a completed job without a delivery.

## Gaps recorded

- The registered product schemas are recorded in [config/eas.json](../../config/eas.json) and [docs/audits/schema-registration.md](schema-registration.md).
- ACP job 77515 was a real capped diagnostic. It reached FUNDED but expired before delivery; no product observation or verifier-outcome reputation signal was accepted from it.
- ACP job 77736 completed a fresh capped live delivery. The seller-signed EAS observation was read back at block `51075629` with UID `0x662fc353d2d819b1952383de13dad5a9177ac17ac948a98a39e6858f64928b78`.
- The verifier outcome was written to Sibyl and to ERC-8004. Feedback index `2`, value `100`, and the transaction/readback are recorded in [the verifier-loop audit](verifier-loop.md).
- ACP job 77748 completed another capped live delivery. The seller-signed EAS observation was read back at block `51077067` with UID `0x70675af1277c400c155de2e32684cfb264be8061578fb9afa17c6fcdd001bf5e`; its ERC-8004 feedback was written at index `4`.
- Checked observations are now persisted by the reviewer and accumulated by the live loop; `--manual-approval` is an explicit final acceptance gate.

## Exit statement

The real EAS read path, registered product schemas, ACP boundary, seller worker, and reputation writer have passed four fresh live verifier deliveries. The remaining gap is the intentionally stricter acceptance policy, not the adapter or chain path.
