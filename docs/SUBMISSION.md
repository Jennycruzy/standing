# Standing submission kit

This file is the final-day control sheet. Replace the four placeholders before
submitting:

```text
LIVE_URL=<deployed dashboard URL>
VIDEO_URL=<2–5 minute public demo URL>
POST_1_URL=<public launch post URL>
POST_2_URL=<second public post URL>
```

## Submission description

Standing remembers why code was written and blocks changes when the facts that
justified that code are no longer true. It is a temporal system of record for
engineering intent: decisions and their governed paths live in Sibyl Memory;
stale evidence triggers a Virtuals ACP verifier; observations are recorded
through Base EAS; and a deterministic evaluator returns STANDS, EXPIRED,
UNKNOWN, or CONTESTED. Its bitemporal model separately answers what the world
was doing and what the team could have known at the time, preserving history
through evidence and decision supersession.

The interactive controlled demo is explicitly fictional and owner-operated. It
proves the complete product workflow deterministically. The repository also
contains source-linked real-world evaluation candidates. Independent verifier
operation and third-party PMF confirmation remain disclosed release gaps.

## Three-minute demo script

Keep one story on screen. Do not tour every file or integration.

### 0:00–0:20 — Thesis and fresh recall

Say: “A software decision has standing only while the facts that justified it
remain true.” Start a fresh terminal and run:

```sh
standing boot
standing dashboard --demo
```

Explain that the fresh process recalls ACME-001 and its governed code through
Sibyl-backed memory.

### 0:20–0:50 — Original decision and time travel

Open the dashboard. Show ACME-001: use fictional Acme because retention is at
least 365 days. Move the time control to the decision date. Point out the two
answers: what Standing now believes was true, and what Standing knew then.

### 0:50–1:30 — Break, observe, and block

Point to the **CONTROLLED FICTIONAL DEMO** disclosure, then click **BREAK DEMO
ASSUMPTION**. Run the preloaded review. Explain the causal chain:

```text
stale evidence → verifier reads source → observation → temporal acceptance
→ 90 days becomes canonical → ACME-001 expires → exact governed path blocks
```

Open evidence provenance and show the source, method, effective time, recorded
time, and supersession link. Do not call same-owner observations independent.

### 1:30–2:05 — Prove memory is load-bearing

Toggle **MEMORY OFF** and rerun the identical review. The external fact still
exists, but the decision, original assumption, governed path, and historical
protection disappear. Toggle memory back on and show the block returns.

### 2:05–2:35 — Finish the lifecycle

Click **RECORD REPLACEMENT DECISION**, then rerun review. Show ACME-001 as
SUPERSEDED, STORAGE-002 as current, and the result as ALLOW. Emphasize that
Standing does not end at detection and never erases the old reasoning.

### 2:35–3:00 — Real-world proof and honest boundary

Show the real-world evaluation packet and one official vendor source. Say:
“The controlled flow is deterministic; these public cases test the same model
against genuine decisions. Operator independence has not yet been demonstrated,
so we report that as a limitation rather than manufacturing consensus.” Close
with the thesis.

## Public post 1 — product launch

```text
Software keeps the code but forgets why it was written.

I built Standing: a temporal system of record for engineering intent. It
remembers the assumptions behind a decision, revalidates stale external facts,
finds the code still governed by expired reasoning, and blocks unsafe changes.

The key distinction: what was actually true vs what the team could have known
at the time. Standing never rewrites history when later evidence arrives.

Demo: LIVE_URL
Code: https://github.com/Jennycruzy/standing
Video: VIDEO_URL

#SibylHackathon #BuildInPublic
```

## Public post 2 — technical proof

```text
Standing's end-to-end path:

engineering decision → Sibyl Memory → changed code → stale evidence → Virtuals
ACP verification → Base EAS observation → temporal acceptance → deterministic
STANDS / EXPIRED / UNKNOWN / CONTESTED → waiver or replacement

The public Acme interaction is clearly labelled as a controlled fictional demo.
Same-owner verifier evidence proves protocol/transport integrity, not operator
independence; that limitation remains visible. The repo includes the temporal
tests, deletion test, failed-job history, trust model, and real-world review
packet.

Demo: LIVE_URL
Code: https://github.com/Jennycruzy/standing
```

## Final checklist

- [ ] Deploy `render.yaml` and verify `/api/state` returns HTTP 200.
- [ ] Replace all four placeholders at the top of this file.
- [ ] Record the demo in one continuous 2–5 minute take.
- [ ] Use a fresh process for the memory-recall opening.
- [ ] Keep the controlled-demo disclosure visible during the mutation.
- [ ] Show memory on/off and replacement/allow; do not stop at BLOCKED.
- [ ] Open at least one genuine public vendor source.
- [ ] Publish two public posts and save their URLs.
- [ ] Confirm the GitHub repository is public and the MIT license is visible.
- [ ] Run the validation commands immediately before submission.
- [ ] Submit before the deadline in `docs/preflight.json`.

## Final validation

```sh
python -m unittest discover -s tests -p 'test_*.py'
npm --prefix acp-adapter test
npm --prefix acp-adapter run typecheck
standing deletion-test
.preflight-venv/bin/python scripts/check_release.py
```

The final release check is expected to remain non-zero until human-reviewed
real cases and a genuinely independent operator exist. That is an explicitly
reported trust boundary, not a reason to hide or weaken the gate.
