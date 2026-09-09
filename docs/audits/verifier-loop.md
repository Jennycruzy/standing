# ACP verifier loop audit

Date: 2026-09-09

## Result

The live delivery path passed on 2026-09-09. Standing started the seller worker with a separate ACP wallet, sent the condition key together with the configured publisher URL and value type, and required an unsatisfied acceptance result before hiring. The seller published its own EAS observation and returned the UID through ACP. The Python command read the chain record, evaluated acceptance, wrote the observer outcome to Sibyl, and wrote and read an ERC-8004 feedback record.

The final acceptance result was `CONTESTED`, as required by the current policy: the live loop still has no vendor-published observation, only one observer, and no human acceptance flag. The observer now has the required three-reading history. That is a policy outcome, not a delivery or chain-integrity failure.

## Evidence

- Buyer boundary: [standing/acp.py](../../standing/acp.py).
- Seller worker: [acp-adapter/src/verifier.ts](../../acp-adapter/src/verifier.ts).
- Python loop: [scripts/run_verifier_loop.py](../../scripts/run_verifier_loop.py).
- Spend and startup settings: [config/acp.json](../../config/acp.json).
- Sandbox-only condition: [config/verifier.json](../../config/verifier.json).
- Reputation calldata and decoding: [standing/reputation.py](../../standing/reputation.py).
- Job 77515: [ACP job record](https://api.acp.virtuals.io/jobs/8453/77515). It was created with the real buyer and seller wallets, reached FUNDED, and later expired without a delivery; it remains a historical diagnostic only.
- Job 77736: [ACP job record](https://api.acp.virtuals.io/jobs/8453/77736). The capped `$0.01` job completed through the live Python↔TypeScript bridge.
- Seller EAS observation: [Base transaction](https://basescan.org/tx/0x4fc637bf481f389119806fce00db395a7b7ffc19db23fea0f8f773b8931e5b3e), UID `0x662fc353d2d819b1952383de13dad5a9177ac17ac948a98a39e6858f64928b78`, read back at block `51075629`.
- Sibyl observer outcome: observer `0x344903e1dbf8ed072edb3797e832ad74c07cb735` now has 1 reading given, 1 confirmed, and 0 contradicted.
- ERC-8004 feedback: [Base transaction](https://basescan.org/tx/0x8eeaee30a4451e539134aeb703db1484ac828d8325b525b9c44e15e5d49f8d1b), feedback index `2`, value `100`, read back to match the confirmed observer outcome.
- Job 77742: [Base EAS transaction](https://basescan.org/tx/0x01d508d2149748071197a0eef6ac3c3039aeafa40868a81bfdfa899066d5d935), UID `0xd95a69ec8c84a1f0f8047c49ef41e8abba2cbafdf350e60f3e51d27d93963baf`; the accumulated ledger retained this observation.
- Job 77743: [Base EAS transaction](https://basescan.org/tx/0x7fe39f91e0a8298bb55eff020a6466939aa81e09f36a013f5787a6cb3be4fbea), UID `0xc4b306c762705b5ee8765e5828ddfec5636ed9050dcbdfea56967b56f06f08f7`; its [ERC-8004 feedback](https://basescan.org/tx/0xfe2d0d250ca98cc2a63e26ff90648800662b5b0fe4cd6ac0d1b86d71dcc6a77a) advanced the observer history to 3 confirmed and 0 contradicted readings.
- Job 77748: [ACP job record](https://api.acp.virtuals.io/jobs/8453/77748) completed through the same capped live path. Its [Base EAS observation](https://basescan.org/tx/0xfa23b10158da3723d28508d51c8acd6916696cd0a609e4fce741c989e5573eff) has UID `0x70675af1277c400c155de2e32684cfb264be8061578fb9afa17c6fcdd001bf5e` and was read back at block `51077067`; the [ERC-8004 feedback](https://basescan.org/tx/0xb12f670d1c643556b7bb6c45cec12462f9c7f7e41775681b4c1f9b0278146954) advanced the observer history to 4 confirmed and 0 contradicted readings.

## Open item

The one-observer live proof is complete and that observer now meets the three-reading history threshold. To produce an `ACCEPTED` result, the configured policy still needs a hand-verified vendor observation, a second independent observer with its own clean history, and explicit human approval. No `vendor.*` observation has been published.

## Exit statement

The code path, ACP delivery, seller-signed Base EAS record, Sibyl observer update, and ERC-8004 feedback readback are live and verified. The audit remains open only for the separate policy/data requirements needed to turn this contested bootstrap reading into an accepted standing.
