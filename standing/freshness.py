"""Pure freshness checks for time-sensitive evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class FreshnessResult:
    """The deterministic freshness result for a set of observations."""

    fresh: bool
    stale_observation_uids: tuple[str, ...]
    missing_timestamp_uids: tuple[str, ...]
    future_timestamp_uids: tuple[str, ...]
    scheduled_recheck_uids: tuple[str, ...] = ()

    @property
    def reasons(self) -> tuple[str, ...]:
        """Return user-facing reasons for evidence that cannot be reused."""

        reasons: list[str] = []
        if self.stale_observation_uids:
            reasons.append(
                "Evidence is stale and must be revalidated: "
                + ", ".join(self.stale_observation_uids)
                + "."
            )
        if self.scheduled_recheck_uids:
            reasons.append(
                "Evidence is due for scheduled revalidation: "
                + ", ".join(self.scheduled_recheck_uids)
                + "."
            )
        if self.missing_timestamp_uids:
            reasons.append(
                "Evidence has no verification timestamp: "
                + ", ".join(self.missing_timestamp_uids)
                + "."
            )
        if self.future_timestamp_uids:
            reasons.append(
                "Evidence has a timestamp in the future: "
                + ", ".join(self.future_timestamp_uids)
                + "."
            )
        return tuple(reasons)


def check_freshness(
    observations: Sequence[Mapping[str, Any]],
    *,
    now_unix: int,
    max_age_seconds: int,
    recheck_interval_seconds: int | None = None,
) -> FreshnessResult:
    """Check knowledge/verification timestamps without implicit state."""

    if not isinstance(now_unix, int) or isinstance(now_unix, bool) or now_unix < 0:
        raise ValueError("now_unix must be a non-negative integer")
    if not isinstance(max_age_seconds, int) or isinstance(max_age_seconds, bool) or max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be a positive integer")
    if recheck_interval_seconds is not None and (
        not isinstance(recheck_interval_seconds, int)
        or isinstance(recheck_interval_seconds, bool)
        or recheck_interval_seconds <= 0
    ):
        raise ValueError("recheck_interval_seconds must be a positive integer when supplied")

    stale: list[str] = []
    missing: list[str] = []
    future: list[str] = []
    scheduled: list[str] = []
    for observation in observations:
        uid = _required_string(observation.get("observation_uid"), "observation_uid")
        # Freshness is about when Standing last verified the fact, not when the
        # vendor says the fact became effective.  ``effective_from`` remains a
        # compatibility fallback for pre-temporal records.
        raw_timestamp = observation.get("recorded_at", observation.get("observed_at"))
        if raw_timestamp is None:
            raw_timestamp = observation.get("effective_from")
        if raw_timestamp is None:
            missing.append(uid)
            continue
        if not isinstance(raw_timestamp, int) or isinstance(raw_timestamp, bool) or raw_timestamp < 0:
            raise ValueError(f"effective_from for {uid} must be a non-negative integer")
        if raw_timestamp > now_unix:
            future.append(uid)
        elif now_unix - raw_timestamp > max_age_seconds:
            stale.append(uid)
        elif recheck_interval_seconds is not None and now_unix - raw_timestamp >= recheck_interval_seconds:
            scheduled.append(uid)

    stale_uids = tuple(sorted(stale))
    missing_uids = tuple(sorted(missing))
    future_uids = tuple(sorted(future))
    scheduled_uids = tuple(sorted(scheduled))
    return FreshnessResult(
        fresh=not stale_uids and not missing_uids and not future_uids and not scheduled_uids,
        stale_observation_uids=stale_uids,
        missing_timestamp_uids=missing_uids,
        future_timestamp_uids=future_uids,
        scheduled_recheck_uids=scheduled_uids,
    )


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()
