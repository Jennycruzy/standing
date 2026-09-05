"""Read back the Phase 0 EAS schema and attestation from Base."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from eth_abi import decode, encode
from eth_utils import keccak


ROOT = Path(__file__).resolve().parents[1]
RPC_URL = json.loads((ROOT / "config" / "chain.json").read_text())["base"]["rpcUrl"]
SCHEMA_REGISTRY = json.loads((ROOT / "config" / "chain.json").read_text())["base"]["schemaRegistry"]
EAS = json.loads((ROOT / "config" / "chain.json").read_text())["base"]["eas"]
SCHEMA_UID = "0x5c48ce51fcaa872494adb9d7db5f18b0c9d49a85a17f66987f2a5ef2fa5c45f9"
ATTESTATION_UID = "0xd8f641a3c82af731e6021aa71fc572ecf4ad5ca4c223d66e984863b5d6acb637"


def rpc(method: str, params: list[object]) -> Any:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    completed = subprocess.run(
        ["curl", "-sS", "--max-time", "30", RPC_URL, "-H", "content-type: application/json", "--data", payload],
        check=True,
        capture_output=True,
        text=True,
    )
    body = json.loads(completed.stdout)
    if "error" in body:
        raise RuntimeError(body["error"])
    return body["result"]


def call(address: str, selector: str, args: list[bytes]) -> bytes:
    data = "0x" + selector + b"".join(args).hex()
    return bytes.fromhex(rpc("eth_call", [{"to": address, "data": data}, "latest"])[2:])


def main() -> None:
    uid = bytes.fromhex(SCHEMA_UID[2:])
    schema_selector = keccak(text="getSchema(bytes32)")[:4].hex()
    attestation_selector = keccak(text="getAttestation(bytes32)")[:4].hex()
    schema_raw = call(SCHEMA_REGISTRY, schema_selector, [uid])
    attestation_raw = call(EAS, attestation_selector, [bytes.fromhex(ATTESTATION_UID[2:])])
    schema = decode(["(bytes32,address,bool,string)"], schema_raw)[0]
    attestation = decode(["(bytes32,bytes32,uint64,uint64,uint64,bytes32,address,address,bool,bytes)"], attestation_raw)[0]
    data_decoded: str | None
    try:
        data_decoded = str(decode(["string"], attestation[9])[0])
    except Exception:
        data_decoded = None
    print(json.dumps({
        "schema": {
            "uid": "0x" + schema[0].hex(),
            "resolver": schema[1],
            "revocable": schema[2],
            "definition": schema[3],
        },
        "attestation": {
            "uid": "0x" + attestation[0].hex(),
            "schema": "0x" + attestation[1].hex(),
            "time": attestation[2],
            "expirationTime": attestation[3],
            "revocationTime": attestation[4],
            "refUID": "0x" + attestation[5].hex(),
            "recipient": attestation[6],
            "attester": attestation[7],
            "revocable": attestation[8],
            "dataHex": "0x" + attestation[9].hex(),
            "dataDecoded": data_decoded,
        },
    }, indent=2))


if __name__ == "__main__":
    main()
