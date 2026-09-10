# Standing limitations

This repository now contains the temporal evidence foundation, typed source
extraction boundary, conservative evaluator, CLI, and local interactive demo.
The following limitations are deliberate and must remain visible in any
submission.

## Evidence and sources

- The interactive source is controlled fictional data for Fictional Acme
  Corporation. It is operated by Standing, not by a real vendor. The verifier
  genuinely fetches and extracts the source, but that demonstrates extraction
  integrity, not independent factual accuracy.
- The checked-in real-world evaluation manifest
  [`docs/evaluation/cases.json`](evaluation/cases.json) contains three
  source-linked, human-reviewed cases. The first is classified as a stale
  dependency finding because its decision artifact is a later repository
  review; the other two contain explicit historical compatibility or runtime
  requirements. No aggregate real-world accuracy number is published from
  only three cases.
- No external second operator has yet been recorded. The existing live
  observer history is same-owner evidence and remains contested under the
  configured policy.
- The live ACP history includes failed diagnostic job `77515`; it reached
  `FUNDED` and expired before delivery. It is retained as a diagnostic failure,
  not counted as product evidence.

## Coverage

- Predicate support is intentionally narrow: retention thresholds, region
  membership, SSO support, and end-of-life dates. Unsupported required rules
  return `UNKNOWN` and block.
- The HTML extractor supports a narrow ID selector grammar. JSON paths and
  regular expressions are deterministic but must still be bound to an allowed
  source and reviewed under the acceptance policy.
- EAS readback supplies chain observation time and the local ledger supplies
  knowledge recording time. A production deployment should persist a durable
  capture receipt and source snapshot for every external read.
- The current configured EAS observation schema is the existing registered
  six-field schema. The complete bitemporal representation is persisted in
  Sibyl's evidence ledger and returned by the query APIs; registering a new
  expanded on-chain schema requires a separate, explicitly authorized chain
  operation.

## Product and operations

- The dashboard is deployable through `render.yaml`; the public deployment URL
  is an external submission artifact. It uses an isolated temporary store in
  `--demo` mode.
- **BREAK DEMO ASSUMPTION** is a deterministic local replay. It does not create
  a new ACP job or EAS attestation. The completed live ACP → extraction → EAS
  path is separately linked from the dashboard and README.
- Dashboard actions are fixed and constrained. There is no arbitrary signing
  API, but production deployment still needs authentication, rate limiting,
  spend controls, audit monitoring, and key rotation around any future chain
  action.
- ACP revalidation requires configured credentials, a funded job, a reachable
  source, and a compatible seller. The offline test suite does not claim live
  marketplace availability.
- The waiver dashboard action is preview-only. Real waivers require a human
  issuance workflow; the model cannot issue them.
- Model extraction is advisory: artifacts and proposals can be persisted for
  review, but only an explicit human confirmation promotes a proposal to a
  governing decision. The model cannot confirm, reject, waive, or block.

## Evaluation and PMF

- The controlled adversarial corpus is synthetic and must be scored separately
  from real cases. A perfect synthetic score would not be evidence of product-
  market fit.
- Grep, stateless-model, and current-docs-only baselines are evaluation plans;
  no flattering score is reported until a hand-verified corpus and prediction
  files exist. Every miss must be published with its case, expected result,
  actual result, cause, and fix status.
- Maintainer/design-partner confirmation, a demo video, and final public
  submission URLs are external artifacts and are not claimed by this repo.
