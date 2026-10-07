"""The brief going down and the result coming back.

Both are typed. A subagent that cannot do its job returns ``status="insufficient"`` with the
missing inputs listed — it is not allowed to return a plausible-sounding guess, and the result
model refuses to let it: an ``insufficient`` result without ``missing`` fails validation.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentStatus(StrEnum):
    """How the subagent finished. Only ``OK`` may carry a usable answer."""

    OK = "ok"
    INSUFFICIENT = "insufficient"
    BLOCKED = "blocked"


class Brief(BaseModel):
    """Everything a subagent is told. Deliberately *not* the parent transcript."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task: str = Field(min_length=1)
    archer_id: str | None = None
    data_refs: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    output_schema: str = Field(min_length=1)

    def render(self) -> str:
        """Single-text form handed to a model at M3."""
        lines = [f"task: {self.task}"]
        if self.archer_id:
            lines.append(f"archer: {self.archer_id}")
        if self.data_refs:
            lines.append(f"data: {', '.join(self.data_refs)}")
        lines.append(f"must return: {self.output_schema}")
        for constraint in self.constraints:
            lines.append(f"constraint: {constraint}")
        return "\n".join(lines)


class AgentResult(BaseModel):
    """What a subagent must return. The shape is enforced, not requested."""

    model_config = ConfigDict(extra="forbid")

    status: AgentStatus
    summary: str = Field(min_length=1)
    structured: dict[str, Any] | None = None
    artifact_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    tool_calls: int = Field(default=0, ge=0)
    tokens: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _status_matches_payload(self) -> AgentResult:
        if self.status is AgentStatus.OK and self.structured is None:
            raise ValueError("an 'ok' result must carry structured output, not just a summary")
        if self.status is AgentStatus.INSUFFICIENT and not self.missing:
            raise ValueError(
                "an 'insufficient' result must name what is missing; 'I could not do it' is not "
                "an answer"
            )
        return self

    @property
    def usable(self) -> bool:
        return self.status is AgentStatus.OK
