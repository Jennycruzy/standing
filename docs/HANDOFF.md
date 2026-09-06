# Standing v3 handoff

This file is intentionally local and is not part of the commit. It records the state at the stop point on 6 September 2026.

## What is complete

- The v3 Phase 0 investigation is recorded in [`docs/preflight.json`](preflight.json) and [`docs/audits/phase-0.md`](audits/phase-0.md).
- The current Virtuals ACP v2 path was verified with the real portal agents, the seller offering `published_condition_check`, and a capped `$0.01` Base job. Job `76580` completed through creation, requirement, budget, funding, submission, and completion. All five Base transaction links and the job record are in `docs/preflight.json`.
- The current ACP v2 credentials were shown to be incompatible with the legacy Python client. The approved decision is a Python Standing core with an isolated official TypeScript ACP adapter. The decision is in [`docs/decisions/0001-acp-adapter.md`](decisions/0001-acp-adapter.md).
- A dedicated Base signer was read and its address recorded without exposing the key. The verified address and pre-write balance are in `docs/preflight.json`.
- Base EAS deployment addresses were taken from the official deployment artifacts and stored in [`config/chain.json`](../config/chain.json).
- One throwaway schema was registered and one attestation was broadcast on Base. Their UIDs, receipts, links, block numbers, and measured costs are recorded in `docs/preflight.json` and `config/chain.json`.
- The schema readback succeeded. The attestation receipt emitted a UID. A 6 September read-only check still gets the ABI's empty/default record from `getAttestation` on `mainnet.base.org`; `isAttestationValid` is false and `getTimestamp` is zero. A separate older Base attestation UID also returns the empty/default record, so this is not unique to Standing's transaction. The Base EAS indexer reconstructs Standing's exact UID, transaction, timestamps, zero `refUID`, signer, revocability, recipient, and encoded `preflight-only` data. This confirms event/indexer evidence, not direct EAS storage readback.
- The current read-only balance of the recorded Base signer is `0.000197409408466816 ETH`, consistent with the two recorded writes. No further transaction was made.
- The local EAS helper scripts are in [`scripts/phase0_eas.py`](../scripts/phase0_eas.py) and [`scripts/read_preflight_eas.py`](../scripts/read_preflight_eas.py). They read the local environment and do not print private keys.
- The isolated ACP adapter boundary is scaffolded in [`acp-adapter/`](../acp-adapter/). Its official-client wiring typechecks, and three offline tests cover a completed lifecycle, ACP rejection/expiry behavior, and unsafe configuration. It has not been run live or connected to the Python process yet; no spend or chain write occurred while adding it.
- The Python-side ACP bridge is now in [`scripts/acp_bridge.py`](../scripts/acp_bridge.py). It maps the existing `BUYER_*` environment names into the adapter's `STANDING_ACP_*` names, loads the local ignored `.env` when called without an explicit environment, validates only completed typed results, and fails closed on adapter errors/timeouts. Six Python tests and the adapter's three TypeScript tests pass offline. It has not been run live; no spend or chain write occurred while adding it.
- The Sibyl archive gap now has a tenant-scoped, atomic local workaround in [`scripts/sibyl_archive.py`](../scripts/sibyl_archive.py). The real preflight database was inspected read-only; its one archive row was restored successfully on a temporary copy using the actual schema, while the real evidence database remains unchanged. The workaround's tests pass.
- The local environment is `/Users/user/.env` and remains ignored by git. It contains the ACP v2 wallet IDs, signer values, agent addresses, and Base signer value. It is not copied into this handoff.
- No further chain write was made after the recorded schema and attestation. No vendor observation was published.

## What remains blocked or unfinished

1. Resolve the Base EAS readback discrepancy. The Base indexer confirms the UID, schema, transaction, timestamps, `refUID`, attester, recipient, revocability, and encoded data, but direct getters return empty/default for Standing's UID and a separate indexed Base UID. Do not treat the attestation as directly retrievable or make the reference-chain write until there is an accepted supported readback path.
2. Only after that readback is correct and the user approves the spend, make the second attestation with `refUID` and prove the reference chain can be walked.
3. Check the remaining Base signer balance before any new transaction. Do not assume the pre-write balance is still available.
4. Decide whether to restore the existing preflight archive row in the real `.preflight-memory.db`. The restore path is implemented and verified on a temporary copy; performing it on the real evidence database is intentionally still an operator action.
5. Verify ERC-8004 Identity and Reputation live interactions, or document the EAS fallback. No identity or reputation write was made.
6. Confirm hackathon team registration and repair the model access. The configured OpenAI key was checked read-only and returned HTTP 401 from `GET /v1/models`; no exact model identifier is currently usable.
7. Ask the required Virtuals graduation/sandbox questions from the team's account if still needed. Do not use the retired `/acp/join` route and do not create more agents or tokens.
8. Prove the live adapter bridge: run one user-approved completed ACP job through `acp-adapter/` and prove the Python side receives the typed result; also prove a live ACP failure is surfaced rather than treated as success. The local bridge and offline adapter tests already cover the boundary mechanics without spending funds.
9. Do not start Phase 1 product code until the remaining Phase 0 hard-stop items pass.

## Commits already present

The repository does have real commits. The latest before the current local changes is `83e1097 docs: record EAS readback blocker`. Earlier commits record the v3 restart, secret-file ignore rule, ACP route investigation, funding verification, and completed ACP lifecycle. The EAS discrepancy documentation and adapter scaffold are currently uncommitted local changes. The handoff must remain untracked locally. No git remote is configured in this checkout, so a push requires the repository URL and credentials to be configured first.

## Safe next session order

Read this file, inspect `git status`, validate the JSON, review the adapter tests, and investigate the EAS discrepancy before any transaction. Keep `.env` out of git. Do not treat the Virtuals `virtualAgentId` values as ACP Entity IDs. Do not claim Phase 0 passed while any item above remains unresolved.
