"""Pure EAS SchemaRegistry calldata and readback helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from eth_abi import decode, encode  # type: ignore[attr-defined]
from eth_utils import keccak  # type: ignore[attr-defined]


class EasSchemaError(ValueError):
    """Raised when a schema definition or registry response is invalid."""


ZERO_ADDRESS = "0x" + "00" * 20


@dataclass(frozen=True)
class SchemaDefinition:
    """One immutable schema registration decision."""

    name: str
    definition: str
    resolver: str
    revocable: bool

    @property
    def uid(self) -> str:
        return schema_uid(self.definition, self.resolver, self.revocable)


@dataclass(frozen=True)
class RegisteredSchema:
    """The direct SchemaRegistry.getSchema response."""

    uid: str
    resolver: str
    revocable: bool
    definition: str


def schema_uid(definition: str, resolver: str, revocable: bool) -> str:
    """Calculate the UID used by SchemaRegistry for a definition."""

    schema = _required_string(definition, "schema definition")
    address = _address(resolver, "schema resolver")
    packed = schema.encode("utf-8") + bytes.fromhex(address[2:]) + (b"\x01" if revocable else b"\x00")
    return "0x" + keccak(packed).hex()


def register_calldata(definition: SchemaDefinition) -> bytes:
    """Build SchemaRegistry.register calldata from the configured definition."""

    selector = keccak(text="register(string,address,bool)")[:4]
    return selector + encode(
        ["string", "address", "bool"],
        [definition.definition, _address(definition.resolver, "schema resolver"), definition.revocable],
    )


def get_schema_calldata(uid: str) -> bytes:
    """Build SchemaRegistry.getSchema calldata."""

    selector = keccak(text="getSchema(bytes32)")[:4]
    return selector + bytes.fromhex(_uid(uid, "schema UID")[2:])


def decode_registered_schema(raw_result: str, uid: str) -> RegisteredSchema:
    """Decode and validate a direct SchemaRegistry.getSchema result."""

    try:
        decoded = decode(["(bytes32,address,bool,string)"], _hex_bytes(raw_result))[0]
    except Exception as error:
        raise EasSchemaError("SchemaRegistry response could not be decoded") from error
    result_uid = "0x" + decoded[0].hex()
    expected_uid = _uid(uid, "schema UID")
    if result_uid.lower() != expected_uid.lower():
        raise EasSchemaError("SchemaRegistry returned a different UID")
    return RegisteredSchema(
        uid=result_uid,
        resolver=str(decoded[1]),
        revocable=bool(decoded[2]),
        definition=str(decoded[3]),
    )


def is_unregistered_schema(raw_result: str) -> bool:
    """Return whether SchemaRegistry returned its empty default record."""

    try:
        decoded = decode(["(bytes32,address,bool,string)"], _hex_bytes(raw_result))[0]
    except Exception as error:
        raise EasSchemaError("SchemaRegistry response could not be decoded") from error
    return decoded[0] == b"\x00" * 32 and str(decoded[3]) == ""


def schema_matches(registered: RegisteredSchema, expected: SchemaDefinition) -> bool:
    """Check every field that makes a schema registration usable."""

    return (
        registered.uid.lower() == expected.uid.lower()
        and registered.resolver.lower() == expected.resolver.lower()
        and registered.revocable == expected.revocable
        and registered.definition == expected.definition
    )


def schema_definitions(raw: Mapping[str, Any]) -> tuple[SchemaDefinition, ...]:
    """Load named schema definitions from the JSON configuration object."""

    section = raw.get("schemas")
    if not isinstance(section, dict):
        raise EasSchemaError("EAS configuration must contain a schemas object")
    definitions: list[SchemaDefinition] = []
    for name in sorted(section):
        item = section[name]
        if not isinstance(item, dict):
            raise EasSchemaError(f"schema {name} must be an object")
        resolver = item.get("resolver", ZERO_ADDRESS)
        revocable = item.get("revocable")
        if not isinstance(revocable, bool):
            raise EasSchemaError(f"schema {name} revocable must be true or false")
        definitions.append(
            SchemaDefinition(
                name=_required_string(name, "schema name"),
                definition=_required_string(item.get("definition"), f"schema {name} definition"),
                resolver=_address(resolver, f"schema {name} resolver"),
                revocable=revocable,
            )
        )
    if not definitions:
        raise EasSchemaError("EAS configuration must define at least one schema")
    return tuple(definitions)


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EasSchemaError(f"{label} must be a non-empty string")
    return value.strip()


def _address(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("0x") or len(value) != 42:
        raise EasSchemaError(f"{label} must be a 20-byte EVM address")
    try:
        bytes.fromhex(value[2:])
    except ValueError as error:
        raise EasSchemaError(f"{label} must be a 20-byte EVM address") from error
    return value


def _uid(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("0x") or len(value) != 66:
        raise EasSchemaError(f"{label} must be a 32-byte hex value")
    try:
        bytes.fromhex(value[2:])
    except ValueError as error:
        raise EasSchemaError(f"{label} must be a 32-byte hex value") from error
    return value


def _hex_bytes(value: Any) -> bytes:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise EasSchemaError("SchemaRegistry response must be 0x-prefixed hex")
    try:
        return bytes.fromhex(value[2:])
    except ValueError as error:
        raise EasSchemaError("SchemaRegistry response must be valid hex") from error
