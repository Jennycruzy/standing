import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from standing.artifacts import ArtifactSnapshot
from standing.model_review import (
    DECISION_OUTPUT_SCHEMA,
    DecisionProposal,
    EXTRACTION_OUTPUT_SCHEMA,
    REVIEW_OUTPUT_SCHEMA,
    ExtractionProposal,
    ModelCompletion,
    ModelDecisionExtractor,
    ModelExtractor,
    ModelReviewError,
    ModelReviewer,
    OpenAIResponsesClient,
    ReviewContext,
    confirm_extraction,
)


class FakeTransport:
    def __init__(self, data: dict[str, object]) -> None:
        self.data = data
        self.calls: list[dict[str, object]] = []

    def complete(self, **kwargs: object) -> ModelCompletion:
        self.calls.append(kwargs)
        return ModelCompletion("resp_test", self.data)


class FakeHttpResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload


class ModelReviewTests(unittest.TestCase):
    def test_artifact_snapshot_is_bounded_and_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact_path = root / "ADR-0042.md"
            artifact_path.write_text("Use Acme for archive persistence.\n", encoding="utf-8")

            snapshot = ArtifactSnapshot.read(artifact_path, root=root, captured_at=100)

        self.assertEqual(snapshot.path, "ADR-0042.md")
        self.assertEqual(snapshot.artifact_type, "ADR")
        self.assertEqual(snapshot.captured_at, 100)
        self.assertEqual(snapshot.size_bytes, len(snapshot.text.encode("utf-8")))
        self.assertEqual(snapshot.sha256, hashlib.sha256(snapshot.text.encode("utf-8")).hexdigest())

    def test_artifact_snapshot_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "inside"):
                ArtifactSnapshot.read("../outside.md", root=directory)

    def test_decision_extractor_returns_a_pending_proposal_bound_to_artifact(self) -> None:
        artifact_text = "Use Acme for archive persistence because retention is at least 365 days."
        transport = FakeTransport(
            {
                "decision_id": "ACME-001",
                "title": "Use Acme for archive persistence",
                "description": "Keep archive persistence on Acme.",
                "governed_paths": ["src/archive.py"],
                "conditions": [
                    {
                        "condition_key": "vendor.acme.retention_days",
                        "predicate": "retention_days >= 365",
                        "required": True,
                        "provenance": "INFERRED",
                        "unit": "days",
                    }
                ],
                "source_sentence": artifact_text,
                "rationale": "The artifact states the choice and its retention requirement.",
            }
        )

        proposal = ModelDecisionExtractor(transport, model_id="gpt-5.4-mini").propose(
            artifact_path="docs/ADR-0042.md",
            artifact_type="ADR",
            artifact_text=artifact_text,
            artifact_sha256=hashlib.sha256(artifact_text.encode("utf-8")).hexdigest(),
        )

        self.assertEqual(proposal.decision_id, "ACME-001")
        self.assertEqual(proposal.status, "PENDING")
        self.assertTrue(proposal.proposal_id.startswith("proposal:"))
        self.assertEqual(transport.calls[0]["schema"], DECISION_OUTPUT_SCHEMA)
        restored = DecisionProposal.from_mapping(proposal.as_dict())
        self.assertEqual(restored.fingerprint, proposal.fingerprint)

    def test_decision_extractor_rejects_artifact_hash_drift(self) -> None:
        transport = FakeTransport({})
        with self.assertRaisesRegex(ModelReviewError, "does not match"):
            ModelDecisionExtractor(transport, model_id="gpt-5.4-mini").propose(
                artifact_path="docs/ADR-0042.md",
                artifact_type="ADR",
                artifact_text="source",
                artifact_sha256="a" * 64,
            )

    def test_reviewer_returns_only_known_targets_and_advisory_fields(self) -> None:
        transport = FakeTransport(
            {
                "decision_ids": ["decision-one"],
                "condition_keys": ["vendor.acme.retention_days"],
                "questions": ["Has the published value changed?"],
                "rationale": "The changed file is governed by this decision.",
            }
        )
        context = ReviewContext(
            changed_paths=("src/service.py",),
            candidate_decisions=(
                {
                    "decision_id": "decision-one",
                    "conditions": [
                        {"condition_key": "vendor.acme.retention_days"},
                    ],
                },
            ),
            boot_changes=({"state": "CONTESTED"},),
        )

        proposal = ModelReviewer(transport, model_id="gpt-5.4").review(context)

        self.assertEqual(proposal.decision_ids, ("decision-one",))
        self.assertEqual(proposal.condition_keys, ("vendor.acme.retention_days",))
        self.assertEqual(proposal.response_id, "resp_test")
        self.assertNotIn("action", proposal.as_dict())
        self.assertNotIn("state", proposal.as_dict())
        self.assertEqual(transport.calls[0]["schema_name"], "standing_review_proposal")
        self.assertEqual(transport.calls[0]["schema"], REVIEW_OUTPUT_SCHEMA)

    def test_reviewer_rejects_model_hallucinated_identifiers(self) -> None:
        transport = FakeTransport(
            {
                "decision_ids": ["not-a-candidate"],
                "condition_keys": [],
                "questions": [],
                "rationale": "unsupported",
            }
        )
        context = ReviewContext(
            changed_paths=("src/service.py",),
            candidate_decisions=(
                {"decision_id": "decision-one", "conditions": []},
            ),
        )

        with self.assertRaises(ModelReviewError):
            ModelReviewer(transport, model_id="gpt-5.4").review(context)

    def test_reviewer_rejects_authority_fields_from_model_output(self) -> None:
        transport = FakeTransport(
            {
                "decision_ids": [],
                "condition_keys": [],
                "questions": [],
                "rationale": "unsupported",
                "action": "block",
            }
        )
        context = ReviewContext(
            changed_paths=("src/service.py",),
            candidate_decisions=(),
        )

        with self.assertRaises(ModelReviewError):
            ModelReviewer(transport, model_id="gpt-5.4").review(context)

    def test_extractor_parses_typed_value_and_binds_requested_source(self) -> None:
        transport = FakeTransport(
            {
                "condition_key": "vendor.acme.retention_days",
                "value_json": "365",
                "source_url": "https://vendor.example.com/retention",
                "effective_from": 1_700_000_000,
                "rationale": "The policy table states a 365-day value.",
            }
        )

        proposal = ModelExtractor(transport, model_id="gpt-5.4-mini").propose(
            condition_key="vendor.acme.retention_days",
            predicate="retention_days >= 365",
            source_url="https://vendor.example.com/retention",
            source_text="Retention: 365 days.",
        )

        self.assertEqual(proposal.value, 365)
        self.assertEqual(proposal.source_url, "https://vendor.example.com/retention")
        self.assertEqual(transport.calls[0]["schema"], EXTRACTION_OUTPUT_SCHEMA)

    def test_extractor_rejects_invalid_value_and_source_drift(self) -> None:
        invalid_value = FakeTransport(
            {
                "condition_key": "vendor.acme.retention_days",
                "value_json": "not-json",
                "source_url": "https://vendor.example.com/retention",
                "effective_from": 1_700_000_000,
                "rationale": "unsupported",
            }
        )
        with self.assertRaises(ModelReviewError):
            ModelExtractor(invalid_value, model_id="gpt-5.4-mini").propose(
                condition_key="vendor.acme.retention_days",
                predicate="retention_days >= 365",
                source_url="https://vendor.example.com/retention",
                source_text="Retention: 365 days.",
            )

        source_drift = FakeTransport(
            {
                "condition_key": "vendor.acme.retention_days",
                "value_json": "365",
                "source_url": "https://other.example.net/retention",
                "effective_from": 1_700_000_000,
                "rationale": "unsupported",
            }
        )
        with self.assertRaises(ModelReviewError):
            ModelExtractor(source_drift, model_id="gpt-5.4-mini").propose(
                condition_key="vendor.acme.retention_days",
                predicate="retention_days >= 365",
                source_url="https://vendor.example.com/retention",
                source_text="Retention: 365 days.",
            )

    def test_human_confirmation_hashes_snapshot_and_returns_explicit_records(self) -> None:
        proposal = ExtractionProposal(
            condition_key="vendor.acme.retention_days",
            value=365,
            source_url="https://vendor.example.com/retention",
            effective_from=1_700_000_000,
            rationale="The source states the value.",
            model_id="gpt-5.4-mini",
            response_id="resp_test",
        )
        snapshot = b"Retention: 365 days."

        confirmed = confirm_extraction(
            proposal,
            source_snapshot=snapshot,
            confirmed_by="operator:human",
            confirmed_at=1_700_000_100,
            publisher_id="vendor-acme",
            review_note="I checked the source text and effective date.",
        )

        self.assertEqual(confirmed.source_sha256, hashlib.sha256(snapshot).hexdigest())
        body, metadata = confirmed.as_condition_reference()
        self.assertEqual(body["accepted_value"], 365)
        self.assertEqual(body["observation_uids"], [confirmed.observation_uid])
        self.assertEqual(metadata["confirmed_by"], "operator:human")
        self.assertEqual(metadata["publisher_id"], "vendor-acme")
        self.assertEqual(confirmed.as_observation()["provenance"]["operator_id"], "operator:human")
        with self.assertRaises(ModelReviewError):
            confirm_extraction(
                proposal,
                source_snapshot=b"",
                confirmed_by="operator:human",
                confirmed_at=1_700_000_100,
                review_note="checked",
            )

    def test_responses_client_parses_structured_output_without_logging_key(self) -> None:
        request_holder: dict[str, object] = {}

        def opener(request: object, *, timeout: float) -> FakeHttpResponse:
            request_holder["request"] = request
            request_holder["timeout"] = timeout
            return FakeHttpResponse(
                json.dumps(
                    {
                        "id": "resp_api",
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {"type": "output_text", "text": '{"ok":true}'},
                                ],
                            }
                        ],
                    }
                ).encode("utf-8")
            )

        client = OpenAIResponsesClient(
            "sk-test-secret",
            timeout_seconds=7,
            opener=opener,
        )
        completion = client.complete(
            model="gpt-5.4",
            instructions="Return JSON.",
            input_text="{}",
            schema_name="test_schema",
            schema={"type": "object"},
        )

        self.assertEqual(completion.response_id, "resp_api")
        self.assertEqual(completion.data, {"ok": True})
        request = request_holder["request"]
        self.assertIn("Authorization", request.headers)  # type: ignore[union-attr]
        self.assertEqual(request_holder["timeout"], 7.0)

    def test_from_env_does_not_accept_an_empty_key(self) -> None:
        with patch.dict(os.environ, {"MODEL_REVIEW_TEST_KEY": ""}, clear=False):
            with self.assertRaises(ModelReviewError):
                OpenAIResponsesClient.from_env(env_name="MODEL_REVIEW_TEST_KEY")


if __name__ == "__main__":
    unittest.main()
