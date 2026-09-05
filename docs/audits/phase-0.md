# Phase 0 audit — blocked (v3 restart)

Restarted 5 September 2026 against **STANDING — BUILD SPECIFICATION v3**. This phase is a hard stop. No product code, schemas, attestations, identities, or observations were created. One capped ACP self-evaluation job was executed because v3 makes that integration the first gate.

| Checklist item | Result | Evidence |
| --- | --- | --- |
| Rules and deadline verified | Pass | `docs/preflight.json` → `rules`; live source is https://hack.sibyllabs.org/rules. The deadline is 10 September 2026, 23:59 UTC. |
| Hackathon team registration verified | Fail | Registration status cannot be inferred from public rules. The team's build-page access was not provided. |
| ACP SDK interface verified | Pass with deviation | `docs/preflight.json` → `virtualsAcp`; the legacy Python package 0.3.23 was inspected, and the current official `@virtuals-protocol/acp-node-v2@0.1.12` interface was installed from `https://github.com/Virtual-Protocol/acp-node-v2`. The current client uses wallet address, wallet ID, and P-256 signer key; the legacy Python client rejects the current signer format (`Error: Non-hexadecimal digit found`). |
| ACP sandbox lifecycle completed | Pass with deviation | Current ACP v2 discovery found both profiles and the verifier offering. Job `76580` ran on Base at $0.01 and completed through `job.created → requirement → budget.set → job.funded → job.submitted → job.completed`. The five transaction links and authenticated job record are recorded in `docs/preflight.json`. The initial listeners required the documented restart/hydration path before replaying the requirement; no second job was created. |
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
2. A dedicated Base signing key is present in local secret storage, but its public address and balance have not yet been verified. Registering schemas, attesting, registering an ERC-8004 identity, and measuring gas remain blocked until that read-only verification passes.
3. No model access was supplied, so choosing an extraction model would be an unsupported assumption.
4. The required Discord post is an external communication that has not been authorized through a team account.
5. Version 3 makes a completed ACP sandbox lifecycle the earliest hard gate. The lifecycle now passes through the current ACP v2 path, and the approved language decision is recorded in `docs/decisions/0001-acp-adapter.md`.
6. The current portal’s EconomyOS profile page and the older ACP onboarding instructions do not expose the same registration control. The current v2 API is now the source of truth: both wallets resolve, and the seller has one visible offering.
7. The official ACP-native create endpoint returned HTTP 429 twice after a cooldown. This is an external service blocker, not an invented Entity ID or a reason to reuse the portal’s `virtualAgentId` values.
8. The current product separates its surfaces: `app.virtuals.io/acp/agents` is EconomyOS “My Agents”; `app.virtuals.io/acp/scan` is marketplace reporting and discovery; `https://agdp.io/join` is an onboarding page whose ACP CTA is stale; and `https://app.virtuals.io/acp/new` is the current first-party agent-creation route. The aGDP CTA's target, `https://app.virtuals.io/acp/join`, is a live 404 in the app. Current first-party builder documentation says `/acp/new` creates a non-custodial Base wallet and does not require a token launch. The official CLI README says legacy agents can be upgraded under the dashboard's “Agents and Projects” section, but the existing profiles' upgrade controls and ACP v2 identifiers have not yet been verified. The official CLI’s open issue #92 documents the separate opaque HTTP 429 behavior, with no published reset interval.

## Exit criteria

Phase 0 does not pass yet. Do not revisit the dead `/acp/join` link, create duplicate agents, or invent Entity IDs. The ACP v2 path and adapter decision are recorded; the remaining hard-stop items are the Sibyl archive restore path, funded Base/EAS and ERC-8004 checks, model identifier, hackathon registration, and the adapter's typed boundary tests. No Phase 1 product code should be started until the remaining Phase 0 checks pass.
