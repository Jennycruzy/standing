# Standing v3 handoff

This file records the state at the 9 September 2026 continuation point.

## What is complete

- The v3 Phase 0 investigation is recorded in [`docs/preflight.json`](preflight.json) and [`docs/audits/phase-0.md`](audits/phase-0.md).
- The current Virtuals ACP v2 path was verified with the real portal agents, the seller offering `published_condition_check`, and a capped `$0.01` Base job. Job `76580` completed through creation, requirement, budget, funding, submission, and completion. All five Base transaction links and the job record are in `docs/preflight.json`.
- The current ACP v2 credentials were shown to be incompatible with the legacy Python client. The approved decision is a Python Standing core with an isolated official TypeScript ACP adapter. The decision is in [`docs/decisions/0001-acp-adapter.md`](decisions/0001-acp-adapter.md).
- A dedicated Base signer was read and its address recorded without exposing the key. The verified address and pre-write balance are in `docs/preflight.json`.
- Base EAS deployment addresses were taken from the official deployment artifacts and stored in [`config/chain.json`](../config/chain.json).
- One throwaway schema and two fresh attestations were broadcast on Base. The second attestation uses the first UID as its native `refUID`; direct EAS reads prove both records and the reference chain. Their UIDs, receipts, links, and measured costs are recorded in `docs/preflight.json` and `config/chain.json`. The original `0xd8f6…b637` event/indexer-only record is retained as historical evidence.
- The ERC-8004 Base Identity and Reputation registries now have live proof: Standing identity `84973` was registered, the separate client wrote feedback index `1`, and owner, wallet, token URI, feedback, and summary read back exactly. The idempotent verifier is [`scripts/erc8004_preflight.py`](../scripts/erc8004_preflight.py).
- The real Sibyl `preflight/standing` archive row was restored in `.preflight-memory.db` with its original entity ID and body `{"status":"verified"}`. `MemoryClient.get_entity`, search, and FTS were checked afterward; the archive row is gone from the archive table.
- The isolated ACP adapter boundary is in [`acp-adapter/`](../acp-adapter/). Its official-client wiring typechecks, four offline tests pass, and it now supports resume-by-job-ID so a retry cannot create a duplicate job.
- The Python-side ACP bridge is in [scripts/acp_bridge.py](../scripts/acp_bridge.py). It maps buyer and seller credentials into the isolated adapter, loads the local ignored .env, validates only completed typed results, and fails closed on adapter errors/timeouts. The last recorded offline run passed 47 Python tests and 4 TypeScript adapter tests.
- The memory store, pure evaluator, reviewer tools, acceptance policy, observer selection, EAS reader, ACP verifier boundary, and ERC-8004 feedback helpers are implemented under [standing/](../standing/). The latest bridge-watchdog edit was made after that test run and must be tested before it is described as verified.
- The EAS reader replays a recorded Base mainnet `getAttestation` response, caches reads with their block number, and rejects the earlier preflight schema as a product observation. The ACP verifier client requires an unsatisfied acceptance result, enforces the configured spend caps, and requires one typed delivery from the selected observer address.
- The local environment is `/Users/user/.env` and remains ignored by git. It contains the ACP v2 wallet IDs, signer values, agent addresses, and Base signer value. It is not copied into this handoff.
- The first attempted live bridge diagnostic created only job `76958`; its requirement did not enter the ACP service index, and the on-chain job is now expired/open with zero budget. It is recorded as a failed diagnostic and will not be reused or duplicated. No registration or public vendor observation was performed.
- A fresh capped job `76973` completed through the live Python bridge. Python received the typed completed result with `budget.set → job.submitted → job.completed`; Base logs prove the full lifecycle and payment release. The seller worker used the existing seller agent and did not create an agent.
- Product schemas are now registered on Base. Their UIDs and readback are recorded in [config/eas.json](../config/eas.json) and [docs/audits/schema-registration.md](audits/schema-registration.md).

## What remains unfinished

1. Resume the real verifier loop. Jobs 77507 and 77515 are expired; no active ACP job remains. Job 77515 reached FUNDED but expired before the seller delivered an observation.
2. Capture one successful ACP verifier delivery containing the seller's own EAS observation UID, feed it through the acceptance policy, write the observer outcome to Sibyl, and read back the matching ERC-8004 feedback.
3. Record that successful evidence in a new verifier-loop audit and update the README links.
4. Connect the model reviewer, extraction confirmation, public console, seeded historical records, measurement harness, and submission materials.

## Commits already present

The repository has real commits and origin/main is configured. The latest pushed commit is db6d72c feat: register product EAS schemas. This paused increment contains the ACP seller worker, reputation helpers, verifier-loop command, and bridge watchdog; it is being committed now without claiming the live verifier proof is complete.

## Safe next session order

Read this file, inspect git status, run the two offline suites, and keep .env out of git. Then run one fresh scripts/run_verifier_loop.py --bootstrap job only after checking the configured spend cap. Do not treat the Virtuals virtualAgentId values as ACP Entity IDs. Do not publish a vendor.* observation until its source and effective date have been hand-verified.
