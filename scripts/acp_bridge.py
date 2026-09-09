"""Python-side process bridge for the isolated Standing ACP adapter."""

from __future__ import annotations

import json
import os
import re
import selectors
import subprocess
import time
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
    verifier_process: subprocess.Popen[str] | None = None
    try:
        if request.get("startVerifier") is True:
            verifier_process = start_verifier_worker(
                adapter_path,
                child_environment,
                _timeout_seconds(request.get("verifierStartupTimeoutMs"), 30.0),
            )
        completed = _run_adapter(
            adapter_path,
            child_environment,
            request,
            verifier_process,
            timeout_seconds,
        )
    except OSError as process_error:
        raise AcpBridgeError("ACP adapter process could not be started") from process_error
    finally:
        if verifier_process is not None:
            stop_verifier_worker(verifier_process)
    response = _parse_response(completed.stdout)
    if completed.returncode != 0 or response.get("ok") is not True:
        response_error = response.get("error") if isinstance(response, dict) else None
        if isinstance(response_error, dict):
            raise AcpBridgeError(
                str(response_error.get("message", "ACP adapter failed")),
                event_type=_optional_string(response_error.get("eventType")),
                entries=response_error.get("entries"),
            )
        raise AcpBridgeError("ACP adapter exited without a successful response")
    return _validate_result(response.get("result"))


def _run_adapter(
    adapter_path: Path,
    environment: Mapping[str, str],
    request: Mapping[str, Any],
    verifier_process: subprocess.Popen[str] | None,
    timeout_seconds: float | None,
) -> subprocess.CompletedProcess[str]:
    """Run the buyer and fail promptly if the seller exits unsuccessfully."""

    process = subprocess.Popen(
        ["npm", "start"],
        cwd=adapter_path,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=dict(environment),
    )
    if process.stdin is None:
        _terminate_process(process)
        raise AcpBridgeError("ACP adapter has no request stream")
    process.stdin.write(json.dumps(dict(request), separators=(",", ":")))
    process.stdin.close()
    process.stdin = None
    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
    try:
        while process.poll() is None:
            if verifier_process is not None:
                verifier_code = verifier_process.poll()
                if verifier_code not in {None, 0, -15, -9}:
                    _terminate_process(process)
                    detail = _stream_text(verifier_process.stderr)
                    suffix = f": {detail}" if detail else ""
                    raise AcpBridgeError(
                        f"ACP verifier worker exited unsuccessfully{suffix}"
                    )
            if deadline is not None and time.monotonic() >= deadline:
                _terminate_process(process)
                raise AcpBridgeError("ACP adapter timed out")
            time.sleep(0.1)
    finally:
        if process.poll() is None:
            _terminate_process(process)
    stdout, stderr = process.communicate()
    if process.returncode is None:
        raise AcpBridgeError("ACP adapter did not report an exit status")
    return subprocess.CompletedProcess(
        process.args,
        process.returncode,
        stdout,
        stderr,
    )


def start_verifier_worker(
    adapter_path: Path,
    environment: Mapping[str, str],
    startup_timeout_seconds: float,
) -> subprocess.Popen[str]:
    """Start the separate seller agent and wait for its ready line."""

    try:
        process = subprocess.Popen(
            ["node", "--import", "tsx", "src/verifier.ts"],
            cwd=adapter_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=dict(environment),
            bufsize=1,
        )
    except OSError as process_error:
        raise AcpBridgeError("ACP verifier worker could not be started") from process_error
    if process.stdout is None:
        process.kill()
        raise AcpBridgeError("ACP verifier worker has no readiness stream")

    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + startup_timeout_seconds
    try:
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            events = selector.select(remaining)
            if not events:
                break
            line = process.stdout.readline().strip()
            if not line:
                if process.poll() is not None:
                    detail = _stream_text(process.stderr)
                    suffix = f": {detail}" if detail else ""
                    raise AcpBridgeError(
                        f"ACP verifier worker exited before readiness{suffix}"
                    )
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as error:
                raise AcpBridgeError("ACP verifier worker produced invalid readiness JSON") from error
            if isinstance(message, dict) and message.get("ready") is True:
                return process
            raise AcpBridgeError("ACP verifier worker did not announce readiness")
    finally:
        selector.close()

    _terminate_process(process)
    raise AcpBridgeError("ACP verifier worker startup timed out")


def stop_verifier_worker(process: subprocess.Popen[str]) -> None:
    """Stop the seller process without copying its stderr into the result."""

    if process.poll() is None:
        _terminate_process(process)
    if process.returncode not in {0, -15, -9}:
        raise AcpBridgeError("ACP verifier worker exited unsuccessfully")


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _stream_text(stream: Any) -> str:
    if stream is None:
        return ""
    try:
        return str(stream.read()).strip()
    except OSError:
        return ""


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
    for secret_name in (
        "OPENAI_API_KEY",
        "BASE_SIGNER_PRIVATE_KEY",
        "WHITELISTED_WALLET_PRIVATE_KEY",
    ):
        child.pop(secret_name, None)
    aliases = {
        "STANDING_ACP_WALLET_ADDRESS": "BUYER_AGENT_WALLET_ADDRESS",
        "STANDING_ACP_WALLET_ID": "BUYER_WALLET_ID",
        "STANDING_ACP_SIGNER_PRIVATE_KEY": "BUYER_SIGNER_PRIVATE_KEY",
        "STANDING_ACP_SELLER_WALLET_ADDRESS": "SELLER_AGENT_WALLET_ADDRESS",
        "STANDING_ACP_SELLER_WALLET_ID": "SELLER_WALLET_ID",
        "STANDING_ACP_SELLER_SIGNER_PRIVATE_KEY": "SELLER_SIGNER_PRIVATE_KEY",
    }
    for target, source in aliases.items():
        if not child.get(target, "").strip() and child.get(source, "").strip():
            child[target] = child[source]
    return child


def _timeout_seconds(value: Any, default: float) -> float:
    if value is None:
        return default
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise AcpBridgeError("verifierStartupTimeoutMs must be positive")
    return float(value) / 1000.0


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


def _validate_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict) or not isinstance(result.get("jobId"), str):
        raise AcpBridgeError("ACP adapter returned an invalid job result")
    if result.get("status") != "completed":
        raise AcpBridgeError("ACP adapter returned a non-completed job")
    if not isinstance(result.get("entries"), list):
        raise AcpBridgeError("ACP adapter result is missing entries")
    return result


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None
