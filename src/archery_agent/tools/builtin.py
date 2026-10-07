"""Assemble the default tool registry.

Subagent views are built from this by :func:`build_registry` plus
``ToolRegistry.restrict_to`` — the dispatcher decides a subagent's action space, the subagent
cannot widen it.
"""

from __future__ import annotations

from archery_agent.domain.enums import RiskLevel
from archery_agent.tools.impl import (
    guard_tools,
    knowledge_tools,
    ledger_tools,
    sim_tools,
    standards_tools,
)
from archery_agent.tools.registry import ToolRegistry, ToolSpec

#: The ceiling of what exists at all. Anything not registered here does not exist for the model.
ALL_SPECS: tuple[ToolSpec, ...] = (
    *guard_tools.SPECS,
    *ledger_tools.SPECS,
    *sim_tools.SPECS,
    *standards_tools.SPECS,
    *knowledge_tools.SPECS,
)

#: Per-subagent action spaces (docs/02-agent-topology.md §2). Enforced by the dispatcher.
SUBAGENT_TOOLS: dict[str, tuple[str, ...]] = {
    "orchestrator": (
        "guard.medical_screen",
        "guard.discipline_scope",
        "ledger.summary",
        "ledger.read",
        "standards.suggest",
        "standards.evaluate",
    ),
    "capture": (
        "guard.medical_screen",
        "ledger.append",
        "ledger.summary",
    ),
    "cycle_analyst": (
        "ledger.read",
        "ledger.summary",
        "stats.effects",
        "stats.trend",
        "standards.evaluate",
    ),
    "equip_tech": (
        "sim.arrow_setup",
        "sim.spine_check",
        "sim.sight_marks",
        "sim.tune_advisor",
    ),
    "planner": (
        "ledger.summary",
        "stats.trend",
        "standards.suggest",
        "standards.validate_instruction",
    ),
    "librarian": ("knowledge.search",),
    "verifier": (
        "standards.evaluate",
        "ledger.summary",
    ),
}


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_all(ALL_SPECS)
    # Documented-but-unavailable capabilities: the model is told these exist and are denied, which
    # is more useful than pretending the harness cannot do them (docs/04 §9).
    registry.register(
        ToolSpec(
            name="raw.sql",
            summary="Direct database access. Permanently denied to the model layer.",
            risk=RiskLevel.DENY,
            input_model=type("Empty", (), {}),  # never constructed; kept for documentation
            handler=lambda *_: None,  # type: ignore[arg-type]
        )
    )
    registry.register(
        ToolSpec(
            name="record.delete",
            summary="Delete recorded data. Permanently denied; corrections are new rows, "
            "deletions are a human operation outside the agent.",
            risk=RiskLevel.DENY,
            input_model=type("Empty2", (), {}),
            handler=lambda *_: None,  # type: ignore[arg-type]
        )
    )
    return registry


def subagent_registry(name: str) -> ToolRegistry:
    """A restricted view for one subagent. Raises on an unknown subagent rather than guessing."""
    if name not in SUBAGENT_TOOLS:
        raise KeyError(
            f"unknown subagent {name!r}; known subagents: {sorted(SUBAGENT_TOOLS)}. "
            "Add the subagent and its tool allow-list to tools/builtin.py — a subagent without "
            "an explicit action space is a security hole, not a feature."
        )
    return build_registry().restrict_to(SUBAGENT_TOOLS[name])
