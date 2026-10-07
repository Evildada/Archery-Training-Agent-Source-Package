"""Persistence. The only layer that touches a disk.

M0 ships an in-memory ledger that already enforces every T0/T1 sensor, so the rest of the system
can be built and tested against the real write path. SQLite lands at M1 behind the same
:class:`~archery_agent.store.base.LedgerStore` protocol — swapping it must not change a single
call site above this layer.
"""

from __future__ import annotations

from archery_agent.store.base import LedgerStore, ObservationFilter
from archery_agent.store.memory import InMemoryLedger

__all__ = ["InMemoryLedger", "LedgerStore", "ObservationFilter"]
