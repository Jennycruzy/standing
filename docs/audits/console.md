# Read-only console audit

Date: 2026-09-09

This is a dated audit snapshot. At the time it was written, the evaluation
manifest had no release-eligible cases. The current manifest has since been
expanded to eight human-reviewed public cases; see
[`docs/evaluation/cases.json`](../evaluation/cases.json).

The console is a static, read-only projection of the persisted revision and
standing journal. It supports a historical `--as-of` timestamp and visibly
labels the owner-controlled sandbox whenever sandbox evidence is rendered. It
also shows the release gate and its reasons, so an attractive page cannot imply
that the current controlled sandbox is trusted standing.

Lifecycle events such as waiver issuance are retained in the history but do
not replace the latest event that contains a standing state. A human waiver
can therefore be displayed beside an `EXPIRED` or `UNKNOWN` factual result
without relabelling that result as `ACCEPTED`.

The renderer is [`standing/console.py`](../../standing/console.py), and the
local entry point is [`scripts/render_console.py`](../../scripts/render_console.py).
The current evaluation manifest keeps the release gate blocked because it has
zero real cases.
