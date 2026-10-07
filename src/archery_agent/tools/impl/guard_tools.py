"""``guard.*`` — safety and scope, callable as tools so every decision is logged.

Exposing the screens as *tools* rather than only as inline code has a specific benefit: the
decision appears in the run event log with its matched terms, so the false-positive rate of a
keyword screen can be measured and the patterns narrowed deliberately
(docs/05 §4, the ratchet).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from archery_agent.domain.enums import Confidence, RiskLevel
from archery_agent.sensors.safety import (
    screen_discipline,
    screen_message,
    screen_scope_decision,
)
from archery_agent.tools.registry import ToolContext, ToolResult, ToolSpec


class TextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000, description="The archer's own words.")


def _medical_screen(payload: BaseModel, ctx: ToolContext) -> ToolResult:
    assert isinstance(payload, TextInput)
    screen = screen_message(payload.text)
    return ToolResult.success(
        {
            "action": screen.action,
            "categories": [c.value for c in screen.categories],
            "matched_terms": list(screen.matched_terms),
            "response": screen.response,
            "follow_up_question": screen.follow_up_question,
            "log_note": screen.log_note,
        },
        confidence=Confidence.MEASURED,
        assumptions=(
            "keyword screen: deliberately over-inclusive, and not a clinical assessment",
            "action='refer' means stop the analysis and use the response verbatim; "
            "action='clarify' means ask the follow-up question once, then continue",
        ),
        snapshot_hash=ctx.data_snapshot_hash,
    )


def _discipline_scope(payload: BaseModel, ctx: ToolContext) -> ToolResult:
    assert isinstance(payload, TextInput)
    screen = screen_discipline(payload.text)
    decision = screen_scope_decision(payload.text)
    return ToolResult.success(
        {
            "in_scope": decision.in_scope,
            "response": decision.message,
            "matched_terms": list(screen.matched_terms),
            "offered_alternatives": list(decision.offered_alternatives),
            "log_note": screen.log_note,
        },
        confidence=Confidence.MEASURED,
        assumptions=("v1 models compound archery only (AGENTS.md rule 1)",),
        snapshot_hash=ctx.data_snapshot_hash,
    )


SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="guard.medical_screen",
        summary="Screen text for medical red flags. Run before any other routing; never skipped.",
        risk=RiskLevel.READ,
        input_model=TextInput,
        handler=_medical_screen,
        tags=("safety",),
    ),
    ToolSpec(
        name="guard.discipline_scope",
        summary="Check whether a request is inside the compound-only scope of this system.",
        risk=RiskLevel.READ,
        input_model=TextInput,
        handler=_discipline_scope,
        tags=("safety", "scope"),
    ),
)
