"""Storage contracts.

The ledger is append-only by design. Nothing in this system mutates a recorded observation:
if a value was wrong, the correction is a *new* observation plus a note, because quietly
editing history would destroy the only property that makes a personal training log worth
keeping — that it can be trusted a year later.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from archery_agent.domain.enums import ObservationSource
from archery_agent.domain.ledger import ObservationBatch, ParameterObservation


class ObservationFilter(BaseModel):
    """Query for the ledger. Every field is optional; absent means 'do not filter'."""

    model_config = ConfigDict(extra="forbid")

    archer_id: str | None = None
    keys: tuple[str, ...] = ()
    session_id: str | None = None
    end_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    sources: tuple[ObservationSource, ...] = ()
    distance_m: float | None = None
    limit: int | None = None


@runtime_checkable
class LedgerStore(Protocol):
    """The write/read surface the agent is allowed to use."""

    def append(self, observations: tuple[ParameterObservation, ...]) -> ObservationBatch:
        """Validate against T0/T1 sensors, then commit the valid rows.

        Rejections are returned, never raised away: the capture flow has to be able to tell the
        archer *which* value was refused and why.
        """
        ...

    def query(self, filt: ObservationFilter) -> tuple[ParameterObservation, ...]: ...

    def series(self, key: str, *, archer_id: str | None = None) -> tuple[ParameterObservation, ...]:
        """All observations of one parameter, oldest first."""
        ...
