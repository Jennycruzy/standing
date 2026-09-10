# Real-world human review packet

These are genuine public artifacts paired with primary vendor sources. They are
evaluation candidates, not endorsements or maintainer-confirmed findings. A
project operator must open every link and confirm the exact claim before setting
`human_reviewed` to `true` in `cases.json`.

## Review procedure

For each case:

1. Open the decision artifact and verify the quoted configuration or rationale.
2. Open the vendor source and verify the change and effective date.
3. Verify that the governed path exactly matches the artifact.
4. Decide whether the expected state follows without inferred motivation.
5. Record your name and review date in `cases.json`; do not use “independent”
   unless the reviewer is genuinely independent of Standing.

## Case 1 — iterabledata upload-artifact v3

- Decision artifact: [repository review report](https://github.com/datenoio/iterabledata/blob/main/REPOSITORY_REVIEW_REPORT.md)
- Governed path: `.github/workflows/security.yml`
- Vendor history: [GitHub's v3 deprecation notice](https://github.blog/changelog/2024-04-16-deprecation-notice-v3-of-the-artifact-actions/)
- Current vendor source: [actions/upload-artifact](https://github.com/actions/upload-artifact)
- Proposed expected state: `EXPIRED`
- Check: the public artifact identifies v3 use and GitHub retired v3 for
  GitHub.com on 2025-01-30.

## Case 2 — SLSA generator artifact v3 compatibility

- Decision artifact: [SLSA container builder compatibility note](https://github.com/slsa-framework/slsa-github-generator/blob/main/internal/builders/docker/README.md#compatibility-with-actionsdownload-artifact)
- Governed path: `internal/builders/docker/README.md`
- Replacement history: [SLSA generator changelog](https://github.com/slsa-framework/slsa-github-generator/blob/main/CHANGELOG.md#v200-breaking-change-upload-artifact-and-download-artifact)
- Vendor history: [GitHub's v3 deprecation notice](https://github.blog/changelog/2024-04-16-deprecation-notice-v3-of-the-artifact-actions/)
- Proposed expected state: `EXPIRED` for the old v3 compatibility decision;
  superseded by the v2.0.0 v4 migration.
- Check: the old documentation explicitly couples download-artifact v3 to
  upload-artifact v3, while the changelog explicitly records the v4 replacement.

## Case 3 — AWS Lambda Next.js sample on Node.js 16

- Decision artifact: [AWS sample requirements](https://github.com/aws-samples/aws-lambda-nextjs/blob/main/README.md#requirements)
- Governed path: [`nextjs-lambda-sam/template.yaml`](https://github.com/aws-samples/aws-lambda-nextjs/blob/main/nextjs-lambda-sam/template.yaml)
- Vendor source: [AWS Lambda runtime lifecycle](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html)
- Proposed expected state: `EXPIRED`
- Check: the sample requires Node.js 16 and configures `nodejs16.x`; AWS lists
  that runtime as deprecated from 2024-06-12.

## Case 4 — AWS SAM CRUD sample on Python 3.8

- Decision artifact: [SAM template at the reviewed commit](https://github.com/aws-samples/sam-python-crud-sample/blob/6e4de8e76d6af3f4715a5f0f847ae99ab3368acc/template.yaml)
- Governed path: `template.yaml`
- Vendor source: [AWS Lambda runtime lifecycle](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html)
- Proposed expected state: `EXPIRED`
- Check: the template pins its CRUD functions to `python3.8`; AWS lists
  `python3.8` as deprecated from 2024-10-14.

This is labelled a stale runtime configuration finding, not an inferred
architectural rationale.

## Case 5 — AWS Java 8 DynamoDB sample

- Decision artifact: [reviewed README commit](https://github.com/aws-samples/lambda-java8-dynamodb/blob/15a015dda4d63df2b03e30e00057bc7cc432776d/README.md)
- Governed path: `README.md`
- Vendor source: [AWS Lambda runtime lifecycle](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html)
- Proposed expected state: `EXPIRED`
- Check: the sample explicitly describes an API built with the Java 8 Lambda
  runtime; AWS lists `java8` as deprecated from 2024-01-08.

This is labelled an explicit stale runtime finding, not an inferred original
architecture rationale.

## Case 6 — Vite Node.js engine compatibility

- Decision artifact: [Vite package metadata at the reviewed commit](https://github.com/vitejs/vite/blob/434e8e9495436a60789f2b588a04a6a24a3d1661/packages/vite/package.json)
- Governed path: `packages/vite/package.json`
- Current runtime source: [Node.js release schedule](https://nodejs.org/en/about/previous-releases)
- Proposed expected state: `STANDS`
- Check: Vite accepts Node `>=22.12.0`; Node.js lists the v22 line as LTS.

This is labelled an explicit package compatibility record, not an inferred
ADR.

## Case 7 — Flask Python runtime compatibility

- Decision artifact: [Flask package metadata at the reviewed commit](https://github.com/pallets/flask/blob/6a2f545bfd8ed31e19066a299296917e034aca58/pyproject.toml)
- Governed paths: `pyproject.toml`, `docs/installation.rst`
- Current runtime source: [Python version status](https://devguide.python.org/versions/)
- Proposed expected state: `STANDS`
- Check: Flask supports Python 3.10 and newer; Python 3.12 remains in security
  support through 2028-10.

This is labelled an explicit package compatibility record, not an inferred
ADR.

## Case 8 — GitHub Actions checkout current release

- Decision artifact: [checkout usage documentation](https://github.com/actions/checkout/blob/v7.0.1/README.md)
- Governed path: `README.md`
- Current release source: [checkout v7.0.1 release](https://github.com/actions/checkout/releases/tag/v7.0.1)
- Proposed expected state: `STANDS`
- Check: the public README uses `actions/checkout@v7`, and v7.0.1 is a
  published, non-prerelease release on the current major line.

This is labelled a current release record, not an inferred historical
architecture rationale.

## Important boundary

Operator review establishes that the corpus labels were checked. It does not
establish maintainer agreement, PMF, or independent verifier operation. Those
remain separate evidence categories in Standing's trust model.
