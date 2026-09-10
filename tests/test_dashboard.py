import tempfile
import unittest
from pathlib import Path

from standing.dashboard import CONTROLLED_DISCLOSURE, DashboardApp, render_dashboard_html, render_landing_html
from standing.memory import create_memory_store


class DashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.store = create_memory_store(
            path=Path(self.directory.name) / "dashboard.db",
            tenant_id="dashboard-tests",
        )
        self.app = DashboardApp(self.store, sandbox=True)

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def test_landing_state_is_product_finding_and_discloses_controlled_source(self) -> None:
        state = self.app.state()

        self.assertEqual(state["summary"], "All remembered engineering decisions currently have standing.")
        self.assertEqual(state["primary_finding"]["decision_id"], "ACME-001")
        self.assertEqual(state["primary_finding"]["evaluation"]["state"], "STANDS")
        self.assertIn("CONTROLLED SCENARIO", state["disclosure"])
        self.assertEqual(state["sandbox"]["current_value"], 365)

    def test_fixed_sandbox_change_updates_temporal_evidence_and_expiry(self) -> None:
        state = self.app.action("break")

        self.assertEqual(state["primary_finding"]["evaluation"]["state"], "EXPIRED")
        condition = state["primary_finding"]["conditions"][0]
        self.assertEqual(condition["reference"]["accepted_value"], 90)
        self.assertEqual(
            [row["observation_uid"] for row in condition["observations"]],
            ["sandbox-initial", "sandbox-changed"],
        )
        self.assertEqual(state["sandbox"]["current_value"], 90)
        self.assertEqual(state["review_result"]["action"], "BLOCK")
        self.assertEqual(state["review_result"]["decision_id"], "ACME-001")

        time_travel = state["sandbox"]["time_travel"]
        decision_point = next(row for row in time_travel if row["point"] == 1770768000)
        self.assertEqual(decision_point["valid"]["value"], 365)
        self.assertEqual(decision_point["known"]["value"], 365)
        changed_point = next(row for row in time_travel if row["point"] == 1788739200)
        self.assertEqual(changed_point["valid"]["value"], 90)
        self.assertEqual(changed_point["known"]["value"], 365)

    def test_review_and_memory_proof_are_backend_results(self) -> None:
        self.app.action("break")
        state = self.app.action("memory-comparison")

        comparison = state["memory_comparison"]
        self.assertEqual(comparison["memory_on"]["decision_found"], "ACME-001")
        self.assertEqual(comparison["memory_on"]["current_fact"], 90)
        self.assertEqual(comparison["memory_on"]["protection"], "BLOCK")
        self.assertIsNone(comparison["memory_removed"]["decision_found"])
        self.assertEqual(
            comparison["memory_removed"]["protection"],
            "HISTORICAL PROTECTION UNAVAILABLE",
        )

    def test_reset_restores_current_decision_without_erasing_history(self) -> None:
        self.app.action("break")
        self.app.action("resolve")
        state = self.app.action("reset")

        decisions = {item["decision_id"]: item for item in state["decisions"]}
        self.assertEqual(decisions["ACME-001"]["body"]["status"], "CURRENT")
        self.assertNotIn("STORAGE-002", decisions)
        self.assertEqual(state["sandbox"]["current_value"], 365)

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
        self.assertEqual(confirmed["confirmed_by"], "sandbox-human")
        self.assertEqual(
            [item["decision_id"] for item in state["decisions"] if item["decision_id"] == "AUDIT-003"],
            ["AUDIT-003"],
        )

    def test_html_contains_temporal_and_fixed_sandbox_surfaces(self) -> None:
        html = render_dashboard_html(self.app.state())

        for label in (
            "Decision graph",
            "Bitemporal time travel",
            "Standing Review",
            "Human confirmation",
            "Compare with memory removed",
            "BREAK ASSUMPTION",
            "RESET SANDBOX",
            "RECORD REPLACEMENT DECISION",
            "VIEW WAIVER POLICY",
            "CONFIRM PROPOSAL",
            "Evidence identity",
            "Public repository evaluation",
            "Live historical verification path",
            "What we now believe was true",
            "What Standing knew then",
        ):
            self.assertIn(label, html)
        self.assertIn("data-graph-target", html)
        self.assertIn("Engineering intent workspace", html)
        self.assertIn("What requires engineering attention", html)
        self.assertIn(CONTROLLED_DISCLOSURE, html)
        self.assertEqual(self.app.state()["partner_proof"]["acp_job_id"], "77748")
        self.assertIn("app.virtuals.io", html)
        self.assertIn("API access may require credentials", html)
        self.assertIn("Standing Verifier", html)
        self.assertIn("139452", html)
        self.assertIn("Standing Requestor", html)
        self.assertIn("139450", html)
        self.assertIn("Registered agent identities", html)
        self.assertIn("84973", html)
        self.assertIn("basescan.org/tx/", html)
        self.assertNotIn("destination address", html.lower())
        self.assertNotIn("private key", html.lower())

    def test_landing_page_has_product_story_and_console_entry(self) -> None:
        html = render_landing_html(self.app.state())

        for label in ("Code remembers", "Reasoning should too", "Open console", "bitemporal", "Evidence chain"):
            self.assertIn(label, html)
        self.assertIn('href="/console"', html)

    def test_waiver_control_is_preview_only(self) -> None:
        result = self.app.action("waiver")

        self.assertEqual(result["status"], "PREVIEW ONLY")
        self.assertIn("No waiver is issued", result["disclosure"])


if __name__ == "__main__":
    unittest.main()
