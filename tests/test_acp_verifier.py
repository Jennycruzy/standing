import json
import unittest
from pathlib import Path
from typing import Any

from standing.acceptance import AcceptancePolicy, AcceptanceResult, AcceptanceStatus
from standing.acp import (
    AcpVerifierClient,
    AcpVerifierError,
    load_acp_config,
    parse_verifier_delivery,
)


class AcpVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_acp_config(Path(__file__).parents[1] / "config" / "acp.json")
        self.condition_key = "vendor.acme.retention_days"
        self.observer = "0x1111111111111111111111111111111111111111"
        self.acceptance = AcceptanceResult(
            condition_key=self.condition_key,
            status=AcceptanceStatus.CONTESTED,
            accepted_value=None,
            vendor_primary_present=True,
            independent_observer_addresses=(self.observer,),
            manual_approval=True,
            observation_uids=("0xold",),
            reasons=("A second independent reading is required.",),
        )

    def test_config_contains_job_and_spend_limits(self) -> None:
        self.assertEqual(self.config.chain_id, 8453)
        self.assertEqual(self.config.offering_name, "published_condition_check")
        self.assertEqual(self.config.budget_usdc, 0.01)
        self.assertEqual(self.config.max_job_usdc, 0.01)
        self.assertTrue(self.config.start_verifier)

    def test_parser_requires_one_typed_verifier_delivery(self) -> None:
        result = {
            "jobId": "76973",
            "status": "completed",
            "entries": [],
        }

        with self.assertRaises(AcpVerifierError):
            parse_verifier_delivery(
                result,
                condition_key=self.condition_key,
                expected_source_type="verifier",
            )

    def test_client_hires_only_when_acceptance_is_unsatisfied(self) -> None:
        calls: list[dict[str, Any]] = []

        def runner(request: dict[str, Any], **_: Any) -> dict[str, Any]:
            calls.append(request)
            return self._completed_result()

        client = AcpVerifierClient(
            adapter_dir=Path(__file__).parents[1] / "acp-adapter",
            config=self.config,
            environment={},
            runner=runner,
        )
        observation = client.hire_verifier(
            self.condition_key,
            self.observer,
            acceptance=self.acceptance,
            spent_today_usdc=0.0,
        )

        self.assertEqual(observation.job_id, "76973")
        self.assertEqual(observation.value, 90)
        self.assertEqual(observation.disclosure, "CONTROLLED DEMO DATA")
        self.assertEqual(observation.provenance.operator_id, "operator:standing")
        self.assertEqual(observation.unit, "days")
        self.assertEqual(observation.extraction_method, "JSON_PATH")
        self.assertEqual(observation.observed_at, 1_000)
        self.assertEqual(calls[0]["providerAddress"], self.observer)
        self.assertEqual(calls[0]["requirement"], {"conditionKey": self.condition_key})
        self.assertNotIn("privateKey", json.dumps(calls[0]))

    def test_client_rejects_a_job_when_acceptance_already_succeeds(self) -> None:
        accepted = AcceptanceResult(
            condition_key=self.condition_key,
            status=AcceptanceStatus.ACCEPTED,
            accepted_value=365,
            vendor_primary_present=True,
            independent_observer_addresses=("0x111", "0x222"),
            manual_approval=True,
            observation_uids=("0xone", "0xtwo"),
            reasons=(),
        )
        client = AcpVerifierClient(
            adapter_dir=Path(__file__).parents[1] / "acp-adapter",
            config=self.config,
            environment={},
            runner=lambda *_args, **_kwargs: self._completed_result(),
        )

        with self.assertRaises(AcpVerifierError):
            client.hire_verifier(
                self.condition_key,
                self.observer,
                acceptance=accepted,
                spent_today_usdc=0.0,
            )

    def test_daily_spend_cap_is_checked_before_bridge_call(self) -> None:
        called = False

        def runner(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            nonlocal called
            called = True
            return self._completed_result()

        client = AcpVerifierClient(
            adapter_dir=Path(__file__).parents[1] / "acp-adapter",
            config=self.config,
            environment={},
            runner=runner,
        )

        with self.assertRaises(AcpVerifierError):
            client.hire_verifier(
                self.condition_key,
                self.observer,
                acceptance=self.acceptance,
                spent_today_usdc=self.config.daily_spend_usdc,
            )
        self.assertFalse(called)

    def test_client_can_resume_an_existing_job_without_creating_another(self) -> None:
        calls: list[dict[str, Any]] = []

        def runner(request: dict[str, Any], **_: Any) -> dict[str, Any]:
            calls.append(request)
            return self._completed_result()

        client = AcpVerifierClient(
            adapter_dir=Path(__file__).parents[1] / "acp-adapter",
            config=self.config,
            environment={},
            runner=runner,
        )
        client.hire_verifier(
            self.condition_key,
            self.observer,
            acceptance=self.acceptance,
            spent_today_usdc=0.0,
            job_id="77716",
        )

        self.assertEqual(calls[0]["jobId"], "77716")

    def test_client_can_target_an_external_provider_without_starting_local_seller(self) -> None:
        calls: list[dict[str, Any]] = []

        def runner(request: dict[str, Any], **_: Any) -> dict[str, Any]:
            calls.append(request)
            return self._completed_result()

        client = AcpVerifierClient(
            adapter_dir=Path(__file__).parents[1] / "acp-adapter",
            config=self.config,
            environment={},
            runner=runner,
        )
        client.hire_verifier(
            self.condition_key,
            self.observer,
            acceptance=self.acceptance,
            spent_today_usdc=0.0,
            start_verifier=False,
            offering_name="external_condition_check",
        )

        self.assertEqual(calls[0]["offeringName"], "external_condition_check")
        self.assertFalse(calls[0]["startVerifier"])

    def test_client_rejects_an_invalid_resume_job_id(self) -> None:
        client = AcpVerifierClient(
            adapter_dir=Path(__file__).parents[1] / "acp-adapter",
            config=self.config,
            environment={},
            runner=lambda *_args, **_kwargs: self._completed_result(),
        )

        with self.assertRaises(AcpVerifierError):
            client.hire_verifier(
                self.condition_key,
                self.observer,
                acceptance=self.acceptance,
                spent_today_usdc=0.0,
                job_id="not-a-job",
            )

    def _completed_result(self) -> dict[str, Any]:
        delivery = {
            "condition_key": self.condition_key,
            "value": 90,
            "source_type": "verifier",
            "source_url": "https://vendor.example/retention",
            "observation_uid": "0x" + "ab" * 32,
            "observer_address": self.observer,
            "effective_from": 1_000,
            "observed_at": 1_000,
            "recorded_at": 1_000,
            "value_type": "number",
            "unit": "days",
            "extraction_method": "JSON_PATH",
            "extraction_version": "retention-json-v1",
            "evidence_hash": "a" * 64,
            "source_snapshot_hash": "a" * 64,
            "demo_controlled": True,
            "note": "CONTROLLED DEMO DATA — The published page reports 90 days.",
            "disclosure": "CONTROLLED DEMO DATA",
            "provenance": {
                "operator_id": "operator:standing",
                "source_id": "source:vendor.example",
                "extractor_id": "extractor:standing.v1",
            },
        }
        return {
            "jobId": "76973",
            "status": "completed",
            "entries": [
                {
                    "kind": "message",
                    "contentType": "application/json",
                    "content": json.dumps(delivery, sort_keys=True),
                }
            ],
        }


if __name__ == "__main__":
    unittest.main()
