import json
import unittest
from pathlib import Path

from eth_abi import encode  # type: ignore[attr-defined]

from standing.eas_registry import (
    ZERO_ADDRESS,
    decode_registered_schema,
    get_schema_calldata,
    is_unregistered_schema,
    register_calldata,
    schema_definitions,
    schema_matches,
    schema_uid,
)


class EasSchemaRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        config_path = Path(__file__).parents[1] / "config" / "eas.json"
        self.config = json.loads(config_path.read_text(encoding="utf-8"))
        self.definitions = schema_definitions(self.config)

    def test_product_definitions_have_stable_uids_and_registration_calldata(self) -> None:
        self.assertEqual(
            [item.name for item in self.definitions],
            ["condition_definition", "observation"],
        )
        for definition in self.definitions:
            self.assertEqual(len(definition.uid), 66)
            self.assertGreater(len(register_calldata(definition)), 4 + 32 * 3)

    def test_uid_matches_the_recorded_preflight_schema_formula(self) -> None:
        self.assertEqual(
            schema_uid("string preflightValue", ZERO_ADDRESS, True),
            "0x5c48ce51fcaa872494adb9d7db5f18b0c9d49a85a17f66987f2a5ef2fa5c45f9",
        )

    def test_direct_registry_response_round_trips(self) -> None:
        definition = self.definitions[1]
        raw = "0x" + encode(
            ["(bytes32,address,bool,string)"],
            [(bytes.fromhex(definition.uid[2:]), definition.resolver, definition.revocable, definition.definition)],
        ).hex()
        registered = decode_registered_schema(raw, definition.uid)

        self.assertTrue(schema_matches(registered, definition))
        self.assertFalse(is_unregistered_schema(raw))
        self.assertEqual(get_schema_calldata(definition.uid)[4:], bytes.fromhex(definition.uid[2:]))

    def test_empty_registry_response_is_detected_without_being_accepted(self) -> None:
        raw = "0x" + encode(
            ["(bytes32,address,bool,string)"],
            [(bytes(32), ZERO_ADDRESS, False, "")],
        ).hex()
        self.assertTrue(is_unregistered_schema(raw))


if __name__ == "__main__":
    unittest.main()
