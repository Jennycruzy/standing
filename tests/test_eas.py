import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Sequence

from standing.eas import EasReadError, EasReader, decode_string_payload, load_eas_config


class FixtureTransport:
    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, Sequence[Any]]] = []

    def request(self, method: str, params: Sequence[Any]) -> Any:
        self.calls.append((method, params))
        return self.responses[method]


class EasReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture_path = Path(__file__).parent / "fixtures" / "eas_reference_read.json"
        self.fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.config = load_eas_config(Path(__file__).parents[1] / "config" / "chain.json")

    def test_decodes_recorded_direct_eas_response_and_caches_by_block(self) -> None:
        transport = FixtureTransport(self.fixture["responses"])
        with tempfile.TemporaryDirectory() as directory:
            reader = EasReader(self.config, Path(directory) / "eas-cache.json", transport)
            first = reader.read_attestation(
                "0xbf2d3af512affd64dda8aea4ad8cabfe80755362e7838d9ba95764f1ccb375f9"
            )
            second = reader.read_attestation(
                "0xbf2d3af512affd64dda8aea4ad8cabfe80755362e7838d9ba95764f1ccb375f9"
            )

        self.assertEqual(first.uid, "0xbf2d3af512affd64dda8aea4ad8cabfe80755362e7838d9ba95764f1ccb375f9")
        self.assertEqual(first.schema_uid, "0x5c48ce51fcaa872494adb9d7db5f18b0c9d49a85a17f66987f2a5ef2fa5c45f9")
        self.assertEqual(first.ref_uid, "0x" + "00" * 32)
        self.assertEqual(first.block_number, int(self.fixture["capturedBlock"], 16))
        self.assertEqual(first.as_dict(), second.as_dict())
        self.assertEqual([call[0] for call in transport.calls], ["eth_blockNumber", "eth_call", "eth_blockNumber"])
        self.assertEqual(decode_string_payload(first.data_hex), "preflight-only")

    def test_config_comes_from_the_existing_chain_file(self) -> None:
        self.assertEqual(self.config.chain_id, 8453)
        self.assertEqual(self.config.rpc_url, "https://mainnet.base.org")
        self.assertEqual(self.config.eas_address, "0x4200000000000000000000000000000000000021")

    def test_preflight_record_is_not_accepted_as_a_product_observation(self) -> None:
        transport = FixtureTransport(self.fixture["responses"])
        with tempfile.TemporaryDirectory() as directory:
            record = EasReader(self.config, Path(directory) / "eas-cache.json", transport).read_attestation(
                "0xbf2d3af512affd64dda8aea4ad8cabfe80755362e7838d9ba95764f1ccb375f9"
            )

        with self.assertRaises(EasReadError):
            record.decode_observation(
                expected_schema_uid=record.schema_uid,
                condition_definition={
                    "condition_key": "vendor.acme.retention_days",
                    "value_type": "number",
                },
                source_type_labels={"0": "vendor_primary"},
            )


if __name__ == "__main__":
    unittest.main()
