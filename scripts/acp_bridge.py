"""Python-side process bridge for the isolated Standing ACP adapter."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping


class AcpBridgeError(RuntimeError):
    """Raised when the ACP adapter cannot produce a successful typed result."""

    def __init__(self, message: str, *, event_type: str | None = None, entries: Any = None) -> None:
        super().__init__(message)
        self.event_type = event_type
        self.entries = entries


def run_acp_job(
    request: Mapping[str, Any],
    *,
    adapter_dir: str | Path,
    environment: Mapping[str, str] | None = None,
    env_file: str | Path | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Run the TypeScript adapter and return a validated completed result.

    Credentials are supplied only through the child process environment. The
    JSON request and response never contain private keys.
    """

    adapter_path = Path(adapter_dir)
    if environment is None:
        base_environment = dict(os.environ)
        dotenv_path = Path(env_file) if env_file is not None else adapter_path.parent / ".env"
        for key, value in load_environment_file(dotenv_path).items():
            base_environment.setdefault(key, value)
    else:
        base_environment = dict(environment)
    child_environment = adapter_environment(base_environment)
    try:
        completed = subprocess.run(
            ["npm", "start"],
            cwd=adapter_path,
            input=json.dumps(dict(request), separators=(",", ":")),
            text=True,
            capture_output=True,
            env=child_environment,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise AcpBridgeError("ACP adapter timed out") from error
    except OSError as error:
        raise AcpBridgeError("ACP adapter process could not be started") from error
    response = _parse_response(completed.stdout)
    if completed.returncode != 0 or response.get("ok") is not True:
        error = response.get("error") if isinstance(response, dict) else None
        if isinstance(error, dict):
            raise AcpBridgeError(
                str(error.get("message", "ACP adapter failed")),
                event_type=_optional_string(error.get("eventType")),
                entries=error.get("entries"),
            )
        raise AcpBridgeError("ACP adapter exited without a successful response")
    result = response.get("result")
    _validate_result(result)
    return result


def load_environment_file(path: str | Path) -> dict[str, str]:
    """Read simple KEY=VALUE entries without logging or expanding secrets."""

    dotenv_path = Path(path).expanduser()
    if not dotenv_path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key.strip()):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def adapter_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Copy the environment and map legacy buyer names into adapter names."""

    child = dict(environment)
    aliases = {
        "STANDING_ACP_WALLET_ADDRESS": "BUYER_AGENT_WALLET_ADDRESS",
        "STANDING_ACP_WALLET_ID": "BUYER_WALLET_ID",
        "STANDING_ACP_SIGNER_PRIVATE_KEY": "BUYER_SIGNER_PRIVATE_KEY",
    }
    for target, source in aliases.items():
        if not child.get(target, "").strip() and child.get(source, "").strip():
            child[target] = child[source]
    return child


def _parse_response(stdout: str) -> dict[str, Any]:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise AcpBridgeError("ACP adapter produced no JSON response")
    try:
        response = json.loads(lines[-1])
    except json.JSONDecodeError as error:
        raise AcpBridgeError("ACP adapter produced invalid JSON") from error
    if not isinstance(response, dict):
        raise AcpBridgeError("ACP adapter response must be a JSON object")
    return response


def _validate_result(result: Any) -> None:
    if not isinstance(result, dict) or not isinstance(result.get("jobId"), str):
        raise AcpBridgeError("ACP adapter returned an invalid job result")
    if result.get("status") != "completed":
        raise AcpBridgeError("ACP adapter returned a non-completed job")
    if not isinstance(result.get("entries"), list):
        raise AcpBridgeError("ACP adapter result is missing entries")


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None
