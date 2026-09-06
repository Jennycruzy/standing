# Standing ACP adapter

This is the isolated TypeScript boundary approved in `../docs/decisions/0001-acp-adapter.md`.

- It uses the official `@virtuals-protocol/acp-node-v2` `0.1.12` client.
- It accepts one typed JSON job request on stdin and emits one JSON response on stdout.
- It loads wallet credentials only inside the TypeScript process. Private keys are never part of the request or response.
- It owns ACP lifecycle mechanics only. Standing verdicts and Sibyl writes remain outside this boundary.
- A rejected or expired ACP job exits non-zero and is never returned as a successful result.

Required environment variables for a live run:

```text
STANDING_ACP_WALLET_ADDRESS
STANDING_ACP_WALLET_ID
STANDING_ACP_SIGNER_PRIVATE_KEY
```

Optional:

```text
STANDING_ACP_BUILDER_CODE
```

Example request shape (do not run without explicit spend approval):

```json
{
  "chainId": 8453,
  "offeringName": "published_condition_check",
  "providerAddress": "0x2222222222222222222222222222222222222222",
  "requirement": { "key": "standing-preflight" },
  "budgetUsdc": 0.01,
  "completionReason": "preflight lifecycle accepted",
  "timeoutMs": 900000
}
```

Set `jobId` to resume a known active ACP job. When `jobId` is present, the adapter never calls the job-creation endpoint, so retries cannot create duplicate jobs.

The tests inject a fake ACP runtime; the live bridge proof is recorded in `../docs/preflight.json`.
