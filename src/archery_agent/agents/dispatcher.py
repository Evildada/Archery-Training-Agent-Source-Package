"""Dispatch a subagent, enforce its contract, and refuse anything that breaks it.

The dispatcher is the place where "the subagent cannot widen its own action space" stops being a
claim in a document and becomes a check in code:

* the brief must ask for exactly the contract's output shape;
* the runner is handed a registry restricted to the spec's allow-list — it never sees the full
  registry, so it cannot call what it should not;
* the result is validated against the spec, and a result that overspent its budget is refused
  rather than trimmed (trimming would hide the failure);
* a read-only specialist that somehow returns a write is caught by the read-only assertion.
"""

from __future__ import annotations

from typing import Any, Protocol

from archery_agent.agents.briefs import AgentResult, AgentStatus, Brief
from archery_agent.agents.specs import (
    READ_ONLY_SUBAGENTS,
    AgentSpec,
    UnknownSubagentError,
    spec_for,
)
from archery_agent.domain.enums import RiskLevel
from archery_agent.tools.builtin import build_registry, subagent_registry
from archery_agent.tools.registry import ToolContext, ToolRegistry


class BudgetExceededError(RuntimeError):
    """Raised when a subagent ships a result that costs more than its contract allows."""


class SubagentRunner(Protocol):
    """What a runner must do. Model-backed at M3; scripted in tests; absent before that."""

    def run(
        self, spec: AgentSpec, brief: Brief, tools: ToolRegistry, ctx: ToolContext
    ) -> AgentResult: ...


class Dispatcher:
    """The only path from the orchestrator to a specialist."""

    def __init__(self, runner: SubagentRunner) -> None:
        self._runner = runner

    def tools_for(self, name: str) -> ToolRegistry:
        """The restricted registry a subagent would receive. Exposed for tests and the doctor."""
        spec = spec_for(name)
        registry = subagent_registry(name)
        self._assert_read_only_if_required(spec, registry)
        return registry

    def dispatch(self, name: str, brief: Brief, ctx: ToolContext) -> AgentResult:
        spec = spec_for(name)
        if brief.output_schema != spec.output_contract:
            raise ValueError(
                f"brief for {name!r} asks for {brief.output_schema!r} but the contract is "
                f"{spec.output_contract!r}; a subagent must return what its contract promises, "
                "not what the caller improvised"
            )

        tools = self.tools_for(name)
        result = self._runner.run(spec, brief, tools, ctx)

        if result.tool_calls > spec.tool_budget or result.tokens > spec.token_budget:
            raise BudgetExceededError(
                f"{name} exceeded its contract: used {result.tool_calls} tool calls and "
                f"{result.tokens} tokens, allowed {spec.tool_budget} and {spec.token_budget}. "
                "The result is refused, not trimmed: a specialist that overspends is a loop bug, "
                "and hiding it would move the cost to the next turn."
            )
        if name in READ_ONLY_SUBAGENTS and result.artifact_refs:
            raise BudgetExceededError(
                f"{name} is read-only but returned artifact_refs {list(result.artifact_refs)}; "
                "read-only specialists must return their findings in structured output instead "
                "of writing artifacts"
            )
        return result

    @staticmethod
    def _assert_read_only_if_required(spec: AgentSpec, registry: ToolRegistry) -> None:
        if spec.name not in READ_ONLY_SUBAGENTS:
            return
        registered = set(registry.names())
        offenders = [
            tool
            for tool in spec.allowed_tools
            if tool in registered and registry.get(tool).risk is not RiskLevel.READ
        ]
        if offenders:
            raise ValueError(
                f"{spec.name} is declared read-only but holds non-read tools {offenders} — "
                "either move the tool's risk level or take it away from the specialist"
            )

    def denied_tools(self, name: str) -> tuple[str, ...]:
        """What a subagent wants but must not have. Used by the doctor to show the boundary."""
        spec = spec_for(name)
        return tuple(sorted(set(build_registry().names()) - set(spec.allowed_tools)))


class NullRunner:
    """The runner used when no model provider is configured (everything before M3).

    It refuses instead of pretending: a subagent's job is a judgement call, and this harness does
    not fake judgement calls with string templates.
    """

    def run(
        self, spec: AgentSpec, brief: Brief, _tools: ToolRegistry | None = None, _ctx: Any = None
    ) -> AgentResult:
        raise RuntimeError(
            f"{spec.name!r} was dispatched for {brief.task!r} but no model provider is "
            "configured. Configure one at M3 (docs/06-roadmap.md) or call a deterministic tool "
            "directly — do not emulate a specialist with a template."
        )


def blocked_result(reason: str) -> AgentResult:
    """A refusal a runner can return without pretending it did work."""
    return AgentResult(status=AgentStatus.BLOCKED, summary=reason, warnings=(reason,))


__all__ = [
    "BudgetExceededError",
    "Dispatcher",
    "NullRunner",
    "SubagentRunner",
    "UnknownSubagentError",
]
