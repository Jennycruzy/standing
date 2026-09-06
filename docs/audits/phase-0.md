# Phase 0 audit — blocked only on external credentials/live bridge (v3 restart)

Restarted 5 September 2026 against **STANDING — BUILD SPECIFICATION v3**. This phase is a hard stop. No product code or vendor observation was created. The required EAS, ERC-8004, Sibyl, and capped ACP preflight actions were executed and recorded; the remaining credential/account item is the local OpenAI key.

| Checklist item | Result | Evidence |
| --- | --- | --- |
| Rules and deadline verified | Pass | `docs/preflight.json` → `rules`; live source is https://hack.sibyllabs.org/rules. The deadline is 10 September 2026, 23:59 UTC. |
| Hackathon team registration verified | Fail | Registration status cannot be inferred from public rules. The team's build-page access was not provided. |
| ACP SDK interface verified | Pass with deviation | `docs/preflight.json` → `virtualsAcp`; the legacy Python package 0.3.23 was inspected, and the current official `@virtuals-protocol/acp-node-v2@0.1.12` interface was installed from `https://github.com/Virtual-Protocol/acp-node-v2`. The current client uses wallet address, wallet ID, and P-256 signer key; the legacy Python client rejects the current signer format (`Error: Non-hexadecimal digit found`). |
| ACP sandbox lifecycle completed | Pass with deviation | Current ACP v2 discovery found both profiles and the verifier offering. Job `76580` completed the original lifecycle, and job `76973` completed the isolated bridge lifecycle on Base at $0.01. The fresh bridge result reached Python as `completed` with `budget.set → job.submitted → job.completed`; all transaction links are recorded in `docs/preflight.json`. The diagnostic job `76958` is retained only as an expired failed attempt. |
| Live Python↔TypeScript ACP bridge | Pass | Python invoked the TypeScript adapter with existing job `76973` and received the typed completed result. The adapter's resume-by-job-ID guard prevented duplicate creation. Base logs prove creation, budget, funding, submission, completion, and payment release. |
| Sibyl SDK language and tier calls verified | Pass with documented deviation | `docs/preflight.json` → `sibylMemory`; Python package `sibyl-memory-client` 0.8.0 was installed under Python 3.12.13 and exercised against the real local database. The official client still has no restore method, so the narrow tenant-scoped SQLite utility is the explicit fallback. |
| One entity written and read in each tier | Pass with documented deviation | State, entity, journal, reference, search, and the real `preflight/standing` archive restore were verified. The restored row preserves its original entity ID and is visible through the client and FTS. |
| EAS Base addresses verified from artifacts | Pass | `docs/preflight.json` → `baseEas`; source is the official `eas-contracts` Base deployment artifacts. |
| Throwaway schema and real attestation | Pass with historical deviation | Fresh replacement UID `0xbf2d…75f9` and native refUID UID `0x0480…2ca66` have successful Base receipts. Direct `EAS.getAttestation` returns both full records, including schema, signer, timestamp, data, and refUID. The original `0xd8f6…b637` remains historical event/indexer-only evidence. |
| Reference chain read back | Pass | The native refUID attestation `0x0480…2ca66` directly reads back with `refUID = 0xbf2d…75f9`; the referenced record directly reads back with `data = preflight-only`. |
| Gas cost recorded | Pass | Receipts include execution gas plus Base `l1Fee`. Historical and fresh EAS write costs are recorded separately in `docs/preflight.json`; the fresh direct-readback chain costs `1412859819812 + 1545853129055 wei` including L1 data fee. |
| Dedicated Base signer and balance | Pass with caution | Address `0x39Dd…be96` and the read-only balance before writes are recorded in `docs/preflight.json`. Remaining balance must be checked before any further write. |
| ERC-8004 registries and live write/read | Pass | Identity `84973` was registered on Base, then feedback index `1` was written from the separate whitelisted client. Owner, agent wallet, token URI, feedback, and summary all read back exactly. |
| Model identifier verified | Fail | The configured OpenAI credential was checked read-only with `GET /v1/models` and returned HTTP 401 `invalid_request_error`; no model access is currently usable. |
| Discord question posted | Fail | Requires the team's Discord account and approval to send an external message. |

## Gaps and blockers

1. The current OpenAI key is not usable: a read-only `GET /v1/models` returned HTTP 401 `invalid_api_key`. Replace the local credential, then select and record an exact supported model identifier from the [official model catalog](https://developers.openai.com/api/docs/models).
2. The required Discord post and hackathon registration are external account actions and are not being performed in this preflight.
3. The ACP v2 language decision remains the isolated TypeScript adapter boundary in `docs/decisions/0001-acp-adapter.md`; do not use the legacy Entity-ID path or invent IDs.

## Exit criteria

Phase 0 does not pass yet because the local OpenAI credential is empty/invalid, and registration/Discord remain separate external account actions. EAS direct readback plus reference chaining, ERC-8004 read/write, the real Sibyl archive restoration, and the live Python↔TypeScript ACP bridge now pass with documented deviations. Do not revisit the dead `/acp/join` link, create duplicate agents, or invent Entity IDs. No Phase 1 product code should be started until the remaining external credential/account checks pass.
