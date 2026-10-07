"""Per-subagent contracts: purpose, output shape, budget, and (by reference) action space."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from archery_agent.tools.builtin import SUBAGENT_TOOLS

#: Budgets from docs/02-agent-topology.md §2. A subagent gets its own context window, so the
#: budget is what keeps a specialist from fanning out into a generalist.
BUDGETS: dict[str, tuple[int, int]] = {
    # name: (tokens, tool calls)
    "orchestrator": (24_000, 24),
    "capture": (6_000, 10),
    "cycle_analyst": (8_000, 12),
    "equip_tech": (8_000, 12),
    "planner": (10_000, 16),
    "librarian": (8_000, 10),
    "verifier": (4_000, 4),
}

PURPOSES: dict[str, str] = {
    "orchestrator": "Own the turn: route, assemble context, dispatch specialists, answer.",
    "capture": "Convert messy practice narration into structured, source-tagged records.",
    "cycle_analyst": "Turn the parameter ledger into honest observations with evidence labels.",
    "equip_tech": "Bow, arrow and release reasoning, with assumptions and a required range test.",
    "planner": "Session and week planning that respects the load guardrail and the standards.",
    "librarian": "Cited research insight. No claim without an EvidenceRef.",
    "verifier": "Adversarial check of a candidate answer against rubrics and sensors.",
}

OUTPUT_CONTRACTS: dict[str, str] = {
    "orchestrator": "TurnResult",
    "capture": "SessionDraft[]",
    "cycle_analyst": "CycleObservation[]",
    "equip_tech": "Recommendation[]",
    "planner": "TrainingPlanDraft",
    "librarian": "EvidenceCard[]",
    "verifier": "Verdict",
}

#: Subagents that must never hold a tool that changes state or that spawns another agent.
READ_ONLY_SUBAGENTS: frozenset[str] = frozenset({"cycle_analyst", "equip_tech", "librarian"})


class AgentSpec(BaseModel):
    """What one specialist is allowed to be."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    purpose: str
    output_contract: str
    allowed_tools: tuple[str, ...] = Field(min_length=1)
    token_budget: int = Field(gt=0)
    tool_budget: int = Field(gt=0)

    def brief_line(self) -> str:
        """One line for the orchestrator's own context — the subagent's whole job description."""
        return (
            f"{self.name}: {self.purpose} Tools: {', '.join(self.allowed_tools)}. "
            f"Return {self.output_contract}."
        )


def _build() -> dict[str, AgentSpec]:
    specs: dict[str, AgentSpec] = {}
    for name, allowed in SUBAGENT_TOOLS.items():
        if name not in BUDGETS or name not in PURPOSES or name not in OUTPUT_CONTRACTS:
            raise KeyError(
                f"subagent {name!r} has an action space in tools/builtin.py but no contract in "
                "agents/specs.py — every subagent needs a purpose, an output contract and a "
                "budget before it may be dispatched."
            )
        tokens, calls = BUDGETS[name]
        specs[name] = AgentSpec(
            name=name,
            purpose=PURPOSES[name],
            output_contract=OUTPUT_CONTRACTS[name],
            allowed_tools=allowed,
            token_budget=tokens,
            tool_budget=calls,
        )
    missing = set(BUDGETS) - set(specs)
    if missing:
        raise KeyError(
            f"agent contracts declared for unknown subagents: {sorted(missing)} — "
            "add their action space to tools/builtin.py::SUBAGENT_TOOLS."
        )
    return specs


SPECS: dict[str, AgentSpec] = _build()


def spec_for(name: str) -> AgentSpec:
    """Look up a spec, or fail with the list of real names."""
    try:
        return SPECS[name]
    except KeyError:
        raise UnknownSubagentError(name) from None


class UnknownSubagentError(KeyError):
    """Raised when a dispatch names a subagent that has no contract."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"unknown subagent {name!r}; known subagents: {sorted(SPECS)}. "
            "A subagent without a contract has no budget and no output guarantee, so it is not "
            "dispatchable — add it to agents/specs.py and tools/builtin.py first."
        )
