# Phase 0 audit — blocked (v3 restart)

Restarted 5 September 2026 against **STANDING — BUILD SPECIFICATION v3**. This phase is a hard stop. No product code, schemas, attestations, identities, observations, ACP accounts, jobs, or payments were created.

| Checklist item | Result | Evidence |
| --- | --- | --- |
| Rules and deadline verified | Pass | `docs/preflight.json` → `rules`; live source is https://hack.sibyllabs.org/rules. The deadline is 10 September 2026, 23:59 UTC. |
| Hackathon team registration verified | Fail | Registration status cannot be inferred from public rules. The team's build-page access was not provided. |
| ACP SDK interface verified | Partial pass | `docs/preflight.json` → `virtualsAcp`; `virtuals-acp` 0.3.23 installed and imported in Python 3.12.13. |
| ACP sandbox lifecycle completed | Fail | The two public agent wallet addresses were queried against `https://acpx.virtuals.io/api/agents?filters[walletAddress]=...`; both returned HTTP 200 with zero matches. The official `@virtuals-protocol/acp-cli` was authenticated and its `agent list --json` returned the two EconomyOS profiles with `acpV2AgentId: null`. Three `agent create` attempts (including a retry after a cooldown) returned HTTP 429 `Rate limit exceeded`; no ACP-native lifecycle or Entity ID was created. The aGDP ACP button was then verified to open `https://app.virtuals.io/acp/join`, which displays the app's `Page not found` screen. Current first-party builder docs instead direct creation to `https://app.virtuals.io/acp/new`. |
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
5. Version 3 makes a completed ACP sandbox lifecycle the earliest hard gate. It is now the first unresolved integration and blocks all implementation phases.
6. The current portal’s EconomyOS profile page and the older ACP onboarding instructions do not expose the same registration control. The registry lookup is the source of truth: both wallets currently have zero ACP records, and read-only Base checks found no deployed smart-account code at either address.
7. The official ACP-native create endpoint returned HTTP 429 twice after a cooldown. This is an external service blocker, not an invented Entity ID or a reason to reuse the portal’s `virtualAgentId` values.
8. The current product separates its surfaces: `app.virtuals.io/acp/agents` is EconomyOS “My Agents”; `app.virtuals.io/acp/scan` is marketplace reporting and discovery; `https://agdp.io/join` is an onboarding page whose ACP CTA is stale; and `https://app.virtuals.io/acp/new` is the current first-party agent-creation route. The aGDP CTA's target, `https://app.virtuals.io/acp/join`, is a live 404 in the app. Current first-party builder documentation says `/acp/new` creates a non-custodial Base wallet and does not require a token launch. The official CLI README says legacy agents can be upgraded under the dashboard's “Agents and Projects” section, but the existing profiles' upgrade controls and ACP v2 identifiers have not yet been verified. The official CLI’s open issue #92 documents the separate opaque HTTP 429 behavior, with no published reset interval.

## Exit criteria

Phase 0 does not pass. Do not revisit the dead `/acp/join` link or create duplicate agents. Next action is to open `https://app.virtuals.io/acp/agents`, open the existing Standing Requestor and Standing Verifier profiles, and inspect their detail/settings pages for Upgrade, Migrate, ACP v2, Wallet, or Signers controls. It can then pass after the resulting ACP identifiers and signer mapping are verified, both agents complete the published self-evaluation lifecycle with funded buyer USDC; a funded dedicated Base wallet performs a real schema registration, attestation, reference-chain read, ERC-8004 identity registration, and reputation write/read (or verifies that the fallback is necessary); an exact extraction and reviewer model identifier is verified; and the archive restore path is resolved.
