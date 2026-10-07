"""Lifecycle hooks — programmatic interception at fixed points.

Two rules keep hooks sane:

1. **Hooks may block, annotate or observe; they may not rewrite content silently.** A hook that
   quietly edits the model's output makes the system impossible to reason about.
2. **A hook failure is a harness failure, not a tool failure.** It is surfaced in the turn result
   rather than swallowed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class HookPhase(StrEnum):
    PRE_TOOL = "pre_tool"
    POST_TOOL = "post_tool"
    PRE_ANSWER = "pre_answer"
    PRE_PERSIST = "pre_persist"


@dataclass
class HookOutcome:
    block: bool = False
    reason: str = ""
    notes: list[str] = field(default_factory=list)

    def merge(self, other: HookOutcome) -> HookOutcome:
        return HookOutcome(
            block=self.block or other.block,
            reason=self.reason or other.reason,
            notes=[*self.notes, *other.notes],
        )


HookFn = Callable[[HookPhase, dict[str, Any]], HookOutcome]


class HookBus:
    """Ordered, deterministic hook execution."""

    def __init__(self) -> None:
        self._hooks: dict[HookPhase, list[tuple[str, HookFn]]] = {phase: [] for phase in HookPhase}

    def register(self, phase: HookPhase, name: str, fn: HookFn) -> None:
        self._hooks[phase].append((name, fn))

    def run(self, phase: HookPhase, payload: dict[str, Any]) -> HookOutcome:
        outcome = HookOutcome()
        for _name, fn in self._hooks[phase]:
            outcome = outcome.merge(fn(phase, payload))
        return outcome

    def registered(self) -> dict[str, tuple[str, ...]]:
        return {phase.value: tuple(name for name, _ in fns) for phase, fns in self._hooks.items()}


def default_hooks() -> HookBus:
    """The hooks the harness always installs. Adding one here is how a mistake becomes permanent
    (docs/05 §4)."""
    bus = HookBus()

    def refuse_unverified_numbers(_phase: HookPhase, payload: dict[str, Any]) -> HookOutcome:
        """Any tool result lacking an explicit confidence label is annotated, not trusted."""
        result = payload.get("result")
        if result is None or getattr(result, "confidence", None) is None:
            return HookOutcome(
                notes=[
                    "tool result reached the loop without a confidence label — treated as "
                    "INSUFFICIENT_DATA by the answer gate"
                ]
            )
        return HookOutcome()

    def flag_write_tools(_phase: HookPhase, payload: dict[str, Any]) -> HookOutcome:
        """Write drafts are logged with their arguments so an approval can be reviewed later."""
        spec = payload.get("spec")
        if spec is not None and getattr(spec, "requires_approval", False):
            return HookOutcome(
                notes=[f"approved write: {spec.name} args={payload.get('arguments', {})}"]
            )
        return HookOutcome()

    bus.register(HookPhase.POST_TOOL, "confidence_required", refuse_unverified_numbers)
    bus.register(HookPhase.PRE_TOOL, "log_write_approvals", flag_write_tools)
    return bus
