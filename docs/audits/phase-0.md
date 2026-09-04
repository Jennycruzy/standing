# Phase 0 audit — blocked

Captured 4 September 2026. This phase is a hard stop. No product code, schemas, attestations, identities, or observations were created.

| Checklist item | Result | Evidence |
| --- | --- | --- |
| Rules and deadline verified | Pass | `docs/preflight.json` → `rules`; live source is https://hack.sibyllabs.org/rules. The deadline is 10 September 2026, 23:59 UTC. |
| Sibyl SDK language and tier calls verified | Partial pass | `docs/preflight.json` → `sibylMemory`; Python package `sibyl-memory-client` 0.8.0 was installed under Python 3.12.13 and exercised against a local database. |
| One entity written and read in each tier | Fail | State, entity, journal, reference, and search were exercised. Archive could be written but not read/restored through the documented client API. |
| EAS Base addresses verified from artifacts | Pass | `docs/preflight.json` → `baseEas`; source is the official `eas-contracts` Base deployment artifacts. |
| Throwaway schema and real attestation | Fail | The available Base wallet is unfunded. No on-chain transaction was attempted. |
| Reference chain read back | Fail | Dependent on the unfunded EAS write. |
| Gas cost recorded in USD | Fail | Dependent on the unfunded EAS write. |
| ERC-8004 registries and live write/read | Fail | Identity address has an explorer result; Reputation Registry and both write/read tests remain unverified because no funded signing wallet is available. |
| Model identifier verified | Fail | No extraction provider or exact identifier has been configured. |
| Discord question posted | Fail | Requires the team's Discord account and approval to send an external message. |

## Gaps and blockers

1. The current official Sibyl client exposes `archive_entity` but no documented archive retrieval or restore method. The product's archive-and-resurrect requirement therefore cannot be claimed yet.
2. The active Base wallet reports $0.00. Registering schemas, attesting, registering an ERC-8004 identity, and measuring gas are blocked.
3. No model access was supplied, so choosing an extraction model would be an unsupported assumption.
4. The required Discord post is an external communication that has not been authorized through a team account.

## Exit criteria

Phase 0 does not pass. It can pass only after a funded dedicated Base wallet performs a real schema registration, attestation, reference-chain read, ERC-8004 identity registration, and reputation write/read (or verifies that the fallback is necessary); an exact extraction model identifier is verified; the archive restore path is resolved; and the team posts the Discord question.
