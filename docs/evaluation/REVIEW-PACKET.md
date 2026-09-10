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

## Important boundary

Operator review establishes that the corpus labels were checked. It does not
establish maintainer agreement, PMF, or independent verifier operation. Those
remain separate evidence categories in Standing's trust model.
