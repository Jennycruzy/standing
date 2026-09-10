"""Command-line entry points for the Standing reviewer."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Mapping, Sequence

from .acp import AcpVerifierClient, load_acp_config
from .acceptance import load_acceptance_policy
from .artifacts import ArtifactSnapshot
from .memory import create_memory_store
from .model_review import ModelDecisionExtractor, ModelReviewError, OpenAIResponsesClient
from .reviewer import ReviewerToolError, ReviewerTools
from .temporal import TemporalObservationError


ROOT = Path(__file__).resolve().parents[1]
DEMO_SOURCE_PATH = ROOT / "docs" / "demo" / "acme-retention.json"


def main(argv: Sequence[str] | None = None) -> int:
    """Run one of Standing's product commands."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "deletion-test":
            return _deletion_test()
        if args.command == "dashboard":
            return _dashboard(args)
        store = create_memory_store(
            path=args.memory_path,
            tenant_id=args.tenant_id,
        )
        try:
            tools = ReviewerTools(store)
            if args.command == "boot":
                payload = _boot(tools)
            elif args.command == "review":
                payload = _review(tools, args)
            elif args.command == "condition":
                payload = _condition(tools, args)
            elif args.command == "history":
                payload = _history(tools, args)
            elif args.command == "decision":
                payload = _decision(store, tools, args)
            elif args.command == "waiver":
                payload = _waiver(store, args)
            else:
                raise ReviewerToolError(f"unsupported command: {args.command}")
            _print_json(payload)
            return 0
        finally:
            store.close()
    except (OSError, ValueError, ModelReviewError, ReviewerToolError, TemporalObservationError) as error:
        print(f"standing: {error}", file=sys.stderr)
        return 2


def _dashboard(args: argparse.Namespace) -> int:
    """Serve the dashboard, isolating the fixed demo from project memory."""

    from .dashboard import DashboardApp, serve_dashboard

    if args.demo:
        with TemporaryDirectory(prefix="standing-dashboard-demo-") as directory:
            store = create_memory_store(
                path=Path(directory) / "memory.db",
                tenant_id=args.tenant_id,
            )
            try:
                serve_dashboard(DashboardApp(store, demo=True), host=args.host, port=args.port)
            finally:
                store.close()
        return 0

    store = create_memory_store(path=args.memory_path, tenant_id=args.tenant_id)
    try:
        serve_dashboard(DashboardApp(store, demo=False), host=args.host, port=args.port)
    finally:
        store.close()
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="standing", description=__doc__)
    parser.add_argument("--memory-path", type=Path, help="Sibyl local database path")
    parser.add_argument("--tenant-id", default="00000000-0000-0000-0000-000000000001")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("boot", help="load the remembered standing journal")

    review = commands.add_parser("review", help="review changed repository paths")
    review.add_argument("paths", nargs="*", help="changed paths; defaults to the current git diff")
    review_sources = review.add_mutually_exclusive_group()
    review_sources.add_argument("--base", help="review paths changed from a git base")
    review_sources.add_argument("--commit", help="review paths changed in one commit")
    review_sources.add_argument("--pr", type=int, help="read a preloaded config/demo/pr-N.json change set")
    review.add_argument(
        "--revalidate",
        action="store_true",
        help="hire the configured ACP verifier when a dependency is stale",
    )
    review.add_argument("--observer-address", help="ACP observer address used by --revalidate")
    review.add_argument("--spent-today-usdc", type=float, default=0.0)

    condition = commands.add_parser("condition", help="query one condition")
    condition.add_argument("condition_key")
    condition.add_argument("--valid-as-of", dest="valid_as_of")
    condition.add_argument("--known-as-of", dest="known_as_of")
    condition_visibility = condition.add_mutually_exclusive_group()
    condition_visibility.add_argument(
        "--accepted-only",
        dest="accepted_only",
        action="store_true",
        default=True,
        help="return only accepted evidence (the default)",
    )
    condition_visibility.add_argument(
        "--include-unaccepted",
        dest="accepted_only",
        action="store_false",
        help="include unaccepted observations for diagnostic inspection",
    )

    history = commands.add_parser("history", help="show a condition's temporal evidence chain")
    history.add_argument("condition_key")
    history.add_argument("--known-as-of", dest="known_as_of")
    history.add_argument("--accepted-only", action="store_true")

    decision = commands.add_parser("decision", help="inspect remembered decisions")
    decision_commands = decision.add_subparsers(dest="decision_command")
    decision_commands.add_parser("list", help="list active decisions")
    decision_show = decision_commands.add_parser("show", help="show one decision")
    decision_show.add_argument("decision_id")
    decision_ingest = decision_commands.add_parser("ingest", help="capture an engineering artifact")
    decision_ingest.add_argument("artifact", type=Path)
    decision_propose = decision_commands.add_parser(
        "propose",
        help="ask the advisory model for a decision envelope from an artifact",
    )
    decision_propose.add_argument("artifact", type=Path)
    decision_propose.add_argument("--config", type=Path, default=ROOT / "config" / "model.json")
    decision_confirm = decision_commands.add_parser(
        "confirm",
        help="human-confirm a pending proposal and persist the decision",
    )
    decision_confirm.add_argument("proposal_id")
    decision_confirm.add_argument("--by", required=True, dest="confirmed_by")
    decision_confirm.add_argument("--note", required=True, dest="confirmation_note")
    decision_confirm.add_argument("--at", dest="confirmed_at")
    decision_reject = decision_commands.add_parser(
        "reject",
        help="human-reject a pending decision proposal",
    )
    decision_reject.add_argument("proposal_id")
    decision_reject.add_argument("--by", required=True, dest="rejected_by")
    decision_reject.add_argument("--reason", required=True)
    decision_reject.add_argument("--at", dest="rejected_at")
    decision_current = decision_commands.add_parser("current", help="find the decision governing a path now")
    decision_current.add_argument("path")
    decision_valid = decision_commands.add_parser("as-of", help="find the decision governing a path at a date")
    decision_valid.add_argument("path")
    decision_valid.add_argument("date")
    decision_known = decision_commands.add_parser("known-as-of", help="find what decision Standing knew then")
    decision_known.add_argument("path")
    decision_known.add_argument("date")

    waiver = commands.add_parser("waiver", help="inspect human-issued waivers")
    waiver_commands = waiver.add_subparsers(dest="waiver_command")
    waiver_commands.add_parser("list", help="list active waivers")
    waiver_show = waiver_commands.add_parser("show", help="show one waiver")
    waiver_show.add_argument("waiver_id")

    dashboard = commands.add_parser("dashboard", help="serve the interactive dashboard")
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8787)
    dashboard.add_argument(
        "--demo",
        action="store_true",
        help="serve an isolated fixed controlled demo without mutating configured memory",
    )

    commands.add_parser("deletion-test", help="run the memory-on/off comparison")
    return parser


def _boot(tools: ReviewerTools) -> dict[str, Any]:
    changes = tools.read_boot_state().changes
    return {
        "command": "boot",
        "memory": "configured through the shared store boundary",
        "journal_entries": len(changes),
        "journal": list(changes),
    }


def _review(tools: ReviewerTools, args: argparse.Namespace) -> dict[str, Any]:
    paths = tuple(args.paths) if args.paths else _changed_paths(args)
    if args.revalidate:
        if args.observer_address is None:
            raise ValueError("--observer-address is required with --revalidate")
        verifier_config = _read_json(ROOT / "config" / "verifier.json")
        conditions = verifier_config.get("conditions")
        if not isinstance(conditions, Mapping):
            raise ValueError("verifier.conditions must be an object")
        source_specs: dict[str, dict[str, Any]] = {}
        source_bindings: dict[str, dict[str, Any]] = {}
        for key, value in conditions.items():
            if not isinstance(key, str) or not isinstance(value, Mapping):
                continue
            extraction = value.get("extraction")
            if not isinstance(extraction, Mapping):
                continue
            source_specs[key] = {
                "source_url": value.get("source_url"),
                "value_type": value.get("value_type"),
                "unit": extraction.get("unit"),
            }
            binding = value.get("source_binding")
            if isinstance(binding, Mapping):
                source_bindings[key] = dict(binding)
        client = AcpVerifierClient(
            adapter_dir=ROOT / "acp-adapter",
            config=load_acp_config(ROOT / "config" / "acp.json"),
            env_file=ROOT / ".env",
        )
        reviews = tools.review_paths_with_revalidation(
            paths,
            client=client,
            policy=load_acceptance_policy(ROOT / "config" / "policy.json"),
            observer_address=args.observer_address,
            source_specs=source_specs,
            source_bindings=source_bindings,
            spent_today_usdc=args.spent_today_usdc,
        )
    else:
        reviews = tools.review_paths(paths)
    serialized = [
        {
            "decision_id": item.decision_id,
            "blocks": item.blocks,
            "action": "BLOCK" if item.blocks else "ALLOW",
            "evaluation": item.evaluation.as_dict(),
        }
        for item in reviews
    ]
    return {
        "command": "review",
        "changed_paths": list(paths),
        "decisions_found": len(serialized),
        "blocked": any(item["blocks"] for item in serialized),
        "decisions": serialized,
    }


def _changed_paths(args: argparse.Namespace) -> tuple[str, ...]:
    if args.pr is not None:
        fixture = ROOT / "config" / "demo" / f"pr-{args.pr}.json"
        with fixture.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        if not isinstance(raw, Mapping) or not isinstance(raw.get("changed_paths"), list):
            raise ValueError(f"{fixture} must contain a changed_paths list")
        return tuple(_required_path(path) for path in raw["changed_paths"])
    if args.commit is not None:
        command = ["git", "diff", "--name-only", f"{args.commit}^", args.commit, "--"]
    elif args.base is not None:
        command = ["git", "diff", "--name-only", args.base, "--"]
    else:
        command = ["git", "diff", "--name-only", "--"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or "git diff failed")
    paths = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    if args.base is None and args.commit is None:
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if staged.returncode != 0:
            raise ValueError(staged.stderr.strip() or "git staged diff failed")
        paths.update(line.strip() for line in staged.stdout.splitlines() if line.strip())
    return tuple(sorted(paths))


def _condition(tools: ReviewerTools, args: argparse.Namespace) -> dict[str, Any]:
    if args.valid_as_of is not None and args.known_as_of is not None:
        raise ValueError("condition accepts only one of --valid-as-of or --known-as-of")
    if args.valid_as_of is not None:
        observation = tools.condition_valid_as_of(
            args.condition_key,
            args.valid_as_of,
            accepted_only=args.accepted_only,
        )
        query = "valid_as_of"
    elif args.known_as_of is not None:
        observation = tools.condition_known_as_of(
            args.condition_key,
            args.known_as_of,
            accepted_only=args.accepted_only,
        )
        query = "known_as_of"
    else:
        observation = tools.current_condition(
            args.condition_key,
            accepted_only=args.accepted_only,
        )
        query = "current"
    return {
        "command": "condition",
        "query": query,
        "condition_key": args.condition_key,
        "status": "ESTABLISHED" if observation is not None else "UNKNOWN",
        "observation": None if observation is None else observation.as_dict(),
    }


def _history(tools: ReviewerTools, args: argparse.Namespace) -> dict[str, Any]:
    observations = tools.condition_history(
        args.condition_key,
        knowledge_at=args.known_as_of,
        accepted_only=args.accepted_only,
    )
    return {
        "command": "history",
        "condition_key": args.condition_key,
        "observations": [item.as_dict() for item in observations],
    }


def _decision(store: Any, tools: ReviewerTools, args: argparse.Namespace) -> dict[str, Any]:
    command = args.decision_command or "list"
    if command == "ingest":
        artifact = ArtifactSnapshot.read(args.artifact, root=ROOT)
        stored = tools.ingest_artifact(artifact)
        return {
            "command": "decision ingest",
            "artifact": artifact.as_dict(include_text=False),
            "stored": stored,
        }
    if command == "propose":
        artifact = ArtifactSnapshot.read(args.artifact, root=ROOT)
        tools.ingest_artifact(artifact)
        config = _read_json(args.config)
        models = config.get("models")
        if not isinstance(models, Mapping):
            raise ValueError("model config must contain a models object")
        model_id = models.get("extraction")
        api_key_env = config.get("api_key_env")
        endpoint = config.get("responses_endpoint")
        timeout = config.get("timeout_seconds")
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("models.extraction must be a non-empty string")
        if not isinstance(api_key_env, str) or not api_key_env.strip():
            raise ValueError("api_key_env must be a non-empty string")
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("responses_endpoint must be a non-empty string")
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError("timeout_seconds must be a positive integer")
        client = OpenAIResponsesClient.from_env(
            env_name=api_key_env,
            endpoint=endpoint,
            timeout_seconds=timeout,
        )
        proposal = ModelDecisionExtractor(client, model_id=model_id).propose(
            artifact_path=artifact.path,
            artifact_type=artifact.artifact_type,
            artifact_text=artifact.text,
            artifact_sha256=artifact.sha256,
        )
        tools.record_decision_proposal(proposal)
        return {
            "command": "decision propose",
            "artifact": artifact.as_dict(include_text=False),
            "proposal": proposal.as_dict(),
        }
    if command == "confirm":
        record = tools.confirm_decision_proposal(
            args.proposal_id,
            confirmed_by=args.confirmed_by,
            confirmation_note=args.confirmation_note,
            confirmed_at=args.confirmed_at,
        )
        return {"command": "decision confirm", "decision_id": record.decision_id, "body": record.body}
    if command == "reject":
        stored = tools.reject_decision_proposal(
            args.proposal_id,
            rejected_by=args.rejected_by,
            reason=args.reason,
            rejected_at=args.rejected_at,
        )
        return {"command": "decision reject", "proposal": _body(stored)}
    if command == "show":
        entity = store.read_decision(args.decision_id)
        return {"command": "decision show", "decision_id": args.decision_id, "body": _body(entity)}
    if command == "current":
        current_record = tools.current_decision(args.path)
        return _decision_query("current_decision", args.path, current_record)
    if command == "as-of":
        valid_record = tools.decision_as_of(args.path, args.date)
        return _decision_query("decision_as_of", args.path, valid_record)
    if command == "known-as-of":
        known_record = tools.decision_known_as_of(args.path, args.date)
        return _decision_query("decision_known_as_of", args.path, known_record)
    if command == "list":
        decisions = []
        for entity in store.list_decisions():
            decision_id = entity.get("key", entity.get("name"))
            if not isinstance(decision_id, str):
                raise ValueError("Sibyl returned a decision without an ID")
            decisions.append({"decision_id": decision_id, "body": _body(entity)})
        return {"command": "decision list", "decisions": decisions}
    raise ValueError(f"unsupported decision command: {command}")


def _decision_query(
    query: str,
    path: str,
    record: Any,
) -> dict[str, Any]:
    if record is None:
        return {"command": query, "path": path, "decision": None, "status": "UNKNOWN"}
    return {
        "command": query,
        "path": path,
        "status": "ESTABLISHED",
        "decision": {"decision_id": record.decision_id, "body": record.body},
    }


def _waiver(store: Any, args: argparse.Namespace) -> dict[str, Any]:
    command = args.waiver_command or "list"
    if command == "show":
        entity = store.read_waiver(args.waiver_id)
        return {"command": "waiver show", "waiver_id": args.waiver_id, "body": _body(entity)}
    if command == "list":
        waivers = []
        for entity in store.list_all_waivers():
            waiver_id = entity.get("key", entity.get("name"))
            if not isinstance(waiver_id, str):
                raise ValueError("Sibyl returned a waiver without an ID")
            waivers.append({"waiver_id": waiver_id, "body": _body(entity)})
        return {"command": "waiver list", "waivers": waivers}
    raise ValueError(f"unsupported waiver command: {command}")


def _deletion_test() -> int:
    source_fact = _read_demo_fact()
    # The deletion test runs the fixed post-change scenario without mutating
    # the checked-in controlled source.  This mirrors the dashboard's
    # BREAK DEMO ASSUMPTION action and keeps the comparison deterministic.
    fact = 90 if source_fact == 365 else source_fact
    with TemporaryDirectory(prefix="standing-deletion-test-") as directory:
        root = Path(directory)
        on_store = create_memory_store(path=root / "memory-on.db", tenant_id="deletion-test-on")
        off_store = create_memory_store(path=root / "memory-off.db", tenant_id="deletion-test-off")
        try:
            on_tools = ReviewerTools(on_store)
            off_tools = ReviewerTools(off_store)
            _seed_deletion_scenario(on_store, fact)
            on_review = on_tools.review_paths(["src/archive.py"])
            off_review = off_tools.review_paths(["src/archive.py"])
            on_decision = on_review[0] if on_review else None
            payload = {
                "command": "deletion-test",
                "external_fact": {
                    "retention_days": fact,
                    "source_value_before_fixed_change": source_fact,
                },
                "memory_on": {
                    "decision_found": None if on_decision is None else on_decision.decision_id,
                    "assumption_recovered": "retention_days >= 365",
                    "expiry_detected": bool(on_decision and on_decision.blocks),
                    "protection": "BLOCK" if on_decision and on_decision.blocks else "ALLOW",
                },
                "memory_off": {
                    "decision_found": None,
                    "assumption_recovered": None,
                    "expiry_detected": False,
                    "protection": "HISTORICAL PROTECTION UNAVAILABLE",
                },
            }
            _print_json(payload)
            return 0
        finally:
            on_store.close()
            off_store.close()


def _seed_deletion_scenario(store: Any, fact: int) -> None:
    store.save_decision(
        "ACME-001",
        {
            "title": "Use Acme for event archives",
            "governed_paths": ["src/archive.py"],
            "conditions": [
                {
                    "condition_key": "sandbox.demo.retention_days",
                    "predicate": "retention_days >= 365",
                    "provenance": "CONFIRMED",
                    "required": True,
                }
            ],
        },
    )
    store.save_condition_reference(
        "sandbox.demo.retention_days",
        {
            "condition_key": "sandbox.demo.retention_days",
            "accepted_value": fact,
            "unit": "days",
            "accepted_source_url": "https://controlled-demo.invalid/acme-retention",
            "observation_uids": ["controlled-demo-current"],
            "basis": "controlled demo source",
        },
    )


def _read_demo_fact() -> int:
    with DEMO_SOURCE_PATH.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, Mapping):
        raise ValueError("controlled demo source must contain an object")
    value = raw.get("retention_days")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("controlled demo retention_days must be a non-negative integer")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain an object")
    return raw


def _body(entity: Mapping[str, Any]) -> dict[str, Any]:
    body = entity.get("body")
    if not isinstance(body, dict):
        raise ValueError("Sibyl record has no mapping body")
    return dict(body)


def _required_path(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("changed paths must be non-empty strings")
    return value.strip()


def _print_json(value: Mapping[str, Any]) -> None:
    print(json.dumps(dict(value), indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    raise SystemExit(main())
