"""Read or idempotently register Standing's product schemas on Base."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import sleep
from typing import Any, Mapping, cast

from eth_account import Account
from eth_utils import to_checksum_address  # type: ignore[attr-defined]


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from standing.eas import EasReadError, JsonRpcTransport
from standing.eas_registry import (
    RegisteredSchema,
    SchemaDefinition,
    decode_registered_schema,
    get_schema_calldata,
    is_unregistered_schema,
    register_calldata,
    schema_definitions,
    schema_matches,
)

CHAIN_CONFIG_PATH = ROOT / "config" / "chain.json"
EAS_CONFIG_PATH = ROOT / "config" / "eas.json"
ENV_PATH = ROOT / ".env"


def load_env(path: Path) -> dict[str, str]:
    """Read simple KEY=value entries without ever printing their values."""

    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RuntimeError("local environment file could not be read") from error
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        clean_value = value.strip()
        if len(clean_value) >= 2 and clean_value[0] == clean_value[-1] and clean_value[0] in "'\"":
            clean_value = clean_value[1:-1]
        values[key.strip()] = clean_value
    return values


def load_base_config(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("chain configuration could not be read") from error
    if not isinstance(raw, dict) or not isinstance(raw.get("base"), dict):
        raise RuntimeError("chain configuration must contain a base object")
    return cast(dict[str, Any], raw["base"])


def load_schema_config(path: Path) -> tuple[SchemaDefinition, ...]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("EAS configuration could not be read") from error
    if not isinstance(raw, dict):
        raise RuntimeError("EAS configuration must contain an object")
    return schema_definitions(raw)


def read_schema(
    transport: JsonRpcTransport,
    registry: str,
    expected: SchemaDefinition,
    block_tag: str = "latest",
) -> RegisteredSchema | None:
    """Read one schema and distinguish an empty record from a real mismatch."""

    result = transport.request(
        "eth_call",
        [
            {
                "to": registry,
                "data": "0x" + get_schema_calldata(expected.uid).hex(),
            },
            block_tag,
        ],
    )
    if not isinstance(result, str):
        raise RuntimeError(f"SchemaRegistry returned a non-hex result for {expected.name}")
    if is_unregistered_schema(result):
        return None
    registered = decode_registered_schema(result, expected.uid)
    if not schema_matches(registered, expected):
        raise RuntimeError(
            f"SchemaRegistry has a conflicting registration for {expected.name} ({expected.uid})"
        )
    return registered


def transaction_settings(base: Mapping[str, Any]) -> tuple[int, int, float, int]:
    raw = base.get("transaction")
    if not isinstance(raw, dict):
        raise RuntimeError("base.transaction configuration is required")
    multiplier = _positive_int(raw.get("maxFeeMultiplier"), "maxFeeMultiplier")
    gas_buffer = _nonnegative_int(raw.get("gasBufferPercent"), "gasBufferPercent")
    poll_seconds = raw.get("receiptPollSeconds")
    if not isinstance(poll_seconds, (int, float)) or isinstance(poll_seconds, bool) or poll_seconds <= 0:
        raise RuntimeError("receiptPollSeconds must be positive")
    attempts = _positive_int(raw.get("receiptPollAttempts"), "receiptPollAttempts")
    return multiplier, gas_buffer, float(poll_seconds), attempts


def send_registration(
    transport: JsonRpcTransport,
    base: Mapping[str, Any],
    private_key: str,
    data: bytes,
) -> tuple[str, dict[str, Any]]:
    sender = Account.from_key(private_key).address
    registry = _required_string(base.get("schemaRegistry"), "base.schemaRegistry")
    chain_id = _positive_int(base.get("chainId"), "base.chainId")
    multiplier, gas_buffer, poll_seconds, poll_attempts = transaction_settings(base)
    nonce = _quantity(transport.request("eth_getTransactionCount", [sender, "pending"]), "pending nonce")
    block = transport.request("eth_getBlockByNumber", ["latest", False])
    if not isinstance(block, dict):
        raise RuntimeError("latest Base block was not an object")
    base_fee = _quantity(block.get("baseFeePerGas"), "base fee")
    priority = _quantity(transport.request("eth_maxPriorityFeePerGas", []), "priority fee")
    estimate = _quantity(
        transport.request(
            "eth_estimateGas",
            [
                {
                    "from": sender,
                    "to": to_checksum_address(registry),
                    "data": "0x" + data.hex(),
                    "value": "0x0",
                }
            ],
        ),
        "gas estimate",
    )
    transaction: dict[str, Any] = {
        "chainId": chain_id,
        "nonce": nonce,
        "maxPriorityFeePerGas": priority,
        "maxFeePerGas": base_fee * multiplier + priority,
        "gas": estimate * (100 + gas_buffer) // 100,
        "to": to_checksum_address(registry),
        "value": 0,
        "data": data,
        "type": 2,
    }
    signed = Account.sign_transaction(transaction, private_key)
    tx_hash = transport.request(
        "eth_sendRawTransaction",
        ["0x" + signed.raw_transaction.hex()],
    )
    if not isinstance(tx_hash, str) or not tx_hash.startswith("0x"):
        raise RuntimeError("Base did not return a transaction hash")
    receipt_data = wait_for_receipt(transport, tx_hash, poll_seconds, poll_attempts)
    return tx_hash, receipt_data


def wait_for_receipt(
    transport: JsonRpcTransport,
    tx_hash: str,
    poll_seconds: float,
    attempts: int,
) -> dict[str, Any]:
    for attempt in range(attempts):
        result = transport.request("eth_getTransactionReceipt", [tx_hash])
        if result is not None:
            if not isinstance(result, dict):
                raise RuntimeError("Base returned an invalid transaction receipt")
            if result.get("status") != "0x1":
                raise RuntimeError(f"schema registration transaction reverted: {tx_hash}")
            return result
        if attempt + 1 < attempts:
            sleep(poll_seconds)
    raise TimeoutError(f"transaction receipt was not available: {tx_hash}")


def verify_after_registration(
    transport: JsonRpcTransport,
    base: Mapping[str, Any],
    registry: str,
    definition: SchemaDefinition,
    receipt_data: Mapping[str, Any],
) -> RegisteredSchema:
    """Verify at the mined block, then retry latest while an RPC catches up."""

    block_number = receipt_data.get("blockNumber")
    if not isinstance(block_number, str) or not block_number.startswith("0x"):
        raise RuntimeError(f"{definition.name} receipt omitted its block number")
    last_error: Exception | None = None
    try:
        registered = read_schema(transport, registry, definition, block_number)
    except EasReadError as error:
        registered = None
        last_error = error
    if registered is not None:
        return registered

    _, _, poll_seconds, attempts = transaction_settings(base)
    for attempt in range(attempts):
        try:
            registered = read_schema(transport, registry, definition)
        except EasReadError as error:
            registered = None
            last_error = error
        if registered is not None:
            return registered
        if attempt + 1 < attempts:
            sleep(poll_seconds)
    message = f"{definition.name} was not readable after registration"
    if last_error is not None:
        raise RuntimeError(message) from last_error
    raise RuntimeError(message)


def result_record(
    base: Mapping[str, Any],
    definition: SchemaDefinition,
    status: str,
    tx_hash: str | None = None,
    receipt_data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    explorers = base.get("explorers")
    transaction_base = ""
    if isinstance(explorers, dict) and isinstance(explorers.get("transaction"), str):
        transaction_base = explorers["transaction"]
    record: dict[str, Any] = {
        "name": definition.name,
        "definition": definition.definition,
        "uid": definition.uid,
        "status": status,
    }
    if tx_hash is not None:
        record["transactionHash"] = tx_hash
        record["transactionUrl"] = transaction_base + tx_hash
    if receipt_data is not None:
        record["blockNumber"] = receipt_data.get("blockNumber")
        record["gasUsed"] = receipt_data.get("gasUsed")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="send a transaction for each missing schema; default is read-only",
    )
    args = parser.parse_args()

    base = load_base_config(CHAIN_CONFIG_PATH)
    definitions = load_schema_config(EAS_CONFIG_PATH)
    rpc_url = _required_string(base.get("rpcUrl"), "base.rpcUrl")
    timeout = _positive_float(base.get("rpcTimeoutSeconds"), "base.rpcTimeoutSeconds")
    registry = _required_string(base.get("schemaRegistry"), "base.schemaRegistry")
    transport = JsonRpcTransport(rpc_url, timeout)

    records: list[dict[str, Any]] = []
    missing: list[SchemaDefinition] = []
    for definition in definitions:
        registered = read_schema(transport, registry, definition)
        if registered is None:
            missing.append(definition)
            records.append(result_record(base, definition, "missing"))
        else:
            records.append(result_record(base, definition, "already_registered"))

    if args.write and missing:
        env = load_env(ENV_PATH)
        private_key = env.get("BASE_SIGNER_PRIVATE_KEY", "")
        if not private_key:
            raise RuntimeError("BASE_SIGNER_PRIVATE_KEY is missing")
        for definition in missing:
            tx_hash, receipt_data = send_registration(
                transport,
                base,
                private_key,
                register_calldata(definition),
            )
            registered = verify_after_registration(
                transport,
                base,
                registry,
                definition,
                receipt_data,
            )
            if not schema_matches(registered, definition):
                raise RuntimeError(f"{definition.name} did not match after registration")
            for record in records:
                if record["name"] == definition.name:
                    record.clear()
                    record.update(result_record(base, definition, "registered", tx_hash, receipt_data))
                    break

    print(json.dumps({"write": args.write, "schemas": records}, indent=2, sort_keys=True))


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{label} must be a non-empty string")
    return value.strip()


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RuntimeError(f"{label} must be a positive integer")
    return value


def _nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(f"{label} must be a non-negative integer")
    return value


def _positive_float(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise RuntimeError(f"{label} must be positive")
    return float(value)


def _quantity(value: Any, label: str) -> int:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise RuntimeError(f"{label} was not a hex quantity")
    try:
        parsed = int(value, 16)
    except ValueError as error:
        raise RuntimeError(f"{label} was not a hex quantity") from error
    if parsed < 0:
        raise RuntimeError(f"{label} cannot be negative")
    return parsed


if __name__ == "__main__":
    try:
        main()
    except (EasReadError, RuntimeError, TimeoutError) as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        raise
