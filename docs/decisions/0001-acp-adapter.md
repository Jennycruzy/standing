# Decision 0001 — isolate the current ACP client

**Date:** 5 September 2026  
**Status:** Accepted  
**Scope:** Virtuals ACP integration only

## Decision

Standing's product code remains Python 3.12. The Virtuals ACP boundary is a small, separately tested TypeScript process using the official `@virtuals-protocol/acp-node-v2` client.

The boundary accepts typed job requests and returns typed job results. It does not evaluate conditions, choose a standing verdict, or write Sibyl Memory. Both processes load their own environment-injected secrets locally; private keys are never sent through the boundary or logged.

## Why

The current ACP v2 profiles successfully completed a real Base job using wallet addresses, Privy wallet IDs, and P-256 signer keys. The installed Python package `virtuals-acp==0.3.23` is a legacy client: it expects a hexadecimal EOA key and a numeric Entity ID, and rejects the current signer format before it can initialize.

Strict Python would therefore require different legacy ACP agents or an unsupported reimplementation of the current wallet protocol. The adapter preserves the real ACP integration already verified and limits the language exception to the external boundary.

## Evidence

- Current client: [Virtual-Protocol/acp-node-v2](https://github.com/Virtual-Protocol/acp-node-v2)
- ACP API: [api.acp.virtuals.io](https://api.acp.virtuals.io)
- Completed Base job: [job 76580 completion](https://basescan.org/tx/0x3dea100ecba5a9ae114e9cd979b0a1fbdcf90b38fb197d06c058c652a4401afd)
- Full preflight record: [docs/preflight.json](../preflight.json)

## Guardrails

- The adapter cannot return a standing state or a gate decision.
- Job prices and daily spend limits come from configuration, not source literals.
- The adapter uses fixed operation names and typed payloads; it accepts no arbitrary URL or free-form signing request.
- ACP responses are recorded and replayed in offline tests; no synthetic response is used.
- The adapter is not considered complete until a test proves that Python receives the real completed job result and that an ACP failure is surfaced rather than treated as success.
