"""Pure ERC-8004 reputation calldata and response helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from eth_abi import decode, encode  # type: ignore[attr-defined]
from eth_utils import keccak  # type: ignore[attr-defined]


class ReputationError(ValueError):
    """Raised when a reputation configuration or response is unusable."""


@dataclass(frozen=True)
class ReputationConfig:
    """Configured ERC-8004 identity and feedback target."""

    identity_registry: str
    reputation_registry: str
    standing_agent_id: int
    client_key_env: str
    value_decimals: int
    confirmed_value: int
    contradicted_value: int
    tag1: str


def load_reputation_config(path: str | Path) -> ReputationConfig:
    config_path = Path(path).expanduser()
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReputationError("reputation configuration could not be read") from error
    if not isinstance(raw, dict):
        raise ReputationError("reputation configuration must contain an object")
    return ReputationConfig(
        identity_registry=_address(raw.get("identity_registry"), "identity_registry"),
        reputation_registry=_address(raw.get("reputation_registry"), "reputation_registry"),
        standing_agent_id=_positive_int(raw.get("standing_agent_id"), "standing_agent_id"),
        client_key_env=_required_string(raw.get("client_key_env"), "client_key_env"),
        value_decimals=_byte(raw.get("value_decimals"), "value_decimals"),
        confirmed_value=_int128(raw.get("confirmed_value"), "confirmed_value"),
        contradicted_value=_int128(raw.get("contradicted_value"), "contradicted_value"),
        tag1=_required_string(raw.get("tag1"), "tag1"),
    )


def feedback_calldata(
    config: ReputationConfig,
    *,
    value: int,
    observer_address: str,
    endpoint: str,
    feedback_uri: str,
    feedback_hash: bytes,
) -> bytes:
    """Build ReputationRegistry.giveFeedback calldata."""

    if len(feedback_hash) != 32:
        raise ReputationError("feedback_hash must be 32 bytes")
    observer = _address(observer_address, "observer_address")
    endpoint_value = _url(endpoint, "endpoint")
    uri_value = _url(feedback_uri, "feedback_uri")
    selector = keccak(
        text="giveFeedback(uint256,int128,uint8,string,string,string,string,bytes32)"
    )[:4]
    return selector + encode(
        ["uint256", "int128", "uint8", "string", "string", "string", "string", "bytes32"],
        [
            config.standing_agent_id,
            _int128(value, "feedback value"),
            config.value_decimals,
            config.tag1,
            observer,
            endpoint_value,
            uri_value,
            feedback_hash,
        ],
    )


def last_index_calldata(config: ReputationConfig, client_address: str) -> bytes:
    """Build ReputationRegistry.getLastIndex calldata."""

    selector = keccak(text="getLastIndex(uint256,address)")[:4]
    return selector + encode(
        ["uint256", "address"],
        [config.standing_agent_id, _address(client_address, "client_address")],
    )


def read_feedback_calldata(config: ReputationConfig, client_address: str, index: int) -> bytes:
    """Build ReputationRegistry.readFeedback calldata."""

    selector = keccak(text="readFeedback(uint256,address,uint64)")[:4]
    return selector + encode(
        ["uint256", "address", "uint64"],
        [config.standing_agent_id, _address(client_address, "client_address"), _nonnegative_int(index, "index")],
    )


def decode_feedback(raw_result: str) -> tuple[int, int, str, str, bool]:
    """Decode the direct five-field reputation record."""

    try:
        raw = _hex_bytes(raw_result, "reputation response")
        decoded = decode(["int128", "uint8", "string", "string", "bool"], raw)
    except Exception as error:
        raise ReputationError("reputation response could not be decoded") from error
    return int(decoded[0]), int(decoded[1]), str(decoded[2]), str(decoded[3]), bool(decoded[4])


def decode_last_index(raw_result: str) -> int:
    """Decode ReputationRegistry.getLastIndex."""

    try:
        decoded = decode(["uint64"], _hex_bytes(raw_result, "last feedback index response"))[0]
    except Exception as error:
        raise ReputationError("last feedback index could not be decoded") from error
    return int(decoded)


def evidence_hash(evidence: Mapping[str, Any]) -> bytes:
    """Hash the stable evidence fields placed behind a public feedback signal."""

    try:
        canonical = json.dumps(dict(evidence), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise ReputationError("reputation evidence could not be serialized") from error
    return keccak(canonical.encode("utf-8"))


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReputationError(f"{label} must be a non-empty string")
    return value.strip()


def _address(value: Any, label: str) -> str:
    result = _required_string(value, label)
    if len(result) != 42 or not result.startswith("0x"):
        raise ReputationError(f"{label} must be a 20-byte address")
    try:
        bytes.fromhex(result[2:])
    except ValueError as error:
        raise ReputationError(f"{label} must be a 20-byte address") from error
    return result


def _positive_int(value: Any, label: str) -> int:
    result = _nonnegative_int(value, label)
    if result == 0:
        raise ReputationError(f"{label} must be positive")
    return result


def _nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ReputationError(f"{label} must be a non-negative integer")
    return value


def _byte(value: Any, label: str) -> int:
    result = _nonnegative_int(value, label)
    if result > 255:
        raise ReputationError(f"{label} must fit in uint8")
    return result


def _int128(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < -(2**127) or value >= 2**127:
        raise ReputationError(f"{label} must fit in int128")
    return value


def _url(value: Any, label: str) -> str:
    result = _required_string(value, label)
    if not result.startswith(("https://", "http://")):
        raise ReputationError(f"{label} must be HTTP or HTTPS")
    return result


def _hex_bytes(value: Any, label: str) -> bytes:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise ReputationError(f"{label} must be 0x-prefixed hex")
    try:
        return bytes.fromhex(value[2:])
    except ValueError as error:
        raise ReputationError(f"{label} must be valid hex") from error
