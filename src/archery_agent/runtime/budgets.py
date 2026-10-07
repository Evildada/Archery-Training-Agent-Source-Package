"""Budgets and guards.

Budgets are not optimisations; they are the difference between a partial answer and a runaway
one. Hitting a budget is a **designed outcome** that produces an honest, incomplete answer —
never a silent truncation, and never an exception that loses the turn.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from archery_agent.domain.enums import RiskLevel


class Budget(BaseModel):
    """Starting values are documented in docs/01 §4 and are deliberately conservative."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_steps: int = Field(default=40, ge=1, le=200)
    max_tool_calls: int = Field(default=60, ge=1, le=400)
    max_tokens: int = Field(default=150_000, ge=1_000)
    max_repairs: int = Field(default=2, ge=0, le=5)
    max_write_drafts: int = Field(default=8, ge=0, le=50)


class BudgetUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: int = 0
    tool_calls: int = 0
    tokens: int = 0
    repairs: int = 0
    write_drafts: int = 0


class BudgetExceeded(RuntimeError):
    def __init__(self, dimension: str, usage: BudgetUsage, limit: int) -> None:
        super().__init__(
            f"budget exhausted: {dimension} ({getattr(usage, dimension)}/{limit}). "
            "Stop calling tools, summarise what has been established so far with its "
            "uncertainty, and state what is still missing. Do not attempt a workaround."
        )
        self.dimension = dimension


class BudgetGuard:
    """Counts usage and refuses further work once a dimension is exhausted."""

    def __init__(self, budget: Budget) -> None:
        self.budget = budget
        self.usage = BudgetUsage()
        self.hits: list[str] = []

    def _check(self, dimension: str, limit: int) -> None:
        if getattr(self.usage, dimension) >= limit and dimension not in self.hits:
            self.hits.append(dimension)

    def record_step(self) -> None:
        self.usage.steps += 1
        self._check("steps", self.budget.max_steps)

    def record_tool_call(self, risk: RiskLevel) -> None:
        self.usage.tool_calls += 1
        if risk is RiskLevel.WRITE_DRAFT:
            self.usage.write_drafts += 1
            self._check("write_drafts", self.budget.max_write_drafts)
        self._check("tool_calls", self.budget.max_tool_calls)

    def record_tokens(self, tokens: int) -> None:
        self.usage.tokens += max(0, tokens)
        self._check("tokens", self.budget.max_tokens)

    def record_repair(self) -> None:
        self.usage.repairs += 1
        self._check("repairs", self.budget.max_repairs)

    @property
    def exhausted(self) -> bool:
        return bool(self.hits)

    def enforce(self) -> None:
        """Raise if any budget dimension is exhausted. Called before each step."""
        for dimension, limit in (
            ("steps", self.budget.max_steps),
            ("tool_calls", self.budget.max_tool_calls),
            ("tokens", self.budget.max_tokens),
            ("repairs", self.budget.max_repairs),
            ("write_drafts", self.budget.max_write_drafts),
        ):
            if getattr(self.usage, dimension) < limit:
                continue
            if dimension not in self.hits:
                self.hits.append(dimension)
            raise BudgetExceeded(dimension, self.usage, limit)
