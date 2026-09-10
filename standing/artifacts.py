"""Safe ingestion of engineering artifacts for advisory decision extraction."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import Any


class ArtifactIngestionError(ValueError):
    """Raised when an engineering artifact cannot be safely captured."""


_MAX_ARTIFACT_BYTES = 1_000_000


@dataclass(frozen=True)
class ArtifactSnapshot:
    """A bounded, hashed text snapshot supplied to an advisory extractor."""

    path: str
    artifact_type: str
    text: str
    sha256: str
    captured_at: int
    size_bytes: int

    @classmethod
    def read(
        cls,
        path: str | Path,
        *,
        root: str | Path = ".",
        captured_at: int | None = None,
        max_bytes: int = _MAX_ARTIFACT_BYTES,
    ) -> ArtifactSnapshot:
        """Read one UTF-8 artifact while preventing path escape and oversize input."""

        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
            raise ArtifactIngestionError("max_bytes must be a positive integer")
        root_path = Path(root).expanduser().resolve()
        raw_path = Path(path).expanduser()
        candidate = raw_path if raw_path.is_absolute() else root_path / raw_path
        resolved = candidate.resolve()
        try:
            relative = resolved.relative_to(root_path)
        except ValueError as error:
            raise ArtifactIngestionError("artifact path must remain inside the configured root") from error
        if resolved == root_path or not resolved.is_file():
            raise ArtifactIngestionError(f"artifact is not a regular file: {relative}")
        try:
            data = resolved.read_bytes()
        except OSError as error:
            raise ArtifactIngestionError(f"could not read artifact {relative}") from error
        if len(data) > max_bytes:
            raise ArtifactIngestionError(
                f"artifact {relative} exceeds the {max_bytes}-byte ingestion limit"
            )
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ArtifactIngestionError("engineering artifacts must be UTF-8 text") from error
        timestamp = int(time()) if captured_at is None else captured_at
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
            raise ArtifactIngestionError("captured_at must be a non-negative integer")
        relative_name = relative.as_posix()
        return cls(
            path=relative_name,
            artifact_type=classify_artifact(relative_name),
            text=text,
            sha256=hashlib.sha256(data).hexdigest(),
            captured_at=timestamp,
            size_bytes=len(data),
        )

    def as_dict(self, *, include_text: bool = True) -> dict[str, Any]:
        """Return a JSON-compatible capture record."""

        result: dict[str, Any] = {
            "path": self.path,
            "artifact_type": self.artifact_type,
            "sha256": self.sha256,
            "captured_at": self.captured_at,
            "size_bytes": self.size_bytes,
        }
        if include_text:
            result["text"] = self.text
        return result


def classify_artifact(path: str) -> str:
    """Classify common reasoning artifacts without interpreting their claims."""

    name = Path(path).name.lower()
    suffix = Path(path).suffix.lower()
    if "adr" in name:
        return "ADR"
    if "rfc" in name:
        return "RFC"
    if "issue" in name:
        return "ISSUE"
    if "pr" in name or "pull" in name:
        return "PR"
    if suffix in {".md", ".markdown", ".rst", ".txt"}:
        return "DESIGN_DOCUMENT"
    if suffix in {".yaml", ".yml", ".json", ".toml", ".ini", ".tf", ".hcl"}:
        return "CONFIGURATION"
    if suffix in {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java"}:
        return "CODE_COMMENT"
    return "ENGINEERING_ARTIFACT"
