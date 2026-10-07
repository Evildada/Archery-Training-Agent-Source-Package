"""Subagent definitions: what each specialist is for, what it may touch, and what it must return.

The action spaces themselves live in :mod:`archery_agent.tools.builtin` (``SUBAGENT_TOOLS``),
because the tool layer must not depend on this one. This module adds the *contract*: purpose,
output shape, and budget (docs/02-agent-topology.md §2).

Invariant enforced here and asserted in tests: a subagent's budget may not exceed what the
topology document promises, and no subagent may be given a write tool it should not have — the
verifier in particular is read-only, and no subagent may hold a tool that could spawn another.
"""

from __future__ import annotations

from archery_agent.agents.briefs import AgentResult, AgentStatus, Brief
from archery_agent.agents.dispatcher import (
    BudgetExceededError,
    Dispatcher,
    NullRunner,
    SubagentRunner,
    UnknownSubagentError,
)
from archery_agent.agents.routing import RoutingDecision, route_message
from archery_agent.agents.specs import SPECS, AgentSpec, spec_for

__all__ = [
    "SPECS",
    "AgentResult",
    "AgentSpec",
    "AgentStatus",
    "Brief",
    "BudgetExceededError",
    "Dispatcher",
    "NullRunner",
    "RoutingDecision",
    "SubagentRunner",
    "UnknownSubagentError",
    "route_message",
    "spec_for",
]
