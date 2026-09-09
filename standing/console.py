"""Disclosure-first HTML rendering for a read-only Standing console."""

from __future__ import annotations

from html import escape
from typing import Any, Sequence

from .lifecycle import DecisionSnapshot, StandingTimelineEvent
from .release import ReleaseGateResult


def render_console_html(
    snapshot: DecisionSnapshot,
    *,
    controlled_demo_disclosed: bool,
    release_gate: ReleaseGateResult,
    page_title: str = "Standing console",
) -> str:
    """Render a self-contained read-only view of one decision snapshot."""

    if not isinstance(controlled_demo_disclosed, bool):
        raise ValueError("controlled_demo_disclosed must be true or false")
    title = escape(page_title, quote=True)
    decision_id = escape(snapshot.decision_id, quote=True)
    revision = snapshot.revision
    revision_id = "NO ACTIVE REVISION" if revision is None else revision.revision_id
    revision_text = "No revision is active at this time." if revision is None else _revision_text(revision)
    standing = snapshot.standing
    state = "NO STANDING RESULT" if standing is None or standing.state is None else standing.state
    action = "—" if standing is None or standing.action is None else standing.action
    as_of = "current" if snapshot.as_of is None else str(snapshot.as_of)
    disclosure = (
        "CONTROLLED DEMO DATA — owner-controlled sandbox; fictional value; not vendor evidence."
        if controlled_demo_disclosed
        else ""
    )
    release_class = "ready" if release_gate.ready else "blocked"
    release_reasons = "".join(
        f"<li>{escape(reason)}</li>" for reason in release_gate.reasons
    ) or "<li>No release blockers.</li>"
    history_rows = "".join(_event_row(event) for event in snapshot.standing_history)
    if not history_rows:
        history_rows = '<tr><td colspan="6">No journal events at this time.</td></tr>'
    banner = f'<aside class="disclosure">{escape(disclosure)}</aside>' if disclosure else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{ color-scheme: light; font-family: system-ui, sans-serif; }}
    body {{ margin: 0; background: #f5f7fb; color: #162033; }}
    main {{ max-width: 1080px; margin: 0 auto; padding: 2rem; }}
    .disclosure {{ padding: 1rem; border: 2px solid #b45309; background: #fffbeb; color: #78350f; font-weight: 700; }}
    .card {{ margin-top: 1rem; padding: 1.25rem; background: white; border: 1px solid #d7deea; border-radius: .6rem; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: .8rem; }}
    .label {{ color: #526079; font-size: .8rem; text-transform: uppercase; letter-spacing: .05em; }}
    .value {{ margin-top: .25rem; font-size: 1.15rem; font-weight: 700; }}
    .state {{ color: #075985; }}
    .blocked {{ color: #b91c1c; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: .65rem; border-bottom: 1px solid #e5eaf2; text-align: left; vertical-align: top; }}
    th {{ color: #526079; font-size: .8rem; text-transform: uppercase; }}
    code {{ overflow-wrap: anywhere; }}
  </style>
</head>
<body>
  <main data-decision-id="{decision_id}" data-as-of="{escape(as_of, quote=True)}" data-release="{release_class}">
    {banner}
    <section class="card">
      <h1>{decision_id}</h1>
      <p>Read-only historical view at <strong>{escape(as_of)}</strong>.</p>
      <div class="grid">
        <div><div class="label">Standing</div><div class="value state">{escape(state)}</div></div>
        <div><div class="label">Last action</div><div class="value">{escape(action)}</div></div>
        <div><div class="label">Governing revision</div><div class="value"><code>{escape(revision_id)}</code></div></div>
        <div><div class="label">Release gate</div><div class="value {release_class}">{escape("READY" if release_gate.ready else "BLOCKED")}</div></div>
      </div>
      <p>{escape(revision_text)}</p>
    </section>
    <section class="card">
      <h2>Release evidence</h2>
      <ul>{release_reasons}</ul>
    </section>
    <section class="card">
      <h2>Standing history</h2>
      <table>
        <thead><tr><th>When</th><th>Event</th><th>Revision</th><th>State</th><th>Action</th><th>Explanation</th></tr></thead>
        <tbody>{history_rows}</tbody>
      </table>
    </section>
  </main>
</body>
</html>
"""


def _revision_text(revision: Any) -> str:
    body = revision.materialized_body()
    title = body.get("title")
    if isinstance(title, str) and title.strip():
        return f"{title.strip()} became effective at {revision.effective_from}."
    return f"This revision became effective at {revision.effective_from}."


def _event_row(event: StandingTimelineEvent) -> str:
    state = "—" if event.state is None else event.state
    action = "—" if event.action is None else event.action
    explanation = "—" if event.explanation is None else event.explanation
    revision = "—" if event.revision_id is None else event.revision_id
    event_type = "—" if event.event_type is None else event.event_type
    return (
        "<tr>"
        f"<td>{escape(str(event.occurred_at))}<br><code>{escape(event.event_id)}</code></td>"
        f"<td>{escape(event_type)}</td>"
        f"<td><code>{escape(revision)}</code></td>"
        f"<td>{escape(state)}</td>"
        f"<td>{escape(action)}</td>"
        f"<td>{escape(explanation)}</td>"
        "</tr>"
    )
