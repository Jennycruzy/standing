import unittest
from pathlib import Path

from eth_abi import encode  # type: ignore[attr-defined]

from standing.reputation import (
    decode_feedback,
    evidence_hash,
    feedback_calldata,
    last_index_calldata,
    load_reputation_config,
    read_feedback_calldata,
)


class ReputationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_reputation_config(Path(__file__).parents[1] / "config/reputation.json")
        self.observer = "0x1111111111111111111111111111111111111111"
        self.client = "0x2222222222222222222222222222222222222222"

    def test_config_and_calldata_are_loaded_without_private_keys(self) -> None:
        feedback = feedback_calldata(
            self.config,
            value=self.config.confirmed_value,
            observer_address=self.observer,
            endpoint="https://example.com/source",
            feedback_uri="https://example.com/evidence",
            feedback_hash=evidence_hash({"observation_uid": "0x" + "ab" * 32}),
        )
        self.assertNotEqual(feedback[:4], b"\x00" * 4)
        self.assertGreater(len(feedback), 4)
        self.assertGreater(len(last_index_calldata(self.config, self.client)), 4)
        self.assertGreater(len(read_feedback_calldata(self.config, self.client, 1)), 4)
        self.assertEqual(self.config.client_key_env, "WHITELISTED_WALLET_PRIVATE_KEY")

    def test_feedback_response_round_trips(self) -> None:
        raw = "0x" + encode(
            ["int128", "uint8", "string", "string", "bool"],
            [100, 0, "observer_outcome", self.observer, False],
        ).hex()
        self.assertEqual(
            decode_feedback(raw),
            (100, 0, "observer_outcome", self.observer, False),
        )

    def test_evidence_hash_is_stable(self) -> None:
        first = evidence_hash({"job_id": "1", "confirmed": True})
        second = evidence_hash({"confirmed": True, "job_id": "1"})
        self.assertEqual(first, second)
        self.assertEqual(len(first), 32)


if __name__ == "__main__":
    unittest.main()
