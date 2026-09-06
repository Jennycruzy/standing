"""Read back the Phase 0 EAS schema and attestation from Base."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from eth_abi import decode, encode
from eth_utils import keccak


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "chain.json").read_text())
BASE_CONFIG = CONFIG["base"]
PREFLIGHT = BASE_CONFIG["phase0Preflight"]
RPC_URL = BASE_CONFIG["rpcUrl"]
SCHEMA_REGISTRY = BASE_CONFIG["schemaRegistry"]
EAS = BASE_CONFIG["eas"]
SCHEMA_UID = PREFLIGHT["schemaUid"]
ATTESTATION_UID = PREFLIGHT["attestationUid"]
REFERENCE_UID = PREFLIGHT["referenceUid"]


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


def read_attestation(uid: str) -> dict[str, Any]:
    raw = call(EAS, keccak(text="getAttestation(bytes32)")[:4].hex(), [bytes.fromhex(uid[2:])])
    attestation = decode(
        ["(bytes32,bytes32,uint64,uint64,uint64,bytes32,address,address,bool,bytes)"], raw
    )[0]
    data_decoded: str | None
    try:
        data_decoded = str(decode(["string"], attestation[9])[0])
    except Exception:
        data_decoded = None
    return {
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
    }


def main() -> None:
    uid = bytes.fromhex(SCHEMA_UID[2:])
    schema_selector = keccak(text="getSchema(bytes32)")[:4].hex()
    schema_raw = call(SCHEMA_REGISTRY, schema_selector, [uid])
    schema = decode(["(bytes32,address,bool,string)"], schema_raw)[0]
    reference = read_attestation(REFERENCE_UID)
    attestation = read_attestation(ATTESTATION_UID)
    if reference["schema"] != SCHEMA_UID or attestation["schema"] != SCHEMA_UID:
        raise RuntimeError("EAS attestation schema readback mismatch")
    if attestation["refUID"].lower() != REFERENCE_UID.lower():
        raise RuntimeError("EAS reference UID readback mismatch")
    print(json.dumps({
        "schema": {
            "uid": "0x" + schema[0].hex(),
            "resolver": schema[1],
            "revocable": schema[2],
            "definition": schema[3],
        },
        "referenceAttestation": reference,
        "attestation": attestation,
        "referenceMatches": True,
    }, indent=2))


if __name__ == "__main__":
    main()
