"""Run one real ACP verifier job through EAS, memory, and ERC-8004 feedback."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping

from eth_account import Account
from sibyl_memory_client.exceptions import NotFoundError  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.acp_bridge import load_environment_file
from scripts.register_product_schemas import load_base_config, send_registration
from standing.acp import AcpVerifierClient, load_acp_config
from standing.acceptance import load_acceptance_policy
from standing.eas import EasReader, load_eas_config
from standing.memory import create_memory_store
from standing.reputation import (
    decode_feedback,
    decode_last_index,
    evidence_hash,
    feedback_calldata,
    last_index_calldata,
    load_reputation_config,
    read_feedback_calldata,
)
from standing.reviewer import ReviewerToolError, ReviewerTools

ENV_PATH = ROOT / ".env"
CHAIN_CONFIG_PATH = ROOT / "config" / "chain.json"
EAS_CONFIG_PATH = ROOT / "config" / "eas.json"
POLICY_CONFIG_PATH = ROOT / "config" / "policy.json"
ACP_CONFIG_PATH = ROOT / "config" / "acp.json"
REPUTATION_CONFIG_PATH = ROOT / "config" / "reputation.json"
VERIFIER_CONFIG_PATH = ROOT / "config" / "verifier.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condition", default="sandbox.demo.retention_days")
    parser.add_argument("--spent-today-usdc", type=float, default=0.0)
    parser.add_argument(
        "--provider-address",
        help="hire this external Provider address instead of the configured local seller",
    )
    parser.add_argument(
        "--offering-name",
        help="use this Provider offering instead of the configured offering",
    )
    parser.add_argument("--bootstrap", action="store_true", help="use the configured seller before it has three readings")
    parser.add_argument("--job-id", help="resume an existing active ACP job instead of creating a new one")
    parser.add_argument(
        "--manual-approval",
        action="store_true",
        help="assert explicit human approval after reviewing the accumulated evidence",
    )
    parser.add_argument(
        "--approval-id",
        help="use a persisted human approval record when promoting accepted evidence",
    )
    args = parser.parse_args()

    env = load_environment_file(ENV_PATH)
    external_provider = args.provider_address is not None
    seller_address = (
        _required_address(args.provider_address, "provider_address")
        if external_provider
        else _required_env(env, "SELLER_AGENT_WALLET_ADDRESS")
    )
    verifier_condition = _verifier_condition(args.condition)
    source_binding = _object(verifier_condition.get("source_binding"), "verifier source_binding")
    now_unix = int(time.time())
    acp_config = load_acp_config(ACP_CONFIG_PATH)
    policy = load_acceptance_policy(POLICY_CONFIG_PATH)
    store = create_memory_store(path=ROOT / ".standing-memory.db", tenant_id="standing-demo")
    try:
        tools = ReviewerTools(store)
        _ensure_observer_entity(store, seller_address)
        prior_observations = tools.read_observations(args.condition)
        approval_record = _read_approval(store, args.approval_id)
        initial_acceptance = tools.check_acceptance(
            args.condition,
            prior_observations,
            manual_approval=args.manual_approval,
            manual_approval_record=approval_record,
            policy=policy,
            source_binding=source_binding,
            now_unix=now_unix,
        )
        selected_address = (
            seller_address
            if external_provider
            else _select_or_bootstrap(tools, seller_address, policy, args.bootstrap)
        )
        client = AcpVerifierClient(
            adapter_dir=ROOT / "acp-adapter",
            config=acp_config,
            env_file=ENV_PATH,
        )
        observation = tools.hire_verifier(
            client,
            args.condition,
            selected_address,
            acceptance=initial_acceptance,
            spent_today_usdc=args.spent_today_usdc,
            source_url=_required_string(verifier_condition.get("source_url"), "verifier source_url"),
            value_type=_required_string(verifier_condition.get("value_type"), "verifier value_type"),
            unit=_required_string(
                _object(verifier_condition.get("extraction"), "verifier extraction").get("unit"),
                "verifier extraction unit",
            ),
            job_id=args.job_id,
            start_verifier=not external_provider,
            offering_name=args.offering_name,
        )
        chain_observation = _verify_eas_observation(observation, args.condition)
        stored_observation = tools.record_verifier_observation(observation, recorded_at=int(time.time()))
        stored_body = stored_observation.get("body")
        if not isinstance(stored_body, dict):
            raise ReviewerToolError("stored verifier observation has no mapping body")
        accumulated_observations = tools.read_observations(args.condition)
        final_acceptance = tools.check_acceptance(
            args.condition,
            accumulated_observations,
            manual_approval=args.manual_approval,
            manual_approval_record=approval_record,
            policy=policy,
            source_binding=source_binding,
            now_unix=now_unix,
        )
        promotion = None
        if final_acceptance.accepted:
            promotion = tools.promote_acceptance(
                args.condition,
                final_acceptance,
                accumulated_observations,
                accepted_at=now_unix,
            )
        reputation = _write_reputation_signal(
            observation=stored_body,
            confirmed=True,
        )
        history = tools.record_observer_outcome(selected_address, confirmed=True)
        print(
            json.dumps(
                {
                    "condition": args.condition,
                    "observer": selected_address,
                    "jobId": observation.job_id,
                    "observation": chain_observation,
                    "acceptance": final_acceptance.as_dict(),
                    "promotion": None if promotion is None else promotion.as_dict(),
                    "observerHistory": history.as_counts(),
                    "reputation": reputation,
                },
                indent=2,
                sort_keys=True,
            )
        )
    finally:
        store.close()


def _ensure_observer_entity(store: Any, address: str) -> None:
    try:
        store.read_observer(address)
    except NotFoundError:
        store.save_observer(
            address,
            {"readings_given": 0, "readings_confirmed": 0, "readings_contradicted": 0},
        )


def _read_approval(store: Any, approval_id: str | None) -> dict[str, Any] | None:
    if approval_id is None:
        return None
    try:
        stored = store.read_manual_approval(approval_id)
    except NotFoundError as error:
        raise ReviewerToolError(f"manual approval {approval_id} was not found") from error
    body = stored.get("body")
    if not isinstance(body, dict):
        raise ReviewerToolError("stored manual approval has no mapping body")
    return body


def _select_or_bootstrap(
    tools: ReviewerTools,
    seller_address: str,
    policy: Any,
    bootstrap: bool,
) -> str:
    try:
        return tools.select_observer([seller_address], policy).address
    except ReviewerToolError:
        if bootstrap:
            return seller_address
        raise ReviewerToolError(
            "No observer has the required history; use --bootstrap for the first real readings."
        )


def _verify_eas_observation(observation: Any, condition_key: str) -> dict[str, Any]:
    eas_config = load_eas_config(CHAIN_CONFIG_PATH)
    eas_raw = _read_json(EAS_CONFIG_PATH)
    registrations = _object(eas_raw.get("registrations"), "eas.registrations")
    observation_schema = _object(registrations.get("observation"), "eas.registrations.observation")
    source_types_raw = _object(eas_raw.get("source_types"), "eas.source_types")
    source_types = {str(key): _required_string(value, "source type") for key, value in source_types_raw.items()}
    reader = EasReader(eas_config, ROOT / ".standing-eas-cache.json")
    record = reader.read_attestation(observation.observation_uid)
    decoded = record.decode_observation(
        expected_schema_uid=_required_string(observation_schema.get("uid"), "observation schema UID"),
        condition_definition={
            "condition_key": condition_key,
            "value_type": observation.value_type,
            "unit": observation.unit,
        },
        source_type_labels=source_types,
    )
    expected = observation.as_acceptance_record()
    for field in ("condition_key", "value", "source_type", "source_url", "observer_address", "effective_from", "note"):
        if field == "observer_address":
            matches = str(decoded[field]).lower() == str(expected[field]).lower()
        else:
            matches = decoded[field] == expected[field]
        if not matches:
            raise RuntimeError(f"EAS observation does not match ACP delivery for {field}")
    return {
        "uid": record.uid,
        "transactionHash": observation.observation_transaction,
        "transactionUrl": _transaction_url(observation.observation_transaction),
        "sourceUrl": decoded["source_url"],
        "disclosure": expected["disclosure"],
        "provenance": expected["provenance"],
        "blockNumber": record.block_number,
        "refUID": decoded["ref_uid"],
    }


def _verifier_condition(condition_key: str) -> dict[str, Any]:
    raw = _read_json(VERIFIER_CONFIG_PATH)
    conditions = _object(raw.get("conditions"), "verifier.conditions")
    condition = _object(conditions.get(condition_key), f"verifier condition {condition_key}")
    if condition.get("mode") != "source_extract":
        raise RuntimeError("only configured source-extract verifier conditions are runnable")
    extraction = _object(condition.get("extraction"), "verifier extraction")
    if not _required_string(extraction.get("version"), "verifier extraction version"):
        raise RuntimeError("verifier extraction version is required")
    return condition


def _write_reputation_signal(*, observation: Mapping[str, Any], confirmed: bool) -> dict[str, Any]:
    reputation = load_reputation_config(REPUTATION_CONFIG_PATH)
    env = load_environment_file(ENV_PATH)
    private_key = _required_env(env, reputation.client_key_env)
    client_address = Account.from_key(private_key).address
    base = load_base_config(CHAIN_CONFIG_PATH)
    from standing.eas import JsonRpcTransport

    transport = JsonRpcTransport(
        _required_string(base.get("rpcUrl"), "base.rpcUrl"),
        float(base.get("rpcTimeoutSeconds", 0)),
    )
    value = reputation.confirmed_value if confirmed else reputation.contradicted_value
    evidence = {
        "condition_key": observation["condition_key"],
        "observation_uid": observation["observation_uid"],
        "observer_address": observation["observer_address"],
        "acp_job_id": observation["acp_job_id"],
        "confirmed": confirmed,
    }
    data = feedback_calldata(
        reputation,
        value=value,
        observer_address=_required_string(observation.get("observer_address"), "observer address"),
        endpoint=_required_string(observation.get("source_url"), "observation source URL"),
        feedback_uri=_required_string(observation.get("source_url"), "observation source URL"),
        feedback_hash=evidence_hash(evidence),
    )
    tx_hash, receipt = send_registration(
        transport,
        base,
        private_key,
        data,
        reputation.reputation_registry,
    )
    index_raw = transport.request(
        "eth_call",
        [
            {
                "to": reputation.reputation_registry,
                "data": "0x" + last_index_calldata(reputation, client_address).hex(),
            },
            "latest",
        ],
    )
    index = decode_last_index(index_raw)
    if index == 0:
        raise RuntimeError("ERC-8004 reputation write returned no feedback index")
    feedback_raw = transport.request(
        "eth_call",
        [
            {
                "to": reputation.reputation_registry,
                "data": "0x" + read_feedback_calldata(reputation, client_address, index).hex(),
            },
            "latest",
        ],
    )
    feedback = decode_feedback(feedback_raw)
    expected_feedback = (value, reputation.value_decimals, reputation.tag1, observation["observer_address"], False)
    if feedback != expected_feedback:
        raise RuntimeError("ERC-8004 reputation readback did not match the verifier outcome")
    return {
        "agentId": reputation.standing_agent_id,
        "client": client_address,
        "feedbackIndex": index,
        "value": value,
        "tag1": reputation.tag1,
        "tag2": observation["observer_address"],
        "transactionHash": tx_hash,
        "transactionUrl": _transaction_url(tx_hash),
        "blockNumber": receipt.get("blockNumber"),
    }


def _select_or_none(value: Any) -> Any:
    return value


def _transaction_url(tx_hash: Any) -> str | None:
    if not isinstance(tx_hash, str):
        return None
    chain = _read_json(CHAIN_CONFIG_PATH)
    base = _object(chain.get("base"), "chain.base")
    explorers = _object(base.get("explorers"), "base.explorers")
    prefix = explorers.get("transaction")
    return prefix + tx_hash if isinstance(prefix, str) else None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"could not read {path}") from error
    if not isinstance(raw, dict):
        raise RuntimeError(f"{path} must contain an object")
    return raw


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be an object")
    return value


def _required_env(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise RuntimeError(f"{key} is missing")
    return value


def _required_address(value: Any, label: str) -> str:
    address = _required_string(value, label)
    if len(address) != 42 or not address.startswith("0x"):
        raise RuntimeError(f"{label} must be a 20-byte EVM address")
    try:
        bytes.fromhex(address[2:])
    except ValueError as error:
        raise RuntimeError(f"{label} must be a 20-byte EVM address") from error
    return address


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{label} must be a non-empty string")
    return value.strip()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        raise
