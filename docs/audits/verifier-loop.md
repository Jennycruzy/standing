# ACP verifier loop audit

Date: 2026-09-09

## Result

The live-loop implementation is present but not yet passed. Standing starts a seller worker with a separate ACP wallet, sends the condition key together with the configured publisher URL and value type, and requires an unsatisfied acceptance result before hiring. The seller is configured to publish its own EAS observation and return the UID through ACP. The Python command then checks the chain record, evaluates acceptance, writes the observer outcome to Sibyl, and writes and reads an ERC-8004 feedback record.

## Evidence

- Buyer boundary: [standing/acp.py](../../standing/acp.py).
- Seller worker: [acp-adapter/src/verifier.ts](../../acp-adapter/src/verifier.ts).
- Python loop: [scripts/run_verifier_loop.py](../../scripts/run_verifier_loop.py).
- Spend and startup settings: [config/acp.json](../../config/acp.json).
- Sandbox-only condition: [config/verifier.json](../../config/verifier.json).
- Reputation calldata and decoding: [standing/reputation.py](../../standing/reputation.py).
- Job 77515: [ACP job record](https://api.acp.virtuals.io/jobs/8453/77515). It was created with the real buyer and seller wallets, reached FUNDED, and later expired without a delivery.

## Open item

Run one fresh capped job after resuming. Record the completed ACP job, seller-signed EAS transaction and UID, Sibyl outcome, and ERC-8004 transaction/readback here and in the README. The expired diagnostic must not be reused. No vendor.* observation has been published.

## Exit statement

The code path and configuration are staged for live verification. This audit remains open until one complete verifier delivery is read back from ACP and Base.
