# Release evidence gates

Standing has two different claims:

1. The protocol path works: ACP delivery, EAS readback, memory, and reputation writes complete correctly.
2. The product is ready to claim trusted standing: real vendor evidence, independent operators, and real evaluation ground truth exist.

The first claim is showsd by the live jobs in [the verifier-loop audit](verifier-loop.md). The second is intentionally not claimed by the current controlled sandbox.

Before a non-sandbox release, [`standing/release.py`](../../standing/release.py) requires:

- a visible controlled-scenario disclosure whenever sandbox data is shown;
- at least one real, hand-verified vendor-expiry case;
- at least three real evaluation cases with source-linked ground truth; and
- at least two distinct operator identities for independent observers.

Synthetic cases remain useful for unit tests, but they do not count toward the release gate. If the external operator requirement is not met, the limitation must say so plainly: different wallets or parsers operated by the same person are not independent parties.
