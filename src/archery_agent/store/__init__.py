"""Persistence. The only layer that touches a disk.

Two interchangeable implementations of :class:`~archery_agent.store.base.LedgerStore`:
:class:`~archery_agent.store.memory.InMemoryLedger` for the deterministic demo and the tests, and
:class:`~archery_agent.store.sqlite.SqliteStore` for real archers. They run the *same* sensors on
the write path, so a bug cannot hide in one of them.

The equipment history lives behind
:class:`~archery_agent.store.base.EquipmentStore`, and neither implementation exposes a way to
update or delete a recorded row — append-only is the storage contract, not an implementation
detail (see the SQLite triggers in ``store/sqlite.py``).
"""

from __future__ import annotations

from archery_agent.store.base import (
    EquipmentStore,
    LedgerStore,
    ObservationFilter,
)
from archery_agent.store.memory import InMemoryLedger
from archery_agent.store.sqlite import SqliteStore, append_only_probe

__all__ = [
    "EquipmentStore",
    "InMemoryLedger",
    "LedgerStore",
    "ObservationFilter",
    "SqliteStore",
    "append_only_probe",
]
