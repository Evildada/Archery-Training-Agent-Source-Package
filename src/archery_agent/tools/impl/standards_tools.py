"""``standards.*`` — producing executable, *achievable* targets.

The distinguishing design decision: a suggested standard is derived from the archer's **own
distribution**, not from a table of what a good archer should do. A standard set at someone
else's level is not a standard; it is a reason to stop logging.

Concretely, a "just achievable" target is the value the archer already meets in roughly two
thirds of their sessions. That is hard enough to demand attention and easy enough to be
reachable on a bad day — and the rationale string records exactly how it was derived, so a coach
can override it with their own number and have the override be visible.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from archery_agent.domain import parameters as registry
from archery_agent.domain.enums import BetterDirection, Confidence, RiskLevel, SessionMode
from archery_agent.domain.standards import Dose, PracticeInstruction, Standard, evaluate_standard
from archery_agent.sensors.standards import validate_standard
from archery_agent.sensors.stats import percentile
from archery_agent.store.base import ObservationFilter
from archery_agent.tools.registry import ToolContext, ToolResult, ToolSpec

#: The pass-rate a fresh standard should sit at, expressed as a percentile of the archer's own
#: history. 0.65 means "they already meet it about two thirds of the time".
JUST_ACHIEVABLE_PASS_RATE: float = 0.65

MIN_OBSERVATIONS_FOR_SUGGESTION: int = 12


def _session_means(rows: tuple[object, ...]) -> list[float]:
    from collections import defaultdict

    from archery_agent.domain.ledger import ParameterObservation

    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if isinstance(row, ParameterObservation) and row.is_numeric and row.session_id:
            grouped[row.session_id].append(row.numeric())
    return [sum(v) / len(v) for _, v in sorted(grouped.items())]


class StandardSuggestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archer_id: str
    metric_key: str
    window_days: int = Field(default=90, ge=14, le=730)
    mode: SessionMode | None = None
    distance_m: float | None = Field(default=None, gt=0, le=100)
    name: str | None = Field(default=None, max_length=120)


def _standards_suggest(payload: BaseModel, ctx: ToolContext) -> ToolResult:
    assert isinstance(payload, StandardSuggestInput)
    if ctx.store is None:
        return ToolResult.failure("no ledger store is attached to this run")

    definition = registry.get(payload.metric_key)
    if definition.better is BetterDirection.NONE:
        return ToolResult.failure(
            f"{payload.metric_key} has no better-direction in the registry (it is descriptive "
            "rather than a target). A standard needs a direction: pick a metric where higher, "
            "lower, or a band is meaningful."
        )

    since = datetime.now(UTC) - timedelta(days=payload.window_days)
    rows = ctx.store.query(
        ObservationFilter(
            archer_id=payload.archer_id,
            keys=(payload.metric_key,),
            since=since,
            distance_m=payload.distance_m,
        )
    )
    values = _session_means(rows)
    if len(values) < MIN_OBSERVATIONS_FOR_SUGGESTION:
        return ToolResult.failure(
            f"only {len(values)} sessions with {payload.metric_key} in the last "
            f"{payload.window_days} days; a suggestion needs at least "
            f"{MIN_OBSERVATIONS_FOR_SUGGESTION} so it reflects this archer rather than a guess. "
            "Record a few more sessions, or set the target with the coach directly."
        )

    unit = f" {definition.unit}" if definition.unit else ""
    if definition.better is BetterDirection.LOWER:
        threshold = percentile(values, JUST_ACHIEVABLE_PASS_RATE * 100.0)
        operator_repr = "lte"
        band = None
    elif definition.better is BetterDirection.HIGHER:
        threshold = percentile(values, (1.0 - JUST_ACHIEVABLE_PASS_RATE) * 100.0)
        operator_repr = "gte"
        band = None
    else:
        threshold = None
        operator_repr = "in_band"
        band = (percentile(values, 25.0), percentile(values, 75.0))

    rationale = (
        f"derived from this archer's own last {len(values)} sessions "
        f"(p{int(JUST_ACHIEVABLE_PASS_RATE * 100)} of session means = "
        f"{threshold:.2f}{unit})"
        if threshold is not None
        else f"derived from this archer's own interquartile range over {len(values)} sessions"
    )

    data: dict[str, object] = {
        "metric_key": payload.metric_key,
        "metric_label": definition.label,
        "unit": definition.unit,
        "operator": operator_repr,
        "threshold": round(threshold, 3) if threshold is not None else None,
        "band": [round(band[0], 3), round(band[1], 3)] if band else None,
        "window": "session",
        "n_min": 6,
        "expected_pass_rate": JUST_ACHIEVABLE_PASS_RATE,
        "based_on_sessions": len(values),
        "observed_range": [round(min(values), 3), round(max(values), 3)],
        "rationale": rationale,
        "difficulty": "development",
    }
    return ToolResult.success(
        data,
        n=len(values),
        confidence=Confidence.DERIVED,
        units={payload.metric_key: definition.unit or ""},
        assumptions=(
            "the archer's recent distribution predicts their near-future performance "
            "(true over weeks, not over a season)",
            "session-level means, so intra-session variation is not represented",
        ),
        warnings=("present this as a starting point the archer can negotiate, not as a verdict",),
        snapshot_hash=ctx.store.snapshot_hash(),
    )


class StandardDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=3, max_length=120)
    metric_key: str
    operator: str = Field(description="lte | gte | in_band | equals_band")
    threshold: float | None = None
    band_lo: float | None = None
    band_hi: float | None = None
    window: str = Field(default="session", description="shot|end|session|rolling_3_ends|rolling_7d")
    n_min: int = Field(default=6, ge=1, le=200)
    difficulty: str = Field(default="development")
    focus_tag: str | None = None
    rationale: str = ""


def _standards_draft(payload: BaseModel, ctx: ToolContext) -> ToolResult:
    assert isinstance(payload, StandardDraftInput)
    from pydantic import ValidationError

    try:
        standard = Standard(
            name=payload.name,
            owner="archer",
            metric_key=payload.metric_key,
            operator=payload.operator,  # type: ignore[arg-type]
            threshold=payload.threshold,
            band_lo=payload.band_lo,
            band_hi=payload.band_hi,
            window=payload.window,  # type: ignore[arg-type]
            n_min=payload.n_min,
            difficulty=payload.difficulty,  # type: ignore[arg-type]
            focus_tag=payload.focus_tag,
            rationale=payload.rationale,
        )
    except ValidationError as exc:
        return ToolResult.failure(
            "this standard is not executable: "
            + "; ".join(error["msg"] for error in exc.errors()[:4])
            + ". Rewrite it with a metric, a comparison, a threshold, a window and n_min — "
            "otherwise the archer cannot score it at the end of a session."
        )

    validation = validate_standard(standard)
    return ToolResult.success(
        {
            "standard_id": standard.standard_id,
            "description": standard.describe(),
            "executable": True,
            "validation": validation.summary(),
            "issues": [i.message for i in validation.issues],
        },
        confidence=Confidence.MEASURED,
        warnings=tuple(i.message for i in validation.warnings),
        snapshot_hash=ctx.data_snapshot_hash,
    )


class StandardEvaluateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    standard_id: str
    metric_key: str
    operator: str
    threshold: float | None = None
    band_lo: float | None = None
    band_hi: float | None = None
    observed_value: float | None = None
    n: int = Field(default=0, ge=0)
    session_id: str | None = None


def _standards_evaluate(payload: BaseModel, ctx: ToolContext) -> ToolResult:
    assert isinstance(payload, StandardEvaluateInput)
    standard = Standard(
        name="inline",
        metric_key=payload.metric_key,
        operator=payload.operator,  # type: ignore[arg-type]
        threshold=payload.threshold,
        band_lo=payload.band_lo,
        band_hi=payload.band_hi,
        n_min=1,
    )
    standard = standard.model_copy(update={"standard_id": payload.standard_id})
    evaluation = evaluate_standard(
        standard, payload.observed_value, payload.n, session_id=payload.session_id
    )
    data = {
        "standard_id": evaluation.standard_id,
        "observed_value": evaluation.observed_value,
        "n": evaluation.n,
        "passed": evaluation.passed,
        "evaluable": evaluation.evaluable,
        "reason": evaluation.reason,
    }
    if not evaluation.evaluable:
        return ToolResult.failure(
            f"not evaluable: {evaluation.reason}. Do not report this as a failure — 'we do not "
            "know yet' and 'you missed it' are different messages."
        )
    return ToolResult.success(
        data,
        n=evaluation.n,
        confidence=Confidence.MEASURED,
        snapshot_hash=ctx.data_snapshot_hash,
    )


class InstructionDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=120)
    focus_tag: str | None = None
    mode: SessionMode | None = None
    distance_m: float | None = Field(default=None, gt=0, le=100)
    standard_id: str | None = None
    metric_key: str | None = None
    operator: str | None = None
    threshold: float | None = None
    band_lo: float | None = None
    band_hi: float | None = None
    window: str | None = None
    n_min: int | None = Field(default=None, ge=1, le=200)
    arrows: int | None = Field(default=None, ge=1, le=600)
    ends: int | None = Field(default=None, ge=1, le=60)
    sets: int | None = Field(default=None, ge=1, le=30)
    reps: int | None = Field(default=None, ge=1, le=200)
    duration_min: int | None = Field(default=None, ge=1, le=240)
    execution_cue: str = ""
    stop_rule: str = ""


def _instruction_draft(payload: BaseModel, ctx: ToolContext) -> ToolResult:
    assert isinstance(payload, InstructionDraftInput)
    from pydantic import ValidationError

    from archery_agent.sensors.standards import validate_instruction

    try:
        instruction = PracticeInstruction(
            title=payload.title,
            focus_tag=payload.focus_tag,
            mode=payload.mode,
            distance_m=payload.distance_m,
            standard_id=payload.standard_id,
            metric_key=payload.metric_key,
            operator=payload.operator,  # type: ignore[arg-type]
            threshold=payload.threshold,
            band_lo=payload.band_lo,
            band_hi=payload.band_hi,
            window=payload.window,  # type: ignore[arg-type]
            n_min=payload.n_min,
            dose=Dose(
                arrows=payload.arrows,
                ends=payload.ends,
                sets=payload.sets,
                reps=payload.reps,
                duration_min=payload.duration_min,
            ),
            execution_cue=payload.execution_cue,
            stop_rule=payload.stop_rule,
        )
    except ValidationError as exc:
        return ToolResult.failure(
            "this prescription is not executable: "
            + "; ".join(error["msg"] for error in exc.errors()[:4])
            + ". Add a dose (arrows/ends/sets/reps/minutes) and a measurable criterion."
        )

    validation = validate_instruction(instruction)
    if not validation.ok:
        return ToolResult.failure(
            "instruction failed the executability sensor: "
            + "; ".join(i.message for i in validation.errors)
        )
    return ToolResult.success(
        {"description": instruction.describe(), "issues": [i.message for i in validation.issues]},
        confidence=Confidence.MEASURED,
        warnings=tuple(i.message for i in validation.warnings),
        snapshot_hash=ctx.data_snapshot_hash,
    )


SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="standards.suggest",
        summary="Derive a just-achievable standard from the archer's own session distribution.",
        risk=RiskLevel.READ,
        input_model=StandardSuggestInput,
        handler=_standards_suggest,
        tags=("standards", "planning"),
    ),
    ToolSpec(
        name="standards.validate_draft",
        summary="Validate a proposed standard for executability and return it as a draft. "
        "Persisting it is a separate, approval-gated step (milestone M2).",
        risk=RiskLevel.READ,
        input_model=StandardDraftInput,
        handler=_standards_draft,
        tags=("standards",),
    ),
    ToolSpec(
        name="standards.evaluate",
        summary="Deterministically check one standard against an observed value and n.",
        risk=RiskLevel.READ,
        input_model=StandardEvaluateInput,
        handler=_standards_evaluate,
        tags=("standards",),
    ),
    ToolSpec(
        name="standards.validate_instruction",
        summary="Validate a practice prescription: it must carry a dose and a measurable "
        "criterion. Returns a draft; nothing is persisted.",
        risk=RiskLevel.READ,
        input_model=InstructionDraftInput,
        handler=_instruction_draft,
        tags=("standards", "planning"),
    ),
)
