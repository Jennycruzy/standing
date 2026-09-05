"""Register a throwaway EAS schema and attestation on Base for Phase 0.

This script uses the verified deployment addresses from config/chain.json,
loads the dedicated signer from the local environment file, and sends only
the two explicitly requested preflight transactions. It never prints a key,
raw signed transaction, or environment value.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from eth_abi import encode
from eth_account import Account
from eth_utils import keccak, to_checksum_address


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "chain.json"
ENV_PATH = ROOT / ".env"


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def rpc(url: str, method: str, params: list[object]) -> Any:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    completed = subprocess.run(
        [
            "curl",
            "-sS",
            "--max-time",
            "30",
            url,
            "-H",
            "content-type: application/json",
            "--data",
            payload,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    body = json.loads(completed.stdout)
    if "error" in body:
        raise RuntimeError(f"RPC {method} failed: {body['error']}")
    return body["result"]


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))["base"]


def hex_int(value: str) -> int:
    return int(value, 16)


def receipt(rpc_url: str, tx_hash: str) -> dict[str, Any]:
    for _ in range(60):
        value = rpc(rpc_url, "eth_getTransactionReceipt", [tx_hash])
        if value is not None:
            if value.get("status") != "0x1":
                raise RuntimeError(f"transaction reverted: {tx_hash}")
            return value
        time.sleep(2)
    raise TimeoutError(f"transaction receipt timeout: {tx_hash}")


def send_transaction(
    rpc_url: str,
    private_key: str,
    sender: str,
    to: str,
    data: bytes,
) -> tuple[str, dict[str, Any]]:
    nonce = hex_int(rpc(rpc_url, "eth_getTransactionCount", [sender, "pending"]))
    block = rpc(rpc_url, "eth_getBlockByNumber", ["latest", False])
    base_fee = hex_int(block["baseFeePerGas"])
    priority = hex_int(rpc(rpc_url, "eth_maxPriorityFeePerGas", []))
    max_fee = base_fee * 2 + priority
    estimate = hex_int(
        rpc(
            rpc_url,
            "eth_estimateGas",
            [{"from": sender, "to": to, "data": "0x" + data.hex(), "value": "0x0"}],
        )
    )
    transaction = {
        "chainId": 8453,
        "nonce": nonce,
        "maxPriorityFeePerGas": priority,
        "maxFeePerGas": max_fee,
        "gas": estimate * 12 // 10 + 5_000,
        "to": to_checksum_address(to),
        "value": 0,
        "data": data,
        "type": 2,
    }
    signed = Account.sign_transaction(transaction, private_key)
    tx_hash = rpc(rpc_url, "eth_sendRawTransaction", ["0x" + signed.raw_transaction.hex()])
    return tx_hash, receipt(rpc_url, tx_hash)


def transaction_cost(receipt_data: dict[str, Any]) -> int:
    execution_fee = hex_int(receipt_data["gasUsed"]) * hex_int(receipt_data["effectiveGasPrice"])
    # Base receipts expose the L1 data fee separately; include it in the total.
    return execution_fee + hex_int(receipt_data.get("l1Fee", "0x0"))


def usd_price() -> tuple[float, str]:
    completed = subprocess.run(
        [
            "curl",
            "-fsS",
            "--max-time",
            "30",
            "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    body = json.loads(completed.stdout)
    source = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd"
    return float(body["ethereum"]["usd"]), source


def first_topic(receipt_data: dict[str, Any], event_signature: str, contract: str) -> str:
    topic = "0x" + keccak(text=event_signature).hex()
    for item in receipt_data["logs"]:
        if item["address"].lower() == contract.lower() and item["topics"][0].lower() == topic.lower():
            return item["topics"][1]
    raise RuntimeError(f"event {event_signature} not found in receipt")


def attestation_uid(receipt_data: dict[str, Any], contract: str) -> str:
    topic = "0x" + keccak(text="Attested(address,address,bytes32,bytes32)").hex()
    for item in receipt_data["logs"]:
        if item["address"].lower() == contract.lower() and item["topics"][0].lower() == topic.lower():
            # EAS leaves uid unindexed; it is the first word in the event data.
            return "0x" + item["data"][2:66]
    raise RuntimeError("Attested event not found in receipt")


def main() -> None:
    config = load_config()
    env = load_env(ENV_PATH)
    private_key = env.get("BASE_SIGNER_PRIVATE_KEY", "")
    if not private_key:
        raise RuntimeError("BASE_SIGNER_PRIVATE_KEY is missing")

    rpc_url = str(config["rpcUrl"])
    schema_registry = str(config["schemaRegistry"])
    eas = str(config["eas"])
    account = Account.from_key(private_key)
    sender = account.address

    schema = "string preflightValue"
    schema_tx: str | None = None
    schema_receipt: dict[str, Any] | None = None
    schema_uid: str
    if len(sys.argv) == 3 and sys.argv[1] == "--attest-only":
        schema_uid = sys.argv[2]
    else:
        register_data = keccak(text="register(string,address,bool)")[:4] + encode(
            ["string", "address", "bool"],
            [schema, "0x0000000000000000000000000000000000000000", True],
        )
        schema_tx, schema_receipt = send_transaction(rpc_url, private_key, sender, schema_registry, register_data)
        # SchemaRegistry calculates UID with abi.encodePacked(schema, resolver, revocable).
        schema_uid = "0x" + keccak(schema.encode() + bytes(20) + b"\x01").hex()

    attestation_data = encode(["string"], ["preflight-only"])
    schema_uid_bytes = bytes.fromhex(schema_uid.removeprefix("0x"))
    request_data = encode(
        ["(bytes32,(address,uint64,bool,bytes32,bytes,uint256))"],
        [(
            schema_uid_bytes,
            (
                "0x0000000000000000000000000000000000000000",
                0,
                True,
                bytes(32),
                attestation_data,
                0,
            ),
        )],
    )
    attest_data = keccak(text="attest((bytes32,(address,uint64,bool,bytes32,bytes,uint256)))")[:4] + request_data
    attestation_tx, attestation_receipt = send_transaction(rpc_url, private_key, sender, eas, attest_data)
    attestation_uid_value = attestation_uid(attestation_receipt, eas)

    price, price_source = usd_price()
    schema_cost = transaction_cost(schema_receipt) if schema_receipt is not None else 0
    attestation_cost = transaction_cost(attestation_receipt)
    print(json.dumps({
        "chainId": 8453,
        "signer": sender,
        "schema": {
            "definition": schema,
            "uid": schema_uid,
            "transactionHash": schema_tx,
            "transactionUrl": (str(config["explorers"]["transaction"]) + schema_tx) if schema_tx else None,
            "gasWei": str(schema_cost),
            "gasEth": schema_cost / 10**18,
            "gasUsd": schema_cost / 10**18 * price,
        },
        "attestation": {
            "uid": attestation_uid_value,
            "transactionHash": attestation_tx,
            "transactionUrl": str(config["explorers"]["transaction"]) + attestation_tx,
            "gasWei": str(attestation_cost),
            "gasEth": attestation_cost / 10**18,
            "gasUsd": attestation_cost / 10**18 * price,
            "refUID": "0x" + "00" * 32,
        },
        "ethUsd": price,
        "ethUsdSource": price_source,
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        raise
