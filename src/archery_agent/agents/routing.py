"""Deterministic first-pass routing: the part of the decision that must never be left to a model.

The routing table in docs/02-agent-topology.md §1 is implemented here as plain code. The model
gets to *refine* a route at M3 — it does not get to notice a red flag, decide the sport is
compound, or choose whether a claim needs a citation. Those are safety properties, so they are
decided before the model sees anything.

Order matters and is deliberate: safety screen → discipline scope → intent → clarification.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from archery_agent.sensors.safety import screen_discipline, screen_message

#: Intent cues, most specific first. A message may match several; the union is dispatched.
_INTENT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "capture",
        (
            r"\b(i|we) (shot|scored|practi[cs]ed|did)\b",
            r"\bhere('| i)s my (score|end|card|breakdown)\b",
            r"\b\d{2,3}\b.{0,20}\b(card|round|dozen|ends?)\b",
        ),
    ),
    (
        "planner",
        (
            r"\b(plan|schedule|this week|next week|programme|program)\b",
            r"\bhow (often|many days|much) (should|do) i\b",
            r"\bgym\b|\bstrength (work|training)\b|\bsupport work\b",
        ),
    ),
    (
        "equip_tech",
        (
            r"\b(draw weight|limb|cam|module|ata|ibo)\b",
            r"\bspine|arrow|shaft|vane|fletch|nock|insert|point weight|grains?\b",
            r"\brelease[r]?\b|\btumbler\b|\btension\b.*\brelease",
            r"\bsight|pin|scope|peep\b",
            r"\btune|tear|paper turret|walk ?back|bare shaft\b",
        ),
    ),
    (
        "cycle_analyst",
        (
            r"\bgroup|spread|pattern|consistency|trend|improving|worse\b",
            r"\bwhy\b|\bwhat changed\b",
            r"\bform|cycle|hold|aim|follow[- ]?through|back tension\b",
        ),
    ),
    (
        "librarian",
        (
            r"\bresearch|study|studies|evidence|literature|science\b",
            r"\bwhat does (the )?(research|science|literature)\b",
            r"\bproven\b|\bis it true that\b",
        ),
    ),
)

_QUESTION_RE = re.compile(r"\b(how|what|why|when|should|does|do i|can i)\b", re.IGNORECASE)

#: A capture request writes to the ledger, so it needs the archer's approval before it lands.
_APPROVAL_ROUTES = frozenset({"capture"})


class RoutingDecision(BaseModel):
    """Where a message goes, and why. Logged on every turn (docs/01 §events)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    routes: tuple[str, ...]
    reason: str
    blocked: bool = False
    requires_approval: bool = False
    needs_clarification: bool = False
    safety_response: str | None = None
    out_of_scope_response: str | None = None


def _scoped_routes(text: str) -> tuple[str, ...]:
    matched: list[str] = []
    for route, patterns in _INTENT_PATTERNS:
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
            matched.append(route)
    return tuple(matched)


def route_message(text: str) -> RoutingDecision:
    """Route one archer message. Pure function — no model, no IO, no hidden state."""
    screen = screen_message(text)
    if screen.action == "refer":
        return RoutingDecision(
            routes=(),
            reason=f"safety screen matched {[c.value for c in screen.categories]}",
            blocked=True,
            safety_response=screen.response,
        )

    discipline = screen_discipline(text)
    if discipline.action != "proceed":
        return RoutingDecision(
            routes=(),
            reason="message is outside the compound-only scope of v1",
            blocked=True,
            out_of_scope_response=discipline.response,
        )

    if screen.action == "clarify":
        # The safety question is asked before any specialist runs: a pain question the archer has
        # not answered changes what the analysis should look at, so dispatching first would waste
        # the turn and could normalise an injury.
        return RoutingDecision(
            routes=(),
            reason=(
                f"safety question first: {[c.value for c in screen.categories]} "
                f"matched {list(screen.matched_terms)}; intent cues were "
                f"{list(_scoped_routes(text)) or 'absent'}"
            ),
            needs_clarification=True,
            safety_response=screen.response,
        )

    routes = _scoped_routes(text)
    if not routes:
        if _QUESTION_RE.search(text):
            # A question with no data context is a knowledge question, not a stats request.
            return RoutingDecision(
                routes=("librarian",),
                reason="question without ledger cues -> cited knowledge path",
            )
        return RoutingDecision(
            routes=(),
            reason="no intent matched; guessing a specialist would waste the turn",
            needs_clarification=True,
        )

    return RoutingDecision(
        routes=routes,
        reason=f"matched intent cues for {list(routes)}",
        requires_approval=bool(_APPROVAL_ROUTES.intersection(routes)),
    )
