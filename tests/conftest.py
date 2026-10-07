"""Shared fixtures.

The synthetic ledger is the same one the demo uses, because it carries a *known ground truth*:
one real effect, one weak real effect, one decoy. Tests that assert on statistical behaviour use
it directly, so a change that makes the statistics tell a nicer story than the data supports will
fail here rather than in front of an archer.
"""

from __future__ import annotations

import pytest

from archery_agent.interfaces.demo import DEMO_ARCHER_ID, seed_demo_ledger
from archery_agent.store.memory import InMemoryLedger
from archery_agent.tools.builtin import build_registry
from archery_agent.tools.registry import ToolRegistry


@pytest.fixture
def ledger() -> InMemoryLedger:
    store = InMemoryLedger()
    seed_demo_ledger(store, archer_id=DEMO_ARCHER_ID, sessions=12, arrows_per_session=6)
    return store


@pytest.fixture
def empty_ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest.fixture
def registry() -> ToolRegistry:
    return build_registry()


@pytest.fixture
def archer_id() -> str:
    return DEMO_ARCHER_ID
