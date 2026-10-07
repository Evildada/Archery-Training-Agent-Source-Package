"""Append-only run events — the observability contract (docs/01 §8).

Every turn writes one JSONL line per event. This is what makes the harness debuggable
("why did it say that?") and what makes the eval suites possible later ("replay this turn and
compare"). Events are cheap; missing events are expensive.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventType(StrEnum):
    TURN_START = "turn_start"
    GUARD_BLOCK = "guard_block"
    CONTEXT_ASSEMBLED = "context_assembled"
    PLAN = "plan"
    TOOL_CALL = "tool_call"
    SENSOR_BLOCK = "sensor_block"
    REPAIR = "repair"
    BUDGET_HIT = "budget_hit"
    ANSWER_GATE = "answer_gate"
    INSIGHT_PERSISTED = "insight_persisted"
    TURN_END = "turn_end"


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    run_id: str
    event: EventType
    step: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class EventLog:
    """Keeps events in memory for the caller and appends them to disk when configured."""

    def __init__(self, path: Path | str | None = None, *, run_id: str = "run_local") -> None:
        self.run_id = run_id
        self.path = Path(path) if path is not None else None
        self.events: list[Event] = []
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: EventType, *, step: int | None = None, **data: Any) -> Event:
        record = Event(run_id=self.run_id, event=event, step=step, data=data)
        self.events.append(record)
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
        return record

    def by_type(self, event: EventType) -> tuple[Event, ...]:
        return tuple(e for e in self.events if e.event is event)

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for event in self.events:
            counts[event.event.value] = counts.get(event.event.value, 0) + 1
        return counts
