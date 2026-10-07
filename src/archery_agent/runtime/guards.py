"""Turn-level guards: preflight screening and the answer gate.

The answer gate is the harness's last line of defence and the second half of the ratchet: the
preflight screen stops the wrong questions from being answered at all, and the gate stops the
right questions from being answered with numbers nobody can trace.

Its most valuable check is **numeric grounding**. Every number in a user-facing answer must
appear in a tool result or be a declared structural constant. This is the deterministic,
model-free version of the eval metric that later gates the whole project
(``numeric_grounding = 1.00`` in docs/05 §3), and it catches the single most damaging failure
mode a coaching agent can have: a confident, plausible, invented figure.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from archery_agent.domain.insight import Claim, EvidenceRef
from archery_agent.sensors.citations import validate_claim_strength, validate_evidence_coverage
from archery_agent.sensors.safety import screen_discipline, screen_message
from archery_agent.sensors.validators import ValidationResult

#: Structural numbers that legitimately appear in archery prose without coming from a tool:
#: ring values, common distances, and small counts. Everything else must be traceable.
STRUCTURAL_NUMBERS: frozenset[float] = frozenset(
    {
        1.0,
        2.0,
        3.0,
        4.0,
        5.0,
        6.0,
        7.0,
        8.0,
        9.0,
        10.0,
        12.0,
        15.0,
        18.0,
        20.0,
        25.0,
        30.0,
        40.0,
        50.0,
        60.0,
        70.0,
        90.0,
        100.0,
        0.5,
        1.5,
        2.5,
    }
)

#: Extract numbers, including ones that end a sentence. The first version of this pattern used
#: `(?![\w.])`, which silently skipped every figure followed by a full stop — so
#: "Your score went from 561 to 587." passed the grounding gate with only 561 in evidence. A
#: single unsupported number is exactly what this gate exists to catch, so the pattern is now
#: pinned by two negative fixtures in evals/fixtures/numeric_grounding.jsonl (ground-008/010).
_NUMBER_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?!\d)")


class PreflightResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action: Literal["proceed", "clarify", "refer"]
    response: str = ""
    follow_up_question: str = ""
    notes: tuple[str, ...] = ()
    matched_terms: tuple[str, ...] = ()


def preflight(text: str) -> PreflightResult:
    """Safety first, then scope. Runs before any tool is available to the model."""
    medical = screen_message(text)
    if medical.action == "refer":
        return PreflightResult(
            action="refer",
            response=medical.response,
            notes=(medical.log_note,),
            matched_terms=medical.matched_terms,
        )

    discipline = screen_discipline(text)
    if discipline.action != "proceed":
        return PreflightResult(
            action="clarify",
            response=discipline.response,
            notes=(discipline.log_note,),
            matched_terms=discipline.matched_terms,
        )

    if medical.action == "clarify":
        return PreflightResult(
            action="clarify",
            response=medical.response,
            follow_up_question=medical.follow_up_question,
            notes=(medical.log_note,),
            matched_terms=medical.matched_terms,
        )

    return PreflightResult(action="proceed")


def extract_numbers(text: str) -> set[float]:
    return {float(match.group(1)) for match in _NUMBER_RE.finditer(text)}


def numeric_grounding_check(
    answer_text: str,
    tool_values: set[float],
    *,
    allowed: frozenset[float] = STRUCTURAL_NUMBERS,
    rel_tolerance: float = 0.02,
    label: str = "answer",
) -> ValidationResult:
    """Every non-structural number must be traceable to a tool result."""
    from archery_agent.sensors.validators import Issue, Severity

    candidates = sorted(extract_numbers(answer_text) - allowed)
    untraceable: list[float] = []
    for number in candidates:
        if 1900 <= number <= 2100:
            continue  # a year is not a measurement
        matched = any(
            abs(value - number) <= max(rel_tolerance * abs(value), 0.05) for value in tool_values
        )
        if not matched:
            untraceable.append(number)

    if not untraceable:
        return ValidationResult()

    return ValidationResult(
        issues=tuple(
            Issue(
                code="number_not_grounded",
                severity=Severity.ERROR,
                message=f"{label}: {number:g} does not appear in any tool result",
                field=label,
                suggestion=(
                    "Either call the tool that produces this number, or remove it. An untraceable "
                    "figure in a coaching answer is the most expensive kind of mistake this "
                    "system can make."
                ),
            )
            for number in untraceable
        )
    )


class GateResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    passed: bool
    failures: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    repair_hint: str = ""


class AnswerGate:
    """Deterministic verification of a candidate answer before it reaches the archer."""

    def __init__(self, *, strict_grounding: bool = True) -> None:
        self.strict_grounding = strict_grounding

    def check(
        self,
        *,
        answer_text: str,
        tool_values: set[float],
        claims: tuple[Claim, ...] = (),
        evidence_refs: tuple[EvidenceRef, ...] = (),
    ) -> GateResult:
        failures: list[str] = []
        warnings: list[str] = []

        grounding = numeric_grounding_check(answer_text, tool_values)
        if not grounding.ok:
            if self.strict_grounding:
                failures.extend(issue.message for issue in grounding.errors)
            else:
                warnings.extend(issue.message for issue in grounding.errors)

        if claims:
            coverage = validate_evidence_coverage(claims, evidence_refs)
            failures.extend(issue.message for issue in coverage.errors)
            for claim in claims:
                strength = validate_claim_strength(claim)
                failures.extend(issue.message for issue in strength.errors)
                warnings.extend(issue.message for issue in strength.warnings)

        passed = not failures
        hint = ""
        if not passed:
            hint = (
                "Rewrite the answer using only figures that appear in tool results, and attach "
                "evidence for any factual claim. If a number is genuinely needed and no tool "
                "produces it, say what is missing instead of estimating."
            )
        return GateResult(
            passed=passed, failures=tuple(failures), warnings=tuple(warnings), repair_hint=hint
        )


class TurnBudgetReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dimensions_hit: tuple[str, ...] = Field(default=())
    degraded: bool = False
