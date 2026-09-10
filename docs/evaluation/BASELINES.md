# Evaluation arms

Standing's evaluation is an experiment with separate arms, not a single
self-authored accuracy claim.

| Arm | Context available | What it tests |
| --- | --- | --- |
| `standing` | confirmed decision memory, bitemporal evidence, acceptance, exact paths | the complete product |
| `no-memory` | the same current code and source inputs, with decision history removed | whether remembered intent is causal |
| `grep` | repository/vendor-name search | a lexical search baseline |
| `stateless-model` | the current code change without historical decision records | a model without intent memory |
| `current-docs-only` | current external documentation without the historical justification | current facts without decision context |

The prediction artifact is deliberately supplied by each runner. A manifest
cannot honestly derive a grep or model answer. The checked-in measurement
boundary is [`standing/baselines.py`](../../standing/baselines.py), and the
command is:

```sh
.venv/bin/python scripts/evaluate_arms.py \
  --dataset docs/evaluation/cases.json \
  --predictions /path/to/five-arm-predictions.json \
  --require-real
```

Each arm gets its own accuracy, expired-decision precision/recall,
false-block rate, missed-expiry rate, `UNKNOWN` rate, `CONTESTED` rate, and
miss list. A mismatch may include `why` and `fixed` so every miss can be
published with its diagnosis and repair status.

The real-world corpus has eight human-reviewed source-linked cases, but arm
predictions have not been recorded, so there are no real-world arm scores. The separate controlled
adversarial corpus is suitable for harness smoke tests only; its results must
be labelled synthetic and must not be presented as product-market evidence.
