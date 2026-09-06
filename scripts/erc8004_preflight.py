"""Run the Standing ERC-8004 Base identity and reputation preflight."""

from __future__ import annotations

import base64
import argparse
import json
import sys
from pathlib import Path
from typing import Any

from eth_abi import decode, encode
from eth_account import Account
from eth_utils import keccak

try:
    from .phase0_eas import load_config, load_env, rpc, send_transaction, transaction_cost
except ImportError:  # Direct CLI execution from the scripts directory.
    from phase0_eas import load_config, load_env, rpc, send_transaction, transaction_cost


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
IDENTITY_REGISTRY = "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432"
REPUTATION_REGISTRY = "0x8004BAa17C55a88189AE136b182e5fdA19dE9b63"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ZERO_BYTES32 = bytes(32)


def selector(signature: str) -> bytes:
    return keccak(text=signature)[:4]


def call(config: dict[str, Any], address: str, signature: str, types: list[str], values: list[Any]) -> bytes:
    data = selector(signature) + encode(types, values)
    result = rpc(
        str(config["rpcUrl"]),
        "eth_call",
        [{"to": address, "data": "0x" + data.hex()}, "latest"],
    )
    return bytes.fromhex(result[2:])


def estimate(
    config: dict[str, Any], sender: str, address: str, signature: str, types: list[str], values: list[Any]
) -> int:
    data = selector(signature) + encode(types, values)
    return int(
        rpc(
            str(config["rpcUrl"]),
            "eth_estimateGas",
            [{"from": sender, "to": address, "data": "0x" + data.hex(), "value": "0x0"}],
        ),
        16,
    )


def send(
    config: dict[str, Any],
    private_key: str,
    address: str,
    signature: str,
    types: list[str],
    values: list[Any],
) -> tuple[str, dict[str, Any]]:
    data = selector(signature) + encode(types, values)
    sender = Account.from_key(private_key).address
    return send_transaction(str(config["rpcUrl"]), private_key, sender, address, data)


def decode_one(config: dict[str, Any], address: str, signature: str, output_type: str, types: list[str], values: list[Any]) -> Any:
    return decode([output_type], call(config, address, signature, types, values))[0]


def registration_uri() -> str:
    document = {
        "type": "https://eips.ethereum.org/EIPS/eip-8004#registration-v1",
        "name": "Standing",
        "description": "Standing verifies agent work with auditable memory, evidence, and trust signals.",
        "image": "",
        "services": [],
    }
    encoded = base64.b64encode(json.dumps(document, separators=(",", ":")).encode()).decode()
    return "data:application/json;base64," + encoded


def registered_agent_id(receipt: dict[str, Any]) -> int:
    event_topic = "0x" + keccak(text="Registered(uint256,string,address)").hex()
    for log in receipt["logs"]:
        if log["topics"][0].lower() == event_topic.lower() and len(log["topics"]) >= 2:
            return int(log["topics"][1], 16)
    raise RuntimeError("ERC-8004 Registered event not found")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent-id",
        type=int,
        help="Resume with an existing Standing identity instead of registering another one",
    )
    parser.add_argument("--rpc-url", help="Override the Base RPC endpoint for this run")
    args = parser.parse_args()

    config = load_config()
    if args.rpc_url:
        config["rpcUrl"] = args.rpc_url
    env = load_env(ENV_PATH)
    identity_key = env.get("BASE_SIGNER_PRIVATE_KEY", "")
    client_key = env.get("WHITELISTED_WALLET_PRIVATE_KEY", "")
    if not identity_key or not client_key:
        raise RuntimeError("BASE_SIGNER_PRIVATE_KEY and WHITELISTED_WALLET_PRIVATE_KEY are required")

    identity_owner = Account.from_key(identity_key).address
    client = Account.from_key(client_key).address
    if identity_owner.lower() == client.lower():
        raise RuntimeError("identity owner and reputation client must be different wallets")

    uri = registration_uri()
    identity_version = decode_one(config, IDENTITY_REGISTRY, "getVersion()", "string", [], [])
    reputation_version = decode_one(config, REPUTATION_REGISTRY, "getVersion()", "string", [], [])
    linked_identity = decode_one(config, REPUTATION_REGISTRY, "getIdentityRegistry()", "address", [], [])
    if linked_identity.lower() != IDENTITY_REGISTRY.lower():
        raise RuntimeError("Reputation Registry points at an unexpected Identity Registry")

    identity_tx: str | None = None
    identity_receipt: dict[str, Any] | None = None
    if args.agent_id is None:
        identity_gas = estimate(config, identity_owner, IDENTITY_REGISTRY, "register(string)", ["string"], [uri])
        identity_tx, identity_receipt = send(
            config,
            identity_key,
            IDENTITY_REGISTRY,
            "register(string)",
            ["string"],
            [uri],
        )
        agent_id = registered_agent_id(identity_receipt)
    else:
        identity_gas = 0
        agent_id = args.agent_id

    owner = decode_one(config, IDENTITY_REGISTRY, "ownerOf(uint256)", "address", ["uint256"], [agent_id])
    token_uri = decode_one(config, IDENTITY_REGISTRY, "tokenURI(uint256)", "string", ["uint256"], [agent_id])
    agent_wallet = decode_one(config, IDENTITY_REGISTRY, "getAgentWallet(uint256)", "address", ["uint256"], [agent_id])
    if owner.lower() != identity_owner.lower() or token_uri != uri or agent_wallet.lower() != identity_owner.lower():
        raise RuntimeError("registered ERC-8004 identity did not read back exactly")

    approved_operator = decode_one(
        config,
        IDENTITY_REGISTRY,
        "isApprovedForAll(address,address)",
        "bool",
        ["address", "address"],
        [identity_owner, client],
    )
    if approved_operator:
        raise RuntimeError("reputation client is an approved operator for the new identity")

    feedback_args = [
        agent_id,
        100,
        0,
        "standing",
        "phase0",
        "",
        "",
        ZERO_BYTES32,
    ]
    existing_index = decode_one(
        config,
        REPUTATION_REGISTRY,
        "getLastIndex(uint256,address)",
        "uint64",
        ["uint256", "address"],
        [agent_id, client],
    )
    feedback_tx: str | None = None
    feedback_receipt: dict[str, Any] | None = None
    if existing_index == 0:
        feedback_gas = estimate(
            config,
            client,
            REPUTATION_REGISTRY,
            "giveFeedback(uint256,int128,uint8,string,string,string,string,bytes32)",
            ["uint256", "int128", "uint8", "string", "string", "string", "string", "bytes32"],
            feedback_args,
        )
        feedback_tx, feedback_receipt = send(
            config,
            client_key,
            REPUTATION_REGISTRY,
            "giveFeedback(uint256,int128,uint8,string,string,string,string,bytes32)",
            ["uint256", "int128", "uint8", "string", "string", "string", "string", "bytes32"],
            feedback_args,
        )
        index = decode_one(
            config,
            REPUTATION_REGISTRY,
            "getLastIndex(uint256,address)",
            "uint64",
            ["uint256", "address"],
            [agent_id, client],
        )
    else:
        feedback_gas = 0
        index = existing_index
    feedback = decode(
        ["int128", "uint8", "string", "string", "bool"],
        call(
            config,
            REPUTATION_REGISTRY,
            "readFeedback(uint256,address,uint64)",
            ["uint256", "address", "uint64"],
            [agent_id, client, index],
        ),
    )
    summary = decode(
        ["uint64", "int128", "uint8"],
        call(
            config,
            REPUTATION_REGISTRY,
            "getSummary(uint256,address[],string,string)",
            ["uint256", "address[]", "string", "string"],
            [agent_id, [client], "standing", "phase0"],
        ),
    )
    if feedback != (100, 0, "standing", "phase0", False) or summary != (1, 100, 0):
        raise RuntimeError("ERC-8004 reputation did not read back exactly")

    print(json.dumps({
        "chainId": 8453,
        "identityRegistry": IDENTITY_REGISTRY,
        "reputationRegistry": REPUTATION_REGISTRY,
        "identityVersion": identity_version,
        "reputationVersion": reputation_version,
        "agentId": str(agent_id),
        "identityOwner": identity_owner,
        "agentWallet": agent_wallet,
        "identityGasEstimate": identity_gas,
        "identityTransaction": identity_tx,
        "identityGasWei": str(transaction_cost(identity_receipt)) if identity_receipt else "0",
        "reputationClient": client,
        "feedbackGasEstimate": feedback_gas,
        "feedbackTransaction": feedback_tx,
        "feedbackGasWei": str(transaction_cost(feedback_receipt)) if feedback_receipt else "0",
        "feedbackIndex": str(index),
        "feedback": {
            "value": feedback[0],
            "valueDecimals": feedback[1],
            "tag1": feedback[2],
            "tag2": feedback[3],
            "isRevoked": feedback[4],
        },
        "summary": {
            "count": summary[0],
            "value": summary[1],
            "valueDecimals": summary[2],
        },
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        raise
