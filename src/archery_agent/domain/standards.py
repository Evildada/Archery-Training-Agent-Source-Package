"""Standards and prescriptions.

The product's core promise (usage note 3 in the original brief) is that when an archer asks
*"what should I do?"*, the answer is **achievable and measurable**. That promise is encoded
here as types, not as a prompt instruction:

* a :class:`Standard` is only constructible if it names a registered metric, an operator, a
  threshold, a window and a minimum sample size — "work on your release" cannot be a Standard;
* a :class:`PracticeInstruction` is only constructible if it carries a dose and either a
  Standard or an inline criterion. A prescription with no dose is not a prescription.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from archery_agent.domain import parameters as registry
from archery_agent.domain.entities import utcnow
from archery_agent.domain.enums import SessionMode, StandardOperator
from archery_agent.domain.ids import new_id

EvalWindow = Literal["shot", "end", "session", "rolling_3_ends", "rolling_7d", "rolling_30d"]
Aggregation = Literal["mean", "median", "max", "min", "last", "sum", "count", "pct_pass"]


class Standard(BaseModel):
    """An executable definition of 'done well' for one metric, window and difficulty."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    standard_id: str = Field(default_factory=lambda: new_id("standard"))
    name: str = Field(min_length=1, max_length=120)
    owner: Literal["archer", "coach", "system"] = "system"
    owner_id: str | None = None

    metric_key: str
    aggregation: Aggregation = "mean"
    operator: StandardOperator
    threshold: float | None = None
    band_lo: float | None = None
    band_hi: float | None = None
    window: EvalWindow = "session"
    n_min: int = Field(default=6, ge=1, le=200)

    mode: SessionMode | None = None
    distance_m: float | None = Field(default=None, gt=0.0)
    target_face_id: str | None = None
    difficulty: Literal["foundation", "development", "competitive"] = "development"
    focus_tag: str | None = None
    drill_ref: str | None = None
    rationale: str = Field(
        default="",
        description="Where the number came from (archer's own distribution, coach's "
        "method, competition requirement).",
    )
    created_at: datetime = Field(default_factory=utcnow)
    active: bool = True

    @model_validator(mode="after")
    def _valid_metric(self) -> Standard:
        registry.get(self.metric_key)  # raises UnknownParameterError with suggestions
        return self

    @model_validator(mode="after")
    def _executable(self) -> Standard:
        problems = executability_problems(self)
        if problems:
            raise ValueError(
                "a standard must be executable — metric + operator + threshold + window + n_min. "
                "Problems: " + "; ".join(problems)
            )
        return self

    def describe(self) -> str:
        """Human-readable, and it always contains a number and a window by construction."""
        definition = registry.get(self.metric_key)
        unit = f" {definition.unit}" if definition.unit else ""
        window = self.window.replace("_", " ")
        agg = "" if self.aggregation == "mean" else f"{self.aggregation} of "
        if self.operator is StandardOperator.LTE:
            criterion = f"<= {self.threshold}{unit}"
        elif self.operator is StandardOperator.GTE:
            criterion = f">= {self.threshold}{unit}"
        elif self.operator is StandardOperator.IN_BAND:
            criterion = f"between {self.band_lo} and {self.band_hi}{unit}"
        else:
            criterion = f"inside {self.band_lo}-{self.band_hi}{unit} (equals band)"
        return f"{self.name}: {agg}{definition.label} {criterion} per {window} (n >= {self.n_min})"


def executability_problems(standard: Standard) -> list[str]:
    """Rules that make a standard checkable. Kept as a free function so sensors and CI can
    assert on drafts *before* construction (a rejected draft must explain itself)."""
    problems: list[str] = []
    if standard.operator in {StandardOperator.LTE, StandardOperator.GTE}:
        if standard.threshold is None:
            problems.append(f"operator '{standard.operator}' requires a threshold")
    else:
        if standard.band_lo is None or standard.band_hi is None:
            problems.append(f"operator '{standard.operator}' requires band_lo and band_hi")
        elif standard.band_lo >= standard.band_hi:
            problems.append("band_lo must be < band_hi")
    if standard.operator is StandardOperator.EQUALS_BAND and standard.threshold is not None:
        problems.append("equals_band expresses the target in band_lo/band_hi, not threshold")
    if standard.n_min < 1:
        problems.append("n_min must be >= 1 — a standard with no sample is not evaluable")
    if (
        standard.mode is SessionMode.BLANK_BALE
        and registry.get(standard.metric_key).category.value == "outcome"
    ):
        problems.append(
            "an outcome-metric standard cannot be evaluated on blank bale (nothing is scored)"
        )
    definition = registry.get(standard.metric_key)
    if definition.plausible_range is not None:
        lo, hi = definition.plausible_range
        for label, value in (
            ("threshold", standard.threshold),
            ("band_lo", standard.band_lo),
            ("band_hi", standard.band_hi),
        ):
            if value is not None and not (lo <= value <= hi):
                problems.append(
                    f"{label}={value} is outside the plausible range {lo}-{hi} for "
                    f"{standard.metric_key}; nobody is that good or that bad"
                )
    return problems


class StandardEvaluation(BaseModel):
    """The result of checking one standard against one window of the archer's data."""

    model_config = ConfigDict(extra="forbid")

    evaluation_id: str = Field(default_factory=lambda: new_id("evaluation"))
    standard_id: str
    session_id: str | None = None
    evaluated_at: datetime = Field(default_factory=utcnow)
    observed_value: float | None = None
    n: int = Field(default=0, ge=0)
    passed: bool | None = Field(
        default=None, description="None = not evaluable (insufficient n / missing data)."
    )
    reason: str = ""

    @property
    def evaluable(self) -> bool:
        return self.passed is not None


def evaluate_standard(
    standard: Standard,
    observed_value: float | None,
    n: int,
    *,
    session_id: str | None = None,
) -> StandardEvaluation:
    """Deterministic evaluation. No model, no heuristics, no partial credit."""
    if observed_value is None:
        return StandardEvaluation(
            standard_id=standard.standard_id,
            session_id=session_id,
            observed_value=None,
            n=n,
            passed=None,
            reason="no value produced for this window",
        )
    if n < standard.n_min:
        return StandardEvaluation(
            standard_id=standard.standard_id,
            session_id=session_id,
            observed_value=observed_value,
            n=n,
            passed=None,
            reason=f"n={n} below n_min={standard.n_min} — not evaluable, not a failure",
        )
    op = standard.operator
    if op is StandardOperator.LTE:
        passed = observed_value <= float(standard.threshold)  # type: ignore[arg-type]
    elif op is StandardOperator.GTE:
        passed = observed_value >= float(standard.threshold)  # type: ignore[arg-type]
    else:
        passed = float(standard.band_lo) <= observed_value <= float(standard.band_hi)  # type: ignore[arg-type]
    return StandardEvaluation(
        standard_id=standard.standard_id,
        session_id=session_id,
        observed_value=observed_value,
        n=n,
        passed=passed,
        reason=f"observed {observed_value:.2f} against {standard.describe()}",
    )


class Dose(BaseModel):
    """How much work. At least one dimension must be specified (checked by the instruction)."""

    model_config = ConfigDict(extra="forbid")

    arrows: int | None = Field(default=None, ge=1, le=600)
    ends: int | None = Field(default=None, ge=1, le=60)
    sets: int | None = Field(default=None, ge=1, le=30)
    reps: int | None = Field(default=None, ge=1, le=200)
    duration_min: int | None = Field(default=None, ge=1, le=240)

    @property
    def is_specified(self) -> bool:
        return any(
            v is not None for v in (self.arrows, self.ends, self.sets, self.reps, self.duration_min)
        )

    def describe(self) -> str:
        parts = []
        for label, value in (
            ("sets", self.sets),
            ("ends", self.ends),
            ("arrows", self.arrows),
            ("reps", self.reps),
        ):
            if value is not None:
                parts.append(f"{value} {label}")
        if self.duration_min is not None:
            parts.append(f"{self.duration_min} min")
        return " x ".join(parts)


class PracticeInstruction(BaseModel):
    """What the agent hands back when an archer asks 'what should I do?'

    Constructible only with a dose *and* a measurable criterion. This is the type-level
    enforcement of the brief's "achievable / measurable standard to practice".
    """

    model_config = ConfigDict(extra="forbid")

    instruction_id: str = Field(default_factory=lambda: new_id("standard"))
    title: str = Field(min_length=1, max_length=120)
    focus_tag: str | None = None
    mode: SessionMode | None = None
    distance_m: float | None = Field(default=None, gt=0.0)

    standard_id: str | None = None
    metric_key: str | None = None
    aggregation: Aggregation = "mean"
    operator: StandardOperator | None = None
    threshold: float | None = None
    band_lo: float | None = None
    band_hi: float | None = None
    window: EvalWindow | None = None
    n_min: Annotated[int, Field(ge=1, le=200)] | None = None

    dose: Dose
    execution_cue: str = ""
    drill_ref: str | None = None
    stop_rule: str = Field(
        default="", description="When to stop early, e.g. 'stop if grip pressure reaches 4'."
    )

    @model_validator(mode="after")
    def _measurable(self) -> PracticeInstruction:
        if not self.dose.is_specified:
            raise ValueError(
                "a prescription without a dose is not a prescription — set arrows/ends/sets/"
                "reps/duration_min"
            )
        if self.standard_id is None:
            missing = [
                name
                for name, value in (
                    ("metric_key", self.metric_key),
                    ("operator", self.operator),
                    ("window", self.window),
                    ("n_min", self.n_min),
                )
                if value is None
            ]
            if missing:
                raise ValueError(
                    "an instruction without a standard_id must carry an inline criterion; "
                    f"missing: {', '.join(missing)}"
                )
            if self.operator in {StandardOperator.LTE, StandardOperator.GTE}:
                if self.threshold is None:
                    raise ValueError(f"operator {self.operator} requires a threshold")
            elif self.band_lo is None or self.band_hi is None:
                raise ValueError(f"operator {self.operator} requires band_lo and band_hi")
            assert self.metric_key is not None
            registry.get(self.metric_key)
        return self

    def criterion_text(self) -> str:
        """The measurable part of the instruction, always numeric."""
        if self.standard_id is not None:
            return f"standard {self.standard_id}"
        definition = registry.get(str(self.metric_key))
        unit = f" {definition.unit}" if definition.unit else ""
        if self.operator is StandardOperator.LTE:
            return f"{definition.label} <= {self.threshold}{unit} per {self.window}"
        if self.operator is StandardOperator.GTE:
            return f"{definition.label} >= {self.threshold}{unit} per {self.window}"
        return f"{definition.label} within {self.band_lo}-{self.band_hi}{unit} per {self.window}"

    def describe(self) -> str:
        return f"{self.title}: {self.dose.describe()} — success = {self.criterion_text()}"
