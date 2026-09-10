# Source-linked evaluation corpus

`cases.json` is the real-world release corpus manifest. It currently contains
three source-linked cases, marked `human_reviewed: true`, covering two
GitHub Actions compatibility/retirement findings and an AWS Lambda runtime
deprecation. The first is deliberately classified as a stale dependency
finding because its artifact is a later repository review, not original
decision rationale. Jennycruzy reviewed the linked artifacts, governed paths,
vendor sources, effective dates, and expected states using the
[review packet](REVIEW-PACKET.md).

`adversarial.json` is a separate synthetic corpus of 17 deterministic failure
scenarios. Its score must never be combined with the real-world corpus.

Each real case must include:

- the repository and stable decision URL/ref;
- the published ground-truth URL and source type;
- the ground-truth effective time and capture time;
- a SHA-256 digest of the captured source snapshot;
- the expected Standing state; and
- `synthetic: false` explicitly.

For a release-eligible case, the manifest also records the historical and
current claims, condition key, predicate, governed paths, decision snapshot
hash, and an explicit human reviewer/timestamp. The checked-in source files
under `snapshots/` are transparent excerpts whose hashes are pinned; they are
not represented as byte-for-byte remote archives.

Synthetic fixtures are allowed in unit tests and may be placed in a separate
working manifest, but `EvaluationDataset.release_case_count()` excludes them.
The measurement command never fills missing predictions and never accepts
prediction IDs that are absent from the corpus:

```sh
.preflight-venv/bin/python scripts/evaluate_dataset.py \
  --dataset docs/evaluation/cases.json \
  --predictions /path/to/predictions.json \
  --require-real
```

The expected state must be derived from the vendor's published history at the
recorded effective time. A repository decision URL alone is not ground truth.

See [`../EVALUATION.md`](../EVALUATION.md) for the baseline arms, metrics, and
miss-publication policy.

The five-arm JSON shape is:

```json
{
  "standing": {"case-id": "EXPIRED"},
  "no-memory": {"case-id": "UNKNOWN"},
  "grep": {"case-id": {"state": "STANDS", "why": "...", "fixed": false}},
  "stateless-model": {"case-id": "UNKNOWN"},
  "current-docs-only": {"case-id": "EXPIRED"}
}
```

Run [`scripts/evaluate_arms.py`](../../scripts/evaluate_arms.py) only after
each arm has produced a complete prediction file. The command emits one
metric object per arm; it never combines controlled and real-world scores.
