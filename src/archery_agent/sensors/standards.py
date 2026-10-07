"""Sensors for standards and prescriptions.

The brief asks for *"certain standard / executable measures ... in order to check a feasible
training mindset and method"*. Executability is therefore a sensor, not a writing style: a
prescription that cannot be scored by the archer at the end of the session is rejected here
rather than shipped with a friendly tone.
"""

from __future__ import annotations

import re

from archery_agent.domain.standards import PracticeInstruction, Standard, executability_problems
from archery_agent.sensors.validators import Issue, Severity, ValidationResult

#: A measurable criterion has a number and a comparison in it.
_NUMBER_RE = re.compile(r"\d")
_WINDOW_WORDS = ("per ", "each ", "over ", "/end", "window", "rolling", "per session")

MAX_INSTRUCTIONS_PER_SESSION: int = 3


def validate_standard(standard: Standard) -> ValidationResult:
    """Structural + executability checks, safe to run on drafts before construction."""
    issues: list[Issue] = []
    for problem in executability_problems(standard):
        issues.append(
            Issue(
                code="standard_not_executable",
                severity=Severity.ERROR,
                message=problem,
                field="standard",
                suggestion=(
                    "A standard needs a registered metric, an operator, a threshold or band, a "
                    "window and a minimum sample size. If it cannot be scored at the end of a "
                    "session, it is a goal, not a standard."
                ),
            )
        )
    if standard.n_min < 6 and standard.window in {"shot", "end"}:
        issues.append(
            Issue(
                code="standard_small_sample",
                severity=Severity.WARNING,
                message=f"n_min={standard.n_min} on a {standard.window}-level standard",
                field="n_min",
                suggestion=(
                    "Fewer than 6 arrows makes a pass/fail outcome closer to a coin toss than a "
                    "measurement of the session."
                ),
            )
        )
    if not standard.rationale:
        issues.append(
            Issue(
                code="standard_without_rationale",
                severity=Severity.INFO,
                message="no rationale recorded for this threshold",
                field="rationale",
                suggestion=(
                    "Record where the number came from (the archer's own distribution, the "
                    "coach's method, a competition requirement). Standards that appear from "
                    "nowhere are the ones archers quietly stop using."
                ),
            )
        )
    return ValidationResult(issues=tuple(issues))


def validate_instruction(instruction: PracticeInstruction) -> ValidationResult:
    """Is this prescription measurable, dosed, and small enough to be executed?"""
    issues: list[Issue] = []

    if not instruction.dose.is_specified:
        issues.append(
            Issue(
                code="instruction_without_dose",
                severity=Severity.ERROR,
                message="prescription has no dose",
                field="dose",
                suggestion="Give arrows/ends/sets/reps or minutes. 'Practise this' is not a dose.",
            )
        )

    criterion = instruction.criterion_text()
    if not _NUMBER_RE.search(criterion):
        issues.append(
            Issue(
                code="instruction_without_number",
                severity=Severity.ERROR,
                message=f"criterion contains no numeric threshold: {criterion!r}",
                field="threshold",
                suggestion=(
                    "Every instruction must contain a number the archer can check. "
                    "'Improve your release' is unmeasurable by construction."
                ),
            )
        )
    if not any(word in criterion.lower() for word in _WINDOW_WORDS):
        issues.append(
            Issue(
                code="instruction_without_window",
                severity=Severity.WARNING,
                message=f"criterion does not state a window: {criterion!r}",
                field="window",
                suggestion="State how often it must hold: per end, per session, over 3 ends.",
            )
        )
    if instruction.stop_rule and not _NUMBER_RE.search(instruction.stop_rule):
        issues.append(
            Issue(
                code="stop_rule_without_number",
                severity=Severity.WARNING,
                message=f"stop rule is not checkable: {instruction.stop_rule!r}",
                field="stop_rule",
                suggestion=(
                    "Make the stop condition numeric, e.g. 'stop if grip pressure reaches 4'."
                ),
            )
        )
    if (
        instruction.mode is not None
        and instruction.mode.value == "blank_bale"
        and (instruction.metric_key is not None and instruction.metric_key.startswith("outcome."))
    ):
        issues.append(
            Issue(
                code="scored_metric_on_blank_bale",
                severity=Severity.ERROR,
                message="a scored metric cannot be the criterion for a blank-bale block",
                field="metric_key",
                suggestion="Use a timing/tension/aim parameter for blank-bale work.",
            )
        )
    return ValidationResult(issues=tuple(issues))


def validate_session_plan(instructions: tuple[PracticeInstruction, ...]) -> ValidationResult:
    """Focus collapse is a real failure of generated training advice: five priorities is none."""
    issues: list[Issue] = []
    if len(instructions) > MAX_INSTRUCTIONS_PER_SESSION:
        issues.append(
            Issue(
                code="too_many_focus_points",
                severity=Severity.WARNING,
                message=f"{len(instructions)} instructions in one session plan",
                field="instructions",
                suggestion=(
                    f"A session teaches at most {MAX_INSTRUCTIONS_PER_SESSION} things well. "
                    "Move the rest to later sessions — this is the difference between a plan "
                    "and a wish list."
                ),
            )
        )
    tags = [i.focus_tag for i in instructions if i.focus_tag]
    duplicates = {tag for tag in tags if tags.count(tag) > 1}
    if duplicates:
        issues.append(
            Issue(
                code="duplicate_focus",
                severity=Severity.WARNING,
                message=f"the same focus appears twice: {sorted(duplicates)}",
                field="focus_tag",
                suggestion="Merge or delete the duplicate block.",
            )
        )
    return ValidationResult(issues=tuple(issues))
