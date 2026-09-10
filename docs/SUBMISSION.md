# Standing submission kit

This file is the final-day control sheet. Publish and add the remaining product
walkthrough before submitting:

```text
LIVE_URL=https://standing-o1sj.onrender.com
WALKTHROUGH_URL=<2–5 minute public product walkthrough URL>
POST_1_URL=https://x.com/jennyoliver57/status/2097685282598346909
POST_2_URL=https://x.com/jennyoliver57/status/2098056302916190634
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

The interactive controlled sandbox is explicitly fictional and deterministic. It
shows the complete product workflow while the repository separately contains
genuine source extraction, completed partner records, and three human-reviewed,
source-linked public cases.

## Three-minute product walkthrough

Keep one story on screen. Do not tour every file or integration.

### 0:00–0:20 — Thesis and fresh recall

Say: “A software decision has standing only while the facts that justified it
remain true.” Start a fresh terminal and run:

```sh
date -u
git rev-parse --short HEAD
PROOF_DB=./standing-proof.db
.venv/bin/standing --memory-path "$PROOF_DB" proof-seed
.venv/bin/standing --memory-path "$PROOF_DB" boot
.venv/bin/standing --memory-path "$PROOF_DB" review src/archive.py
.venv/bin/standing dashboard --sandbox
```

Each `standing` invocation exits before the next starts. Point out that the
second and third processes recall ACME-001 and its governed code from the same
Sibyl-backed store. Keep the UTC timestamp or commit hash visible in the same
continuous, unedited recording.

### 0:20–0:45 — Original decision and time travel

Open the dashboard. Show ACME-001: use fictional Acme because retention is at
least 365 days. Move the time control to the decision date. Point out the two
answers: what Standing now believes was true, and what Standing knew then.

### 0:45–1:20 — Break, observe, and block

Point to the **CONTROLLED SCENARIO — FICTIONAL ACME** disclosure, then click
**BREAK ASSUMPTION**. Explain exactly what is happening: this safe control
deterministically replays the source-change path locally. Then show the live
partner-proof links, which separately prove the completed verifier transport:

```text
dashboard replay: source change → temporal acceptance → canonical 90 days
→ ACME-001 expires → exact governed path blocks

live proof: ACP job → verifier source extraction → Base EAS observation
→ readback → Sibyl update → ERC-8004 feedback
```

Open evidence provenance and show the source, extraction method, effective
time, recorded time, and supersession link.

### 1:20–1:45 — Prove memory is load-bearing

Press **RUN MEMORY PROOF** and show the backend's identical review with a fresh
empty store. The external fact still exists, but the decision, original
assumption, governed path, and historical protection disappear in the memory-
removed arm.

### 1:45–2:15 — Finish the lifecycle

Click **RECORD REPLACEMENT DECISION**, then rerun review. Show ACME-001 as
SUPERSEDED, STORAGE-002 as current, and the result as ALLOW. Emphasize that
Standing does not end at detection and never erases the old reasoning.

### 2:15–2:50 — Partner and real-world proof

Open **Live historical proof** in the dashboard. Open the public Virtuals ACP
scan, point to completed job `77748`, and open the Base EAS transaction to show
the integrations doing the product's verification work. Then show the real-world evaluation packet and
one official vendor source. Say:
“The controlled flow is deterministic, and these three human-reviewed public
cases test the same temporal model against public repository evidence, stale
dependencies, and vendor changes.” Close with the thesis.

### 2:50–3:00 — Close

Say: “Standing remembers why software exists, knows when that reason stops
being true, and stops teams from unknowingly building on expired assumptions.”

## Public post 1 — product launch

```text
Software keeps the code but forgets why it was written.

I built Standing: a temporal system of record for engineering intent. It
remembers the assumptions behind a decision, revalidates stale external facts,
finds the code still governed by expired reasoning, and blocks unsafe changes.

The key distinction: what was actually true vs what the team could have known
at the time. Standing never rewrites history when later evidence arrives.

Live Standing: LIVE_URL
Code: https://github.com/Jennycruzy/standing
Product walkthrough: WALKTHROUGH_URL

@sibylcap @base @virtuals_io #SibylHackathon #BuildInPublic
```

## Public post 2 — technical proof

```text
Standing's end-to-end path:

engineering decision → Sibyl Memory → changed code → stale evidence → Virtuals
ACP verification → Base EAS observation → temporal acceptance → deterministic
STANDS / EXPIRED / UNKNOWN / CONTESTED → waiver or replacement

The public Acme interaction is clearly labelled as a controlled Fictional Acme scenario.
The repo includes genuine source extraction, temporal tests, fresh-process memory proof,
the trust model, onchain evidence, and three human-reviewed real-world cases.

Live Standing: LIVE_URL
Code: https://github.com/Jennycruzy/standing

@sibylcap @base @virtuals_io
```

## Final checklist

- [ ] Deploy `render.yaml` and verify `/api/state` returns HTTP 200.
- [ ] Replace `WALKTHROUGH_URL` at the top of this file.
- [ ] Record the product walkthrough in one continuous 2–5 minute take.
- [ ] Run `proof-seed`, `boot`, and `review` as separate CLI processes against
      the same proof database.
- [ ] Show `date -u` or `git rev-parse --short HEAD` in that same unedited shot.
- [ ] Keep the controlled-scenario disclosure visible during the mutation.
- [ ] Show Memory Proof and replacement/allow; do not stop at BLOCKED.
- [ ] Open at least one genuine public vendor source.
- [ ] Open the completed ACP job and Base EAS transaction from the dashboard.
- [x] Publish two public posts and save their URLs.
- [ ] Confirm the GitHub repository is public and the MIT license is visible.
- [ ] Run the validation commands immediately before submission.
- [ ] Submit before the deadline in `docs/preflight.json`.

## Final validation

```sh
make verify
```

The real-world corpus gates now pass. The separate strict trust gate remains
non-zero until external operator independence is recorded; that is a disclosed
evidence limitation rather than a failed product verification command.
