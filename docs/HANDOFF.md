# Standing v3 handoff

This file records the state at the 10 September 2026 continuation point.

## Current continuation (10 September 2026)

The in-workspace implementation has now advanced through the product
foundation and demo surfaces. The temporal evidence ledger is bitemporal,
supports effective-period supersession, same-period conflict detection,
canonical heads, revocation, and `current`/`valid_as_of`/`known_as_of`/
`history` queries. The ACP verifier extracts typed values from fetched source
content and returns extraction metadata; it no longer accepts a configured
value as evidence. Accepted evidence is promoted into evaluator-facing
condition references and automatically re-evaluates dependent decisions.

The repository also contains the real `standing` CLI entry point, the
interactive local dashboard, fixed controlled-demo PR/change/restore/
replacement flows, memory-on/off deletion proof, artifact capture, persisted
model proposals, human-only confirmation/rejection, the separate synthetic
17-case adversarial corpus and multi-arm harness, and the required architecture,
trust, demo, evaluation, and limitations documents. Observer records now
preserve explicit wallet/operator/source/extraction identity metadata.

The release gate is intentionally still closed. There is one source-linked
real-world candidate, but it is pending independent human review; there are
zero reviewed real cases, no externally operated second verifier, no
maintainer PMF confirmation, and no deployed URL/video/public submission
evidence. Those are external proof inputs, not claims that can be safely
fabricated in the workspace.

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
- The Python-side ACP bridge is in [scripts/acp_bridge.py](../scripts/acp_bridge.py). It maps buyer and seller credentials into the isolated adapter, loads the local ignored .env, validates only completed typed results, and fails closed on adapter errors/timeouts. The historical Phase 1 offline snapshot was 100 Python tests and 4 TypeScript adapter tests; the current validation counts are maintained in the temporal product audit.
- Checked ACP/EAS observations are now persisted in the memory-backed evidence ledger, and the live-loop command exposes `--manual-approval` for an explicit operator gate after evidence review.
- The memory store, pure evaluator, reviewer tools, acceptance policy, observer selection, EAS reader, ACP verifier boundary, and ERC-8004 feedback helpers are implemented under [standing/](../standing/). The bridge watchdog and resume-by-job-ID changes are covered by the current test suites.
- The EAS reader replays a recorded Base mainnet `getAttestation` response, caches reads with their block number, and rejects the earlier preflight schema as a product observation. The ACP verifier client requires an unsatisfied acceptance result, enforces the configured spend caps, and requires one typed delivery from the selected observer address.
- The local environment is `/Users/user/.env` and remains ignored by git. It contains the ACP v2 wallet IDs, signer values, agent addresses, and Base signer value. It is not copied into this handoff.
- The first attempted live bridge diagnostic created only job `76958`; its requirement did not enter the ACP service index, and the on-chain job is now expired/open with zero budget. It is recorded as a failed diagnostic and will not be reused or duplicated. No registration or public vendor observation was performed.
- A fresh capped job `76973` completed through the live Python bridge. Python received the typed completed result with `budget.set → job.submitted → job.completed`; Base logs prove the full lifecycle and payment release. The seller worker used the existing seller agent and did not create an agent.
- Product schemas are now registered on Base. Their UIDs and readback are recorded in [config/eas.json](../config/eas.json) and [docs/audits/schema-registration.md](audits/schema-registration.md).
- Fresh live verifier deliveries are now recorded: capped ACP jobs `77736`, `77742`, `77743`, and `77748` completed; the seller published Base EAS observations, the evidence ledger accumulated the later readings, Sibyl now records 4 confirmed and 0 contradicted readings for observer `0x344903e1dbf8ed072edb3797e832ad74c07cb735`, and ERC-8004 feedback was written/read for each checked outcome. Full transaction links and UIDs are in [the verifier-loop audit](audits/verifier-loop.md).
- Strict observer provenance, source binding, freshness checks, controlled-demo disclosure, and non-demo release gates are now implemented in `standing/`. The current live records remain historical same-owner demo evidence and are not silently upgraded by the new checks.
- The live-loop CLI now accepts `--provider-address` and `--offering-name` for an external marketplace Provider. External mode does not start the local seller worker, so a remote Provider can supply the second observer without exposing or copying its credentials.
- Decision revision chains, time-travel snapshots, constrained remediation transitions, and human-only expiring waivers are implemented as pure lifecycle primitives in [`standing/lifecycle.py`](../standing/lifecycle.py). They preserve the factual evaluator result while making supersession, remediation, and temporary action authorization explicit.
- The lifecycle records are now durable through dedicated Sibyl entities and the reviewer boundary. Revision promotion, remediation transitions, waiver issuance, and standing actions are journalled; an `allow` action for a non-standing result requires a stored, active human waiver.
- The source-linked evaluation corpus contract and measurement scripts are implemented in [`standing/evaluation.py`](../standing/evaluation.py), [`scripts/evaluate_dataset.py`](../scripts/evaluate_dataset.py), and [`scripts/evaluate_arms.py`](../scripts/evaluate_arms.py). The manifest contains one source-linked real candidate, explicitly marked pending human review; it is not counted as a real evaluation result.
- The release checker is [`scripts/check_release.py`](../scripts/check_release.py). It derives the vendor-expiry claim from non-synthetic `vendor_history` cases instead of accepting a separate assertion, reports the case IDs and operator identities used, and exits non-zero while the release gates remain unsatisfied.
- The advisory model boundary is [`standing/model_review.py`](../standing/model_review.py), configured by [`config/model.json`](../config/model.json) and exposed for read-only review by [`scripts/run_model_review.py`](../scripts/run_model_review.py). Structured model output can select only known review targets or propose a source extraction; explicit human confirmation with the captured source bytes is required before a caller can write the resulting evidence.
- The read-only console renderer is implemented in [`standing/console.py`](../standing/console.py) and [`scripts/render_console.py`](../scripts/render_console.py). It visibly labels controlled demo data, shows release blockers, and supports `--as-of` time travel over the persisted revision/journal view.
- Manual approval is now an evidence-bound persisted record. [`scripts/approve_evidence.py`](../scripts/approve_evidence.py) records it only after the ledger is reviewed, and [`scripts/check_acceptance.py`](../scripts/check_acceptance.py) checks it without hiring or writing on-chain.

## What remains unfinished

1. Independently human-review the source-linked GitHub case and add at least
   two more genuine, source-linked cases before claiming real-world metrics.
2. Obtain a genuinely external second observer operator and run a fresh
   source-derived observation through the official ACP path. Multiple wallets
   controlled by this operator do not satisfy that requirement.
3. Run model extraction with a valid local credential only when desired; any
   resulting proposal still requires human confirmation. Obtain maintainer/
   design-partner confirmation for PMF evidence.
4. Deploy the dashboard, record the demo video, and publish submission
   evidence. These require external hosting/accounts/people and are not
   silently represented as complete here.

The controlled demo and all offline product behavior are available now. The
bootstrap/live same-owner evidence remains intentionally `CONTESTED` under
the configured acceptance policy.

## Commits already present

The repository has real commits and origin/main is configured. The latest pushed commit is e5abbac (`feat: derive release gates from verified corpus`). The handoff file is intentionally maintained locally and is not part of that pushed commit.

## Safe next session order

Read this file, inspect git status, run the Python and TypeScript offline
suites, and keep `.env` out of git. Run the release checker to see the
current blockers; it should report one pending real candidate, zero reviewed
real cases, and one recorded operator. The next product steps are external:
human-review the real corpus, obtain the second operator, run independent
measurements, and collect PMF/deployment evidence. Acceptance should remain
conservative until those inputs and any required human approval exist. Do not
treat Virtuals `virtualAgentId` values as ACP Entity IDs. Do not publish a
`vendor.*` observation until its source and effective date have been
hand-verified.
