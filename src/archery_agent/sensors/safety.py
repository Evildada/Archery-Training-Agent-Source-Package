"""Safety sensors: medical screening and discipline scope.

This is the highest-consequence module in the repository. Two facts shape it:

1. **A keyword screen is not a diagnosis.** It is deliberately over-inclusive, because the cost
   of asking a clarifying question is a slightly clumsier conversation, and the cost of missing
   a red flag is an injured archer. Every screen decision is logged so the error rate can be
   reviewed (docs/05 §4, the ratchet).
2. **The system never advises on injury.** Not "probably tendinitis", not "rest it for a week",
   not "you can train through it". It refers, names who to see, and offers the non-medical part
   of the job: keep the log, hold the plan, ask the coach.

An archer asking about pain is *not* doing something wrong, and the response is designed to keep
them talking to the system about everything else.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

REFERRAL_TEMPLATE = (
    "I can't help with that part, and I don't want to guess — what you're describing needs a "
    "person who can examine it.\n\n"
    "**Please talk to a medical professional** (a doctor or physiotherapist who works with "
    "archers if you can find one; your coach may know who the local archers use).\n\n"
    "What I can still do, and will happily do:\n"
    "• keep your log and your load history intact and readable for whoever you see;\n"
    "• put your training plan on hold so nothing in here pushes you to shoot through it;\n"
    "• record what you *can* do comfortably (blank-bale form work, blank-bale volume, gym) — "
    "if and only if a professional has cleared it;\n"
    "• track how you feel day to day, without interpreting it.\n\n"
    "If you're in immediate distress or severe pain, contact your local emergency number."
)

MENTAL_HEALTH_TEMPLATE = (
    "Thank you for telling me — that matters more than any training plan.\n\n"
    "I'm a training tool, and this is outside what I should be handling. Please talk to someone "
    "qualified and available to you: a doctor, a counsellor, a trusted adult, or a crisis line "
    "in your area.\n\n"
    "I'll keep your log tidy and I won't surface any training pressure while you sort this out."
)

SCOPE_TEMPLATE = (
    "I'm built for **compound** archery in this version, so I'd be guessing on that one — and a "
    "wrong guess about equipment or technique is worse than no answer.\n\n"
    "I can still help with the parts that transfer: training load, session structure, "
    "target-face geometry, scoring and statistics, and the sport-psychology side of routines."
)


class SafetyCategory(StrEnum):
    ACUTE_INJURY = "acute_injury"
    PAIN = "pain"
    NERVE = "nerve"
    SYSTEMIC = "systemic"
    MENTAL_HEALTH = "mental_health"
    DISORDERED_EATING = "disordered_eating"
    MEDICATION = "medication"
    MINOR_CONSENT = "minor_consent"


Action = Literal["proceed", "clarify", "refer"]


class SafetyScreen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action: Action = "proceed"
    categories: tuple[SafetyCategory, ...] = ()
    matched_terms: tuple[str, ...] = ()
    response: str = ""
    follow_up_question: str = ""
    log_note: str = ""


#: Patterns are intentionally broad. Order matters: the first matching *severity* wins.
_REFER_PATTERNS: tuple[tuple[SafetyCategory, tuple[str, ...], str], ...] = (
    (
        SafetyCategory.SYSTEMIC,
        (
            r"\bchest pain\b",
            r"\bcan'?t breathe\b",
            r"\bshort(ness)? of breath\b",
            r"\bdizz(y|iness)\b",
            r"\bfaint(ed|ing)?\b",
            r"\bblurred vision\b",
            r"\bblack(ed)? out\b",
            r"\bmigraine\b",
            r"\bconcussion\b",
            r"\bpassed out\b",
        ),
        REFERRAL_TEMPLATE,
    ),
    (
        SafetyCategory.NERVE,
        (
            r"\bnumb(ness)?\b",
            r"\btingl(ing|e)\b",
            r"pins and needles",
            r"\bcan'?t feel\b",
            r"\bloss of (feeling|sensation)\b",
            r"\bweak(ness)? in (my )?(hand|arm|grip)\b",
        ),
        REFERRAL_TEMPLATE,
    ),
    (
        SafetyCategory.MENTAL_HEALTH,
        (
            r"\bsuicid(e|al)\b",
            r"self[- ]harm",
            r"\bhurt myself\b",
            r"\bhopeless\b",
            r"\bcan'?t cope\b",
            r"\bpanic attack(s)?\b",
            r"\bdepress(ed|ion)\b",
            r"\bworthless\b",
        ),
        MENTAL_HEALTH_TEMPLATE,
    ),
    (
        SafetyCategory.DISORDERED_EATING,
        (
            r"\bcut(ting)? weight\b",
            r"\bmake weight\b",
            r"\bsauna (suit|to lose)\b",
            r"\bnot eating\b",
            r"\bstarv(ing|e)\b",
            r"\bpurge\b",
            r"\blaxative",
            r"\bcalorie deficit\b",
            r"\bdehydrat(e|ion) (to|for) weigh",
        ),
        REFERRAL_TEMPLATE,
    ),
    (
        SafetyCategory.ACUTE_INJURY,
        (
            r"\bpop(ped)?\b",
            r"\bsnap(ped)?\b",
            r"\btear\b",
            r"\btorn\b",
            r"\bruptur",
            r"\bdetached\b",
            r"\bfractur",
            r"\bdislocat",
            r"\bswell(ing|en)\b",
            r"\bcan'?t (lift|move|raise)\b",
            r"\bgiving way\b",
            r"\bwent out\b",
        ),
        REFERRAL_TEMPLATE,
    ),
    (
        SafetyCategory.MEDICATION,
        (
            r"\bibuprofen\b",
            r"\bparacetamol\b",
            r"\bacetaminophen\b",
            r"\bpain ?killers?\b",
            r"\banti[- ]inflammator",
            r"\bcortisone\b",
            r"\binjection\b",
            r"\bprescribed\b",
            r"\bmedication\b",
        ),
        REFERRAL_TEMPLATE,
    ),
)

_CLARIFY_PATTERNS: tuple[tuple[SafetyCategory, tuple[str, ...], str], ...] = (
    (
        SafetyCategory.PAIN,
        (
            r"\bpain(ful)?\b",
            r"\bhurt(s|ing)?\b",
            r"\bach(e|es|ed|y|ing)\b",
            r"\bsore\b",
            r"\bsoreness\b",
            r"\bstitch\b",
            r"\btwitch(ing)?\b",
            r"\bstrain(ed)?\b",
            r"\btendon",
        ),
        "Is this something you've had a professional look at, and are you currently cleared to "
        "keep shooting?",
    ),
)

_DISCIPLINE_PATTERNS: tuple[str, ...] = (
    r"\brecurve\b",
    r"\bolympic\b",
    r"\bbare ?bow\b",
    r"\blongbow\b",
    r"\btraditional\b",
    r"\bhorsebow\b",
    r"\bflatbow\b",
    r"\bkorea(n)? style\b",
)


def _matches(text: str, patterns: tuple[str, ...]) -> tuple[str, ...]:
    found = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            found.append(match.group(0))
    return tuple(dict.fromkeys(found))


def screen_message(text: str) -> SafetyScreen:
    """Run before anything else in a turn. Never skipped, never model-mediated."""
    for category, patterns, template in _REFER_PATTERNS:
        matched = _matches(text, patterns)
        if matched:
            return SafetyScreen(
                action="refer",
                categories=(category,),
                matched_terms=matched,
                response=template,
                log_note=(
                    f"safety screen: refer ({category.value}) on terms {list(matched)}. "
                    "If this is a false positive, add a fixture to evals/fixtures/red_team/ "
                    "so the pattern can be narrowed deliberately."
                ),
            )

    for category, patterns, question in _CLARIFY_PATTERNS:
        matched = _matches(text, patterns)
        if matched:
            return SafetyScreen(
                action="clarify",
                categories=(category,),
                matched_terms=matched,
                response=(
                    "Before we go into training: I don't assess or treat injuries, so I'll ask "
                    "one question and then we can get on with it."
                ),
                follow_up_question=question,
                log_note=f"safety screen: clarify ({category.value}) on terms {list(matched)}",
            )

    return SafetyScreen()


def screen_discipline(text: str) -> SafetyScreen:
    """Compound-only scope (AGENTS.md rule 1). Enforced here, not requested in a prompt."""
    matched = _matches(text, _DISCIPLINE_PATTERNS)
    if not matched:
        return SafetyScreen()
    return SafetyScreen(
        action="clarify",
        categories=(),
        matched_terms=matched,
        response=SCOPE_TEMPLATE,
        log_note=f"scope screen: non-compound discipline mentioned ({list(matched)})",
    )


class ScopeDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    in_scope: bool = True
    message: str = ""
    offered_alternatives: tuple[str, ...] = Field(default=())


def screen_scope_decision(text: str) -> ScopeDecision:
    """Boolean view of :func:`screen_discipline`, for routing tables."""
    screen = screen_discipline(text)
    return ScopeDecision(
        in_scope=screen.action == "proceed",
        message=screen.response,
        offered_alternatives=(
            "training load and session structure",
            "target-face geometry, scoring and statistics",
            "routine and competition-planning psychology",
        ),
    )
