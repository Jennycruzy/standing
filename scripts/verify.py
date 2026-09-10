"""Run the provider-independent Standing verification surface."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from standing.evaluation import EvaluationDataset, EvaluationDatasetError

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "evidence" / "runs"
LATEST_JSON = ROOT / "evidence" / "LATEST.json"
LATEST_MD = ROOT / "evidence" / "LATEST.md"


def _run(label: str, command: list[str]) -> tuple[str, int]:
    print(f"\n== {label} ==")
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    output = (completed.stdout + completed.stderr).strip()
    if output:
        print(output)
    if completed.returncode != 0:
        raise SystemExit(f"verification failed during {label}")
    return output, completed.returncode


def _count(output: str, pattern: str) -> int | None:
    match = re.search(pattern, output, flags=re.IGNORECASE)
    return None if match is None else int(match.group(1))


def _validate_corpora() -> tuple[int, int, int, int]:
    """Validate the separated release manifests without inventing predictions."""

    try:
        public = EvaluationDataset.load(ROOT / "docs" / "evaluation" / "cases.json")
        controlled = EvaluationDataset.load(ROOT / "docs" / "evaluation" / "adversarial.json")
    except EvaluationDatasetError as error:
        raise SystemExit(f"corpus validation failed: {error}") from error
    if len(public.real_cases) < 3:
        raise SystemExit("corpus validation failed: at least three public cases are required")
    if public.pending_real_cases:
        raise SystemExit("corpus validation failed: every public case must be human-reviewed")
    if not public.has_real_vendor_expiry:
        raise SystemExit("corpus validation failed: a reviewed vendor-expiry case is required")
    if not controlled.cases or not all(case.synthetic for case in controlled.cases):
        raise SystemExit("corpus validation failed: controlled cases must be synthetic")
    return (
        len(public.real_cases),
        len(public.reviewed_real_cases),
        len(public.real_vendor_expiry_cases),
        len(controlled.synthetic_cases),
    )


def _commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.stdout.strip() or "working-tree"


def _write_artifacts(report: dict[str, Any]) -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    timestamp = report["utc_timestamp"].replace(":", "").replace("-", "")
    stem = f"{timestamp}-{report['commit']}"
    json_path = RUNS / f"{stem}.json"
    markdown_path = RUNS / f"{stem}.md"
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    json_path.write_text(encoded, encoding="utf-8")
    markdown = "\n".join(
        [
            "# Standing verification run",
            "",
            f"- UTC: `{report['utc_timestamp']}`",
            f"- Commit: `{report['commit']}`",
            f"- Python: `{report['python']}`",
            f"- Node: `{report['node']}`",
            "",
            "## Checks",
            "",
            "| Check | Result |",
            "| --- | --- |",
            *[f"| {key} | `{value}` |" for key, value in report["checks"].items()],
            "",
            "## Corpus",
            "",
            f"- Public repository cases: `{report['corpus']['public_cases']}`",
            f"- Human-reviewed public cases: `{report['corpus']['reviewed_public_cases']}`",
            f"- Reviewed vendor-expiry cases: `{report['corpus']['vendor_expiry_cases']}`",
            f"- Controlled scenarios: `{report['corpus']['controlled_scenarios']}`",
            "",
            "This artifact records verification output; it does not claim an unrun benchmark score.",
            "",
        ]
    )
    markdown_path.write_text(markdown, encoding="utf-8")
    LATEST_JSON.write_text(encoded, encoding="utf-8")
    LATEST_MD.write_text(markdown, encoding="utf-8")
    print(f"\nEvidence written to {json_path.relative_to(ROOT)}")


def main() -> int:
    python_version = sys.version.split()[0]
    pytest_output, _ = _run("Python tests", [sys.executable, "-m", "pytest", "-q"])
    mypy_output, _ = _run("strict Python typing", [sys.executable, "-m", "mypy", "--strict", "standing"])
    if "Success: no issues found" not in mypy_output:
        raise SystemExit("strict Python typing did not report a clean result")
    _run("TypeScript dependencies", ["npm", "ci", "--prefix", "acp-adapter"])
    ts_output, _ = _run("TypeScript tests", ["npm", "--prefix", "acp-adapter", "test"])
    _run("TypeScript typing", ["npm", "--prefix", "acp-adapter", "run", "typecheck"])
    memory_output, _ = _run("fresh-process memory proof", [sys.executable, "-m", "standing", "memory-proof"])
    try:
        memory = json.loads(memory_output)
    except json.JSONDecodeError as error:
        raise SystemExit("memory proof did not return JSON") from error
    if memory.get("memory_on", {}).get("protection") != "BLOCK":
        raise SystemExit("memory proof did not block with memory present")
    if memory.get("memory_off", {}).get("protection") != "HISTORICAL PROTECTION UNAVAILABLE":
        raise SystemExit("memory proof did not remove historical protection")

    public_cases, reviewed_public_cases, vendor_expiry_cases, controlled_cases = _validate_corpora()
    python_tests = _count(pytest_output, r"(\d+) passed")
    typescript_tests = _count(ts_output, r"# tests\s+(\d+)") or _count(ts_output, r"(\d+) pass")
    if python_tests is None or python_tests <= 0:
        raise SystemExit("verification did not report Python tests")
    if typescript_tests is None or typescript_tests <= 0:
        raise SystemExit("verification did not report TypeScript tests")
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    report = {
        "status": "PASSED",
        "utc_timestamp": now,
        "commit": _commit(),
        "python": python_version,
        "node": _node_version(),
        "checks": {
            "python_tests": python_tests,
            "mypy_strict": "PASS",
            "typescript_tests": typescript_tests,
            "typescript_typecheck": "PASS",
            "fresh_process_memory": "PASS",
            "memory_removal": "PASS",
            "corpus_validation": "PASS",
        },
        "corpus": {
            "public_cases": public_cases,
            "reviewed_public_cases": reviewed_public_cases,
            "vendor_expiry_cases": vendor_expiry_cases,
            "controlled_scenarios": controlled_cases,
        },
        "memory_proof": memory,
    }
    _write_artifacts(report)
    print("\nSTANDING VERIFICATION PASSED")
    return 0


def _node_version() -> str:
    completed = subprocess.run(["node", "--version"], cwd=ROOT, text=True, capture_output=True, check=False)
    return completed.stdout.strip() or "unavailable"


if __name__ == "__main__":
    raise SystemExit(main())
