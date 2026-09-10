# Standing evaluation

Standing uses two separate evaluation sets. They must never be merged into a
single accuracy number.

## Real-world corpus

[`docs/evaluation/cases.json`](evaluation/cases.json) is the release manifest.
Each future case must contain a genuine engineering decision artifact, a
public source for the justification, a hand-verified historical/current
ground-truth chain, effective and capture times, and a SHA-256 hash of the
captured source snapshot. `synthetic: false` is mandatory.

The manifest contains three source-linked real cases, including GitHub's
retirement of `actions/upload-artifact@v3` and AWS Lambda's Node.js 16
deprecation. The first is explicitly a stale dependency finding based on a
later repository review, not an original historical rationale. The other two
contain explicit historical compatibility or runtime requirements. Jennycruzy
reviewed each path, evidence chain, and expected state. Scores remain
unpublished until predictions for the defined evaluation arms are recorded.

## Controlled adversarial corpus

[`docs/evaluation/adversarial.json`](evaluation/adversarial.json) contains
17 synthetic, controlled scenarios for implementation correctness. It covers
temporal supersession, same-period conflict, late evidence, historical
correction, wrong units, unsupported required predicates, revoked evidence,
stale evidence, wrong source domains, source spoofing, missing evidence,
observation branches, exact-path false matches, expired waivers, decision
supersession, archived decisions, and memory deletion.
Its source links and hashes are fixture metadata, not real-world evidence.

The corpus is intentionally separate from `cases.json`. It may be measured by
the deterministic harness, but its score must be labelled controlled and
synthetic.

## Baselines

The planned arms are:

1. **Standing:** confirmed decision memory, temporal evidence, acceptance, and
   exact-path review.
2. **No Memory:** the same review interface with history removed.
3. **Grep:** repository/vendor-name search without decision semantics.
4. **Stateless model:** current code change without historical decision memory.
5. **Current-docs-only:** current external documentation without the original
   justification.

The multi-arm measurement harness is implemented in
[`standing/baselines.py`](../standing/baselines.py) and
[`scripts/evaluate_arms.py`](../scripts/evaluate_arms.py). It requires every
named arm, rejects extra case IDs, keeps the five result sets separate, and
preserves per-miss `why` and `fixed` fields. The harness does not generate
predictions: the grep and model runners still need to be run against a
hand-verified corpus. No baseline score is claimed until that happens.

## Metrics and misses

For real cases, publish expired-decision precision/recall, false-block rate,
missed-expiry rate, `UNKNOWN` and `CONTESTED` rates, and decision/path matching
precision. For the temporal layer, publish `valid_as_of`, `known_as_of`,
supersession, and conflict accuracy. For extraction, publish value/unit
accuracy and source-validation failures.

Every miss must include:

```text
case
expected
actual
why Standing failed
whether fixed
```

No real-case misses or scores are being hidden: the manifest contains three
human-reviewed cases, but predictions have not yet been recorded and
therefore no real score is claimed. The unit and adapter suites provide
implementation regressions, not a substitute for external evaluation.

## Commands

```sh
.venv/bin/python scripts/evaluate_dataset.py \
  --dataset docs/evaluation/adversarial.json \
  --predictions /path/to/adversarial-predictions.json

.venv/bin/python scripts/evaluate_dataset.py \
  --dataset docs/evaluation/cases.json \
  --predictions /path/to/real-predictions.json \
  --require-real

.venv/bin/python scripts/evaluate_arms.py \
  --dataset docs/evaluation/cases.json \
  --predictions /path/to/five-arm-predictions.json \
  --require-real
```

The real-case corpus now reaches the configured minimum. Evaluation still
requires complete predictions, and the separate release checker remains a
safeguard for independent observer evidence.
