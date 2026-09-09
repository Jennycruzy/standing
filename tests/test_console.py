import unittest

from standing.console import render_console_html
from standing.lifecycle import DecisionRevision, DecisionSnapshot, StandingTimelineEvent
from standing.release import ReleaseGateResult


class ConsoleRenderingTests(unittest.TestCase):
    def test_console_puts_demo_disclosure_and_time_travel_state_in_visible_markup(self) -> None:
        revision = DecisionRevision(
            "decision",
            "r1",
            {"title": "Use <the> safe path"},
            100,
        )
        event = StandingTimelineEvent(
            "event-1",
            "decision",
            100.0,
            "r1",
            "EXPIRED",
            "block",
            "fingerprint",
            "Vendor value changed.",
            None,
            "standing_change",
        )
        snapshot = DecisionSnapshot("decision", 150, revision, event, (event,))
        release = ReleaseGateResult(False, ("A real vendor-expiry case is required before release.",))

        html = render_console_html(
            snapshot,
            controlled_demo_disclosed=True,
            release_gate=release,
        )

        self.assertIn("CONTROLLED DEMO DATA", html)
        self.assertIn('data-as-of="150"', html)
        self.assertIn("EXPIRED", html)
        self.assertIn("vendor-expiry", html)
        self.assertIn("Use &lt;the&gt; safe path", html)
        self.assertNotIn("Use <the> safe path", html)

    def test_console_can_render_without_a_demo_banner(self) -> None:
        snapshot = DecisionSnapshot("decision", None, None, None, ())
        html = render_console_html(
            snapshot,
            controlled_demo_disclosed=False,
            release_gate=ReleaseGateResult(True, ()),
        )

        self.assertNotIn("CONTROLLED DEMO DATA", html)
        self.assertIn("NO ACTIVE REVISION", html)
        self.assertIn("READY", html)


if __name__ == "__main__":
    unittest.main()
