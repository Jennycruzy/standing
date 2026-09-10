# Evidence-bound manual approval audit

Date: 2026-09-09

The acceptance policy no longer treats a bare boolean as sufficient human
approval. `ManualApproval` requires a human role, reviewer identity, reason,
timestamp, and the SHA-256 fingerprint of the complete observation set. Any
changed, added, or removed observation produces a different fingerprint and
returns `CONTESTED`.

The operator workflow is deliberately separate from ACP hiring:

1. run the verifier without an approval;
2. inspect the persisted observations;
3. run [`scripts/approve_evidence.py`](../../scripts/approve_evidence.py); and
4. run [`scripts/check_acceptance.py`](../../scripts/check_acceptance.py).

The approval record is persisted in Sibyl and its issuance is journalled. The
current controlled-scenario evidence still cannot pass because it lacks vendor
primary evidence and a genuinely independent second operator.
