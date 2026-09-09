# Source-linked evaluation corpus

`cases.json` is the release corpus manifest. It is intentionally empty until
each case has been hand-verified against the public sources; an empty manifest
keeps the release gate honest.

Each real case must include:

- the repository and stable decision URL/ref;
- the published ground-truth URL and source type;
- the ground-truth effective time and capture time;
- a SHA-256 digest of the captured source snapshot;
- the expected Standing state; and
- `synthetic: false` explicitly.

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
