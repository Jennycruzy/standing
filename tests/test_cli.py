import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from standing.cli import main
from standing.memory import create_memory_store


class CliTests(unittest.TestCase):
    def test_sandbox_seed_is_recalled_and_blocks_from_new_cli_invocations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            memory_path = Path(directory) / "fresh-process-proof.db"
            common = [
                "--memory-path",
                str(memory_path),
                "--tenant-id",
                "fresh-process-proof",
            ]

            def invoke(*arguments: str) -> dict[str, object]:
                completed = subprocess.run(
                    [sys.executable, "-m", "standing", *common, *arguments],
                    cwd=Path(__file__).resolve().parents[1],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                return json.loads(completed.stdout)

            self.assertEqual(invoke("proof-seed")["action"], "BLOCK")
            self.assertGreater(invoke("boot")["journal_entries"], 0)

            recalled = invoke("review", "src/archive.py")
            self.assertEqual(recalled["decisions_found"], 1)
            self.assertTrue(recalled["blocked"])
            self.assertEqual(recalled["decisions"][0]["decision_id"], "ACME-001")

    def test_condition_query_defaults_to_accepted_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            memory_path = Path(directory) / "memory.db"
            store = create_memory_store(path=memory_path, tenant_id="cli-condition-tests")
            try:
                store.save_observation(
                    "pending-observation",
                    {
                        "condition_key": "vendor.acme.retention_days",
                        "value": 365,
                        "value_type": "number",
                        "unit": "days",
                        "effective_from": "2026-01-01",
                        "observed_at": "2026-01-02",
                        "recorded_at": "2026-01-03",
                        "source_url": "https://docs.acme.example/retention",
                        "source_type": "vendor_primary",
                        "attester": "attester:acme",
                        "operator_id": "operator:acme",
                        "extraction_method": "HTML_SELECTOR",
                        "extraction_version": "retention-html-v1",
                        "observation_uid": "pending-observation",
                        "evidence_hash": "a" * 64,
                        "notes": "pending",
                    },
                )
            finally:
                store.close()

            output = io.StringIO()
            with redirect_stdout(output):
                result = main(
                    [
                        "--memory-path",
                        str(memory_path),
                        "--tenant-id",
                        "cli-condition-tests",
                        "condition",
                        "vendor.acme.retention_days",
                    ]
                )

            self.assertEqual(result, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["status"], "UNKNOWN")
            self.assertIsNone(payload["observation"])

    def test_decision_ingest_persists_bounded_artifact_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            memory_path = Path(directory) / "memory.db"
            output = io.StringIO()
            with redirect_stdout(output):
                result = main(
                    [
                        "--memory-path",
                        str(memory_path),
                        "--tenant-id",
                        "cli-tests",
                        "decision",
                        "ingest",
                        "docs/WALKTHROUGH.md",
                    ]
                )
            self.assertEqual(result, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["command"], "decision ingest")
            self.assertEqual(payload["artifact"]["artifact_type"], "DESIGN_DOCUMENT")

            store = create_memory_store(path=memory_path, tenant_id="cli-tests")
            try:
                self.assertEqual(len(store.list_artifacts()), 1)
                self.assertNotIn("text", payload["artifact"])
            finally:
                store.close()

    def test_memory_proof_runs_the_post_change_controlled_scenario(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["memory-proof"])

        self.assertEqual(result, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["command"], "memory-proof")
        self.assertEqual(payload["external_fact"]["retention_days"], 90)
        self.assertTrue(payload["memory_on"]["expiry_detected"])
        self.assertEqual(payload["memory_on"]["protection"], "BLOCK")
        self.assertIsNone(payload["memory_off"]["decision_found"])
        self.assertEqual(payload["memory_off"]["protection"], "HISTORICAL PROTECTION UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
