"""In-memory ledger used by the deterministic demo, the tests and the first CLI flows."""

from __future__ import annotations

import hashlib

from archery_agent.domain.ledger import ObservationBatch, ParameterObservation
from archery_agent.sensors.validators import validate_parameter_observation
from archery_agent.store.base import ObservationFilter


class InMemoryLedger:
    """Implements :class:`~archery_agent.store.base.LedgerStore`.

    Every append runs the same plausibility sensors as the SQLite implementation will, so the
    demo exercises the real write path rather than a shortcut.
    """

    def __init__(self) -> None:
        self._rows: list[ParameterObservation] = []

    def append(self, observations: tuple[ParameterObservation, ...]) -> ObservationBatch:
        accepted: list[ParameterObservation] = []
        rejected: list[dict[str, str]] = []
        warnings: list[str] = []

        for observation in observations:
            result = validate_parameter_observation(observation)
            if not result.ok:
                for issue in result.errors:
                    rejected.append(
                        {
                            "key": observation.key,
                            "value": str(observation.value),
                            "reason": issue.message,
                            "suggestion": issue.suggestion,
                        }
                    )
                continue
            warnings.extend(issue.message for issue in result.warnings)
            accepted.append(observation)

        self._rows.extend(accepted)
        return ObservationBatch(
            accepted=tuple(accepted),
            rejected=tuple(rejected),
            warnings=tuple(warnings),
        )

    def query(self, filt: ObservationFilter) -> tuple[ParameterObservation, ...]:
        rows = self._rows
        if filt.archer_id is not None:
            rows = [r for r in rows if r.archer_id == filt.archer_id]
        if filt.keys:
            rows = [r for r in rows if r.key in filt.keys]
        if filt.session_id is not None:
            rows = [r for r in rows if r.session_id == filt.session_id]
        if filt.end_id is not None:
            rows = [r for r in rows if r.end_id == filt.end_id]
        if filt.since is not None:
            rows = [r for r in rows if r.observed_at >= filt.since]
        if filt.until is not None:
            rows = [r for r in rows if r.observed_at <= filt.until]
        if filt.sources:
            rows = [r for r in rows if r.source in filt.sources]
        if filt.distance_m is not None:
            rows = [r for r in rows if r.distance_m == filt.distance_m]
        rows = sorted(rows, key=lambda r: r.observed_at)
        if filt.limit is not None:
            rows = rows[-filt.limit :]
        return tuple(rows)

    def series(self, key: str, *, archer_id: str | None = None) -> tuple[ParameterObservation, ...]:
        return self.query(ObservationFilter(keys=(key,), archer_id=archer_id))

    @property
    def size(self) -> int:
        return len(self._rows)

    def snapshot_hash(self) -> str:
        """Stable hash of the current ledger contents — stamped onto every generated insight.

        With this, an insight can always be traced back to the exact data it saw, even after
        hundreds of later sessions (AGENTS.md rule 8).
        """
        digest = hashlib.sha256()
        for row in sorted(self._rows, key=lambda r: (r.observed_at, r.observation_id)):
            digest.update(
                f"{row.observation_id}|{row.archer_id}|{row.key}|{row.value}|"
                f"{row.source.value}|{row.observed_at.isoformat()}\n".encode()
            )
        return f"sha256:{digest.hexdigest()[:32]}"
