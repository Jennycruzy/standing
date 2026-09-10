"""Read and decode EAS attestations on the configured Base network."""

from __future__ import annotations

import json
import ssl
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from time import time
from typing import Any, Mapping, Protocol, Sequence
from urllib.error import URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

import certifi
from eth_abi import decode  # type: ignore[attr-defined]
from eth_utils import keccak  # type: ignore[attr-defined]


class EasReadError(RuntimeError):
    """Raised when a chain read cannot be trusted or decoded."""


class RpcTransport(Protocol):
    """The small JSON-RPC surface needed by the EAS reader."""

    def request(self, method: str, params: Sequence[Any]) -> Any:
        """Return the JSON-RPC result or raise on an RPC error."""


@dataclass(frozen=True)
class EasConfig:
    """Runtime EAS connection settings loaded from configuration."""

    chain_id: int
    rpc_url: str
    eas_address: str
    rpc_timeout_seconds: float


def load_eas_config(path: str | Path) -> EasConfig:
    """Load the EAS address and RPC endpoint from chain configuration."""

    config_path = Path(path).expanduser()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict) or not isinstance(raw.get("base"), dict):
        raise EasReadError("chain configuration must contain a base object")
    base = raw["base"]
    chain_id = _positive_int(base.get("chainId"), "base.chainId")
    rpc_url = _required_string(base.get("rpcUrl"), "base.rpcUrl")
    eas_address = _required_string(base.get("eas"), "base.eas")
    timeout = base.get("rpcTimeoutSeconds")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise EasReadError("base.rpcTimeoutSeconds must be a positive number")
    return EasConfig(chain_id, rpc_url, eas_address, float(timeout))


class JsonRpcTransport:
    """Read-only JSON-RPC transport for a configured endpoint."""

    def __init__(self, endpoint: str, timeout_seconds: float) -> None:
        self.endpoint = _required_string(endpoint, "RPC endpoint")
        self.timeout_seconds = timeout_seconds

    def request(self, method: str, params: Sequence[Any]) -> Any:
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": method, "params": list(params)},
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            self.endpoint,
            data=payload,
            headers={
                "content-type": "application/json",
                "user-agent": "standing/0.1 (+https://github.com/Jennycruzy/standing)",
            },
            method="POST",
        )
        try:
            with urlopen(
                request,
                timeout=self.timeout_seconds,
                context=ssl.create_default_context(cafile=certifi.where()),
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, json.JSONDecodeError) as error:
            raise EasReadError("Base JSON-RPC request failed") from error
        if not isinstance(body, dict):
            raise EasReadError("Base JSON-RPC response was not an object")
        if "error" in body:
            raise EasReadError(f"Base JSON-RPC returned an error for {method}")
        if "result" not in body:
            raise EasReadError(f"Base JSON-RPC response omitted a result for {method}")
        return body["result"]


@dataclass(frozen=True)
class EasAttestation:
    """The direct EAS.getAttestation record plus its read block."""

    uid: str
    schema_uid: str
    time: int
    expiration_time: int
    revocation_time: int
    ref_uid: str
    recipient: str
    attester: str
    revocable: bool
    data_hex: str
    block_number: int

    @property
    def is_revoked(self) -> bool:
        return self.revocation_time != 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "schema_uid": self.schema_uid,
            "time": self.time,
            "expiration_time": self.expiration_time,
            "revocation_time": self.revocation_time,
            "ref_uid": self.ref_uid,
            "recipient": self.recipient,
            "attester": self.attester,
            "revocable": self.revocable,
            "data_hex": self.data_hex,
            "block_number": self.block_number,
        }

    def decode_observation(
        self,
        *,
        expected_schema_uid: str,
        condition_definition: Mapping[str, Any],
        source_type_labels: Mapping[str, str],
        as_of_timestamp: int | None = None,
    ) -> dict[str, Any]:
        """Turn a product observation attestation into an acceptance record."""

        expected = _required_string(expected_schema_uid, "expected_schema_uid")
        if self.schema_uid.lower() != expected.lower():
            raise EasReadError("attestation schema does not match the configured observation schema")
        if self.is_revoked:
            raise EasReadError("revoked attestations cannot become observations")
        if as_of_timestamp is not None and self.expiration_time != 0 and as_of_timestamp > self.expiration_time:
            raise EasReadError("expired attestation cannot become a current observation")

        definition_key = _required_string(condition_definition.get("condition_key"), "condition_key")
        value_type = _required_string(condition_definition.get("value_type"), "value_type")
        try:
            decoded = decode(
                ["string", "string", "uint64", "string", "uint8", "string"],
                _hex_bytes(self.data_hex, "attestation data"),
            )
        except Exception as error:
            raise EasReadError("observation attestation data could not be decoded") from error

        condition_key = _required_string(decoded[0], "observation condition key")
        if condition_key != definition_key:
            raise EasReadError("observation condition key does not match the condition definition")
        raw_value = _required_string(decoded[1], "observation value")
        source_code = str(decoded[4])
        source_type = source_type_labels.get(source_code)
        if source_type is None:
            raise EasReadError(f"source type {source_code} is not configured")
        source_url = _required_string(decoded[3], "observation source URL")
        if not source_url.startswith(("https://", "http://")):
            raise EasReadError("observation source URL must be HTTP or HTTPS")
        unit = _required_string(condition_definition.get("unit"), "condition unit")
        extracted_at = int(time()) if as_of_timestamp is None else as_of_timestamp
        source_domain = urlparse(source_url).hostname
        if source_domain is None:
            raise EasReadError("observation source URL has no domain")
        return {
            "condition_key": condition_key,
            "value": _parse_value(raw_value, value_type),
            "source_type": source_type,
            "observer_address": self.attester,
            "observation_uid": self.uid,
            "source_url": source_url,
            "source_domain": source_domain.lower().rstrip("."),
            "value_type": value_type,
            "unit": unit,
            "attester": self.attester,
            "effective_from": int(decoded[2]),
            "observed_at": self.time,
            "recorded_at": extracted_at,
            "note": _required_string(decoded[5], "observation note"),
            "ref_uid": self.ref_uid,
            "block_number": self.block_number,
        }


class EasReader:
    """Read EAS records and cache each result with its block number."""

    def __init__(
        self,
        config: EasConfig,
        cache_path: str | Path,
        transport: RpcTransport | None = None,
    ) -> None:
        self.config = config
        self.cache_path = Path(cache_path).expanduser()
        self.transport = transport or JsonRpcTransport(config.rpc_url, config.rpc_timeout_seconds)

    def read_attestation(self, uid: str) -> EasAttestation:
        """Read one direct EAS record at a recorded latest block."""

        normalized_uid = _uid(uid, "attestation UID")
        block_number = _quantity(self.transport.request("eth_blockNumber", []), "block number")
        cache = self._read_cache()
        cache_key = f"{normalized_uid.lower()}@{block_number}"
        cached = cache.get(cache_key)
        if isinstance(cached, dict) and isinstance(cached.get("result"), str):
            raw_result = cached["result"]
        else:
            selector = keccak(text="getAttestation(bytes32)")[:4].hex()
            raw_result = self.transport.request(
                "eth_call",
                [
                    {
                        "to": self.config.eas_address,
                        "data": "0x" + selector + normalized_uid[2:],
                    },
                    _quantity_hex(block_number),
                ],
            )
            if not isinstance(raw_result, str):
                raise EasReadError("EAS eth_call returned a non-hex result")
            cache[cache_key] = {
                "block_number": block_number,
                "captured_at": int(time()),
                "method": "eth_call",
                "result": raw_result,
            }
            self._write_cache(cache)
        return _decode_attestation(raw_result, block_number)

    def _read_cache(self) -> dict[str, Any]:
        if not self.cache_path.is_file():
            return {}
        try:
            with self.cache_path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, json.JSONDecodeError) as error:
            raise EasReadError("EAS cache could not be read") from error
        if not isinstance(raw, dict):
            raise EasReadError("EAS cache must contain an object")
        return raw

    def _write_cache(self, cache: Mapping[str, Any]) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(dict(cache), handle, sort_keys=True, separators=(",", ":"))
            temporary.replace(self.cache_path)
        except OSError as error:
            raise EasReadError("EAS cache could not be written") from error


def _decode_attestation(raw_result: Any, block_number: int) -> EasAttestation:
    if not isinstance(raw_result, str):
        raise EasReadError("EAS attestation result was not a hex string")
    try:
        decoded = decode(
            ["(bytes32,bytes32,uint64,uint64,uint64,bytes32,address,address,bool,bytes)"],
            _hex_bytes(raw_result, "EAS attestation result"),
        )[0]
    except Exception as error:
        raise EasReadError("EAS attestation result could not be decoded") from error
    uid = "0x" + decoded[0].hex()
    if uid == "0x" + "00" * 32:
        raise EasReadError("EAS returned an empty attestation record")
    return EasAttestation(
        uid=uid,
        schema_uid="0x" + decoded[1].hex(),
        time=int(decoded[2]),
        expiration_time=int(decoded[3]),
        revocation_time=int(decoded[4]),
        ref_uid="0x" + decoded[5].hex(),
        recipient=str(decoded[6]),
        attester=str(decoded[7]),
        revocable=bool(decoded[8]),
        data_hex="0x" + decoded[9].hex(),
        block_number=block_number,
    )


def decode_string_payload(data_hex: str) -> str:
    """Decode a single-string EAS payload for recorded preflight records."""

    try:
        return str(decode(["string"], _hex_bytes(data_hex, "string payload"))[0])
    except Exception as error:
        raise EasReadError("EAS string payload could not be decoded") from error


def _parse_value(raw_value: str, value_type: str) -> Any:
    if value_type == "number":
        try:
            return int(raw_value)
        except ValueError:
            try:
                return float(raw_value)
            except ValueError as error:
                raise EasReadError("numeric observation value is invalid") from error
    if value_type == "boolean":
        if raw_value == "true":
            return True
        if raw_value == "false":
            return False
        raise EasReadError("boolean observation value must be true or false")
    if value_type == "date":
        try:
            date.fromisoformat(raw_value)
        except ValueError as error:
            raise EasReadError("date observation value is invalid") from error
        return raw_value
    if value_type == "set":
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError as error:
            raise EasReadError("set observation value is not JSON") from error
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise EasReadError("set observation value must be a list of strings")
        return parsed
    raise EasReadError(f"unsupported condition value type: {value_type}")


def _uid(value: str, label: str) -> str:
    if not isinstance(value, str) or len(value) != 66 or not value.startswith("0x"):
        raise EasReadError(f"{label} must be a 32-byte 0x-prefixed hex value")
    try:
        bytes.fromhex(value[2:])
    except ValueError as error:
        raise EasReadError(f"{label} must be a 32-byte 0x-prefixed hex value") from error
    return value


def _hex_bytes(value: Any, label: str) -> bytes:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise EasReadError(f"{label} must be 0x-prefixed hex")
    try:
        return bytes.fromhex(value[2:])
    except ValueError as error:
        raise EasReadError(f"{label} must be valid hex") from error


def _quantity(value: Any, label: str) -> int:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise EasReadError(f"{label} must be a JSON-RPC quantity")
    try:
        return int(value, 16)
    except ValueError as error:
        raise EasReadError(f"{label} must be a JSON-RPC quantity") from error


def _quantity_hex(value: int) -> str:
    return hex(value)


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EasReadError(f"{label} must be a non-empty string")
    return value.strip()


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise EasReadError(f"{label} must be a positive integer")
    return value
