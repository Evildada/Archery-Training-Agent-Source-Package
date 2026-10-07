"""The runtime: the agent loop, context assembly, budgets, hooks, events and the model boundary.

This is the only layer allowed to talk to a model provider (`llm-isolation` contract), which is
what makes everything below it testable with no credentials and no network.
"""

from __future__ import annotations

from archery_agent.runtime.budgets import Budget, BudgetGuard, BudgetUsage
from archery_agent.runtime.context import AssembledContext, ContextSection, assemble_context
from archery_agent.runtime.events import Event, EventLog, EventType
from archery_agent.runtime.guards import AnswerGate, GateResult, PreflightResult, preflight
from archery_agent.runtime.hooks import HookBus, HookOutcome, HookPhase
from archery_agent.runtime.loop import CoachingLoop, PlannerDecision, ScriptedPlanner, TurnResult
from archery_agent.runtime.model_provider import (
    Message,
    ModelNotConfiguredError,
    ModelResponse,
    NullProvider,
)

__all__ = [
    "AnswerGate",
    "AssembledContext",
    "Budget",
    "BudgetGuard",
    "BudgetUsage",
    "CoachingLoop",
    "ContextSection",
    "Event",
    "EventLog",
    "EventType",
    "GateResult",
    "HookBus",
    "HookOutcome",
    "HookPhase",
    "Message",
    "ModelNotConfiguredError",
    "ModelResponse",
    "NullProvider",
    "PlannerDecision",
    "PreflightResult",
    "ScriptedPlanner",
    "TurnResult",
    "assemble_context",
    "preflight",
]
