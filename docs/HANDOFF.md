# Standing v3 handoff

This file records the state at the 6 September 2026 Phase 0 continuation point.

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
- The Python-side ACP bridge is in [`scripts/acp_bridge.py`](../scripts/acp_bridge.py). It maps the existing `BUYER_*` environment names into the adapter's `STANDING_ACP_*` names, loads the local ignored `.env`, validates only completed typed results, and fails closed on adapter errors/timeouts. Six Python tests and four TypeScript tests pass offline.
- The local environment is `/Users/user/.env` and remains ignored by git. It contains the ACP v2 wallet IDs, signer values, agent addresses, and Base signer value. It is not copied into this handoff.
- The first attempted live bridge diagnostic created only job `76958`; its requirement did not enter the ACP service index, and the on-chain job is now expired/open with zero budget. It is recorded as a failed diagnostic and will not be reused or duplicated. No registration or public vendor observation was performed.
- A fresh capped job `76973` completed through the live Python bridge. Python received the typed completed result with `budget.set → job.submitted → job.completed`; Base logs prove the full lifecycle and payment release. The seller worker used the existing seller agent and did not create an agent.

## What remains blocked or unfinished

1. Replace or repair the local OpenAI API key. The current read-only `GET /v1/models` check returns HTTP 401 `invalid_api_key`; only then select an exact model from the [official model catalog](https://developers.openai.com/api/docs/models).
2. Registration and Discord remain external account actions outside this continuation; no public post has been made.
3. Do not start Phase 1 product code until the remaining Phase 0 hard-stop items pass.

## Commits already present

The repository does have real commits. The current base commit is `e59c83d fix: close local phase 0 gaps`; the EAS replacement/readback, ERC-8004 verifier, Sibyl restore evidence, adapter resume guard, and handoff updates are the current local changes to commit after verification. No git remote is configured in this checkout, so a push still requires the repository URL and credentials to be configured first.

## Safe next session order

Read this file, inspect `git status`, validate the JSON, and repair the local OpenAI credential before selecting a model. Keep `.env` out of git. Do not treat the Virtuals `virtualAgentId` values as ACP Entity IDs. EAS, ERC-8004, Sibyl, and live ACP bridge evidence is already complete in this handoff.
