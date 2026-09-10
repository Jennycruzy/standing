import tempfile
import unittest
from pathlib import Path

from standing.dashboard import CONTROLLED_DISCLOSURE, DashboardApp, render_dashboard_html
from standing.memory import create_memory_store


class DashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.store = create_memory_store(
            path=Path(self.directory.name) / "dashboard.db",
            tenant_id="dashboard-tests",
        )
        self.app = DashboardApp(self.store, demo=True)

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def test_landing_state_is_product_finding_and_discloses_controlled_source(self) -> None:
        state = self.app.state()

        self.assertEqual(state["summary"], "All remembered engineering decisions currently have standing.")
        self.assertEqual(state["primary_finding"]["decision_id"], "ACME-001")
        self.assertEqual(state["primary_finding"]["evaluation"]["state"], "STANDS")
        self.assertIn("CONTROLLED DEMO", state["disclosure"])
        self.assertEqual(state["demo"]["current_value"], 365)

    def test_fixed_demo_change_updates_temporal_evidence_and_expiry(self) -> None:
        state = self.app.action("break")

        self.assertEqual(state["primary_finding"]["evaluation"]["state"], "EXPIRED")
        condition = state["primary_finding"]["conditions"][0]
        self.assertEqual(condition["reference"]["accepted_value"], 90)
        self.assertEqual(
            [row["observation_uid"] for row in condition["observations"]],
            ["demo-initial", "demo-changed"],
        )
        self.assertEqual(state["demo"]["current_value"], 90)

    def test_resolve_supersedes_old_decision_and_leaves_replacement_active(self) -> None:
        self.app.action("break")
        state = self.app.action("resolve")

        all_decisions = {item["decision_id"]: item for item in state["decisions"]}
        self.assertEqual(all_decisions["ACME-001"]["body"]["status"], "SUPERSEDED")
        self.assertEqual(all_decisions["ACME-001"]["body"]["superseded_by"], "STORAGE-002")
        self.assertFalse(all_decisions["ACME-001"]["active"])
        self.assertTrue(all_decisions["STORAGE-002"]["active"])

    def test_human_confirmation_surface_promotes_only_the_fixed_proposal(self) -> None:
        state = self.app.state()
        pending = [proposal for proposal in state["proposals"] if proposal["status"] == "PENDING"]
        self.assertEqual(len(pending), 1)
        proposal_id = pending[0]["proposal_id"]

        state = self.app.action("confirm-proposal")

        confirmed = [proposal for proposal in state["proposals"] if proposal["proposal_id"] == proposal_id][0]
        self.assertEqual(confirmed["status"], "CONFIRMED")
        self.assertEqual(confirmed["confirmed_by"], "demo-human")
        self.assertEqual(
            [item["decision_id"] for item in state["decisions"] if item["decision_id"] == "AUDIT-003"],
            ["AUDIT-003"],
        )

    def test_html_contains_temporal_and_fixed_demo_surfaces(self) -> None:
        html = render_dashboard_html(self.app.state())

        for label in (
            "Decision graph",
            "Bitemporal time travel",
            "Interactive PR review",
            "Human confirmation",
            "Memory comparison",
            "BREAK DEMO ASSUMPTION",
            "RESTORE DEMO",
            "RECORD REPLACEMENT DECISION",
            "INSPECT DEMO WAIVER",
            "CONFIRM PROPOSAL",
            "Evidence provenance",
            "Real-world proof",
            "What we now believe was true",
            "What Standing knew then",
        ):
            self.assertIn(label, html)
        self.assertIn("data-graph-target", html)
        self.assertIn(CONTROLLED_DISCLOSURE, html)
        self.assertNotIn("destination address", html.lower())
        self.assertNotIn("private key", html.lower())

    def test_waiver_control_is_preview_only(self) -> None:
        result = self.app.action("waiver")

        self.assertEqual(result["status"], "PREVIEW ONLY")
        self.assertIn("No waiver is issued", result["disclosure"])


if __name__ == "__main__":
    unittest.main()
