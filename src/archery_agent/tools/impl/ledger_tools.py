"""``ledger.*`` and ``stats.*`` — reading and writing the parameter ledger.

The summary tools exist so the model never sees raw rows it could misread. ``stats.effects`` is
the tool that answers the brief's central question (*"can a set of parameters form a regression
that maintains stable position?"*) and the one most able to do harm, so it is explicit about the
unit of analysis and refuses to rank a parameter with too little paired data — returning the
refusal as data rather than as silence.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from archery_agent.domain import parameters as registry
from archery_agent.domain.enums import Confidence, ObservationSource, Reliability, RiskLevel
from archery_agent.domain.ledger import ParameterObservation
from archery_agent.sensors.stats import (
    MIN_SHOTS_FOR_EFFECT,
    claim_label_for,
    effects,
    ols_trend,
    summarise,
    trend_label_for,
)
from archery_agent.store.base import ObservationFilter
from archery_agent.tools.registry import ToolContext, ToolResult, ToolSpec

MAX_ROWS_PER_READ: int = 2000

#: Session-level analysis needs at least this many paired sessions before a slope is reported.
#: Higher than the shot threshold in unit count, lower in information — hence the separate label
#: function it is passed to.
MIN_SESSIONS_FOR_PAIRED_EFFECT: int = 12

Unit = Literal["shot", "session"]


class ObservationInput(BaseModel):
    """One row to append. Deliberately mirrors ParameterObservation minus ids/timestamps."""

    model_config = ConfigDict(extra="forbid")

    key: str
    value: float | int | bool | str
    source: ObservationSource = ObservationSource.SELF_REPORTED
    reliability: Reliability = Reliability.MEDIUM
    session_id: str | None = None
    end_id: str | None = None
    shot_id: str | None = None
    distance_m: float | None = Field(default=None, gt=0, le=100)
    target_face_id: str | None = None
    note: str = ""
    observed_at: datetime | None = None


class LedgerAppendInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archer_id: str
    observations: list[ObservationInput] = Field(min_length=1, max_length=500)


def _ledger_append(payload: BaseModel, ctx: ToolContext) -> ToolResult:
    assert isinstance(payload, LedgerAppendInput)
    if ctx.store is None:
        return ToolResult.failure("no ledger store is attached to this run")

    built: list[ParameterObservation] = []
    rejected: list[dict[str, str]] = []

    for index, item in enumerate(payload.observations):
        kwargs: dict[str, object] = {
            "archer_id": payload.archer_id,
            "key": item.key,
            "value": item.value,
            "source": item.source,
            "reliability": item.reliability,
            "session_id": item.session_id,
            "end_id": item.end_id,
            "shot_id": item.shot_id,
            "distance_m": item.distance_m,
            "target_face_id": item.target_face_id,
            "note": item.note,
        }
        if item.observed_at is not None:
            kwargs["observed_at"] = item.observed_at
        try:
            built.append(ParameterObservation.model_validate(kwargs))
        except ValidationError as exc:
            rejected.append(
                {
                    "index": str(index),
                    "key": item.key,
                    "reason": "; ".join(error["msg"] for error in exc.errors()[:3]),
                }
            )
        except KeyError as exc:  # unknown parameter key
            rejected.append({"index": str(index), "key": item.key, "reason": str(exc)})

    batch = ctx.store.append(tuple(built))
    rejected.extend(dict(row) for row in batch.rejected)

    if not batch.accepted:
        reasons = "; ".join(f"{r.get('key')}: {r.get('reason')}" for r in rejected[:8])
        return ToolResult.failure(
            "no observations were accepted. Reasons: "
            + reasons
            + ". Fix the values or ask the archer to re-check the measurement — do not resend "
            "the same payload."
        )

    return ToolResult.success(
        {
            "accepted": len(batch.accepted),
            "rejected": rejected,
            "sensor_warnings": list(batch.warnings),
            "snapshot_hash": ctx.store.snapshot_hash(),
        },
        n=len(batch.accepted),
        confidence=Confidence.MEASURED,
        warnings=(f"{len(rejected)} row(s) rejected — show the reasons to the archer",)
        if rejected
        else (),
        snapshot_hash=ctx.store.snapshot_hash(),
    )


class LedgerReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archer_id: str
    keys: list[str] = Field(default_factory=list, description="Empty = all parameters.")
    since: datetime | None = None
    until: datetime | None = None
    session_id: str | None = None
    limit: int = Field(default=200, ge=1, le=MAX_ROWS_PER_READ)


def _ledger_read(payload: BaseModel, ctx: ToolContext) -> ToolResult:
    assert isinstance(payload, LedgerReadInput)
    if ctx.store is None:
        return ToolResult.failure("no ledger store is attached to this run")
    rows = ctx.store.query(
        ObservationFilter(
            archer_id=payload.archer_id,
            keys=tuple(payload.keys),
            session_id=payload.session_id,
            since=payload.since,
            until=payload.until,
            limit=payload.limit,
        )
    )
    return ToolResult.success(
        {
            "count": len(rows),
            "rows": [
                {
                    "key": r.key,
                    "value": r.value,
                    "unit": r.unit,
                    "source": r.source.value,
                    "reliability": r.reliability.value,
                    "at": r.observed_at.isoformat(),
                    "session_id": r.session_id,
                    "shot_id": r.shot_id,
                }
                for r in rows
            ],
        },
        n=len(rows),
        warnings=("result truncated by limit — raise the limit or narrow the window",)
        if len(rows) >= payload.limit
        else (),
        snapshot_hash=ctx.store.snapshot_hash(),
    )


class LedgerSummaryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archer_id: str
    keys: list[str] = Field(min_length=1, max_length=12)
    window_days: int = Field(default=28, ge=1, le=365)


def _ledger_summary(payload: BaseModel, ctx: ToolContext) -> ToolResult:
    assert isinstance(payload, LedgerSummaryInput)
    if ctx.store is None:
        return ToolResult.failure("no ledger store is attached to this run")
    since = datetime.now(UTC) - timedelta(days=payload.window_days)

    summaries: dict[str, dict[str, object]] = {}
    low_reliability_keys: list[str] = []
    total_n = 0

    for key in payload.keys:
        definition = registry.get(key)
        rows = ctx.store.query(
            ObservationFilter(archer_id=payload.archer_id, keys=(key,), since=since)
        )
        numeric = [r.numeric() for r in rows if r.is_numeric]
        if numeric and any(r.reliability.value == "low" for r in rows):
            low_reliability_keys.append(key)
        summary = summarise(numeric, unit=definition.unit)
        total_n += summary.n
        summaries[key] = {
            "n": summary.n,
            "mean": round(summary.mean, 3) if summary.mean is not None else None,
            "sd": round(summary.sd, 3) if summary.sd is not None else None,
            "median": round(summary.median, 3) if summary.median is not None else None,
            "p10": round(summary.p10, 3) if summary.p10 is not None else None,
            "p90": round(summary.p90, 3) if summary.p90 is not None else None,
            "unit": definition.unit,
            "better_direction": definition.better.value,
            "target_band": list(definition.target_band) if definition.target_band else None,
        }

    warnings: list[str] = []
    if low_reliability_keys:
        warnings.append(
            "these summaries mix in self-reported values labelled low reliability: "
            + ", ".join(sorted(low_reliability_keys))
            + " — do not present them as measurements"
        )

    return ToolResult.success(
        {"window_days": payload.window_days, "summaries": summaries},
        n=total_n,
        confidence=Confidence.DERIVED,
        assumptions=(
            "aggregation is a plain mean over the window; no weighting for reliability",
            "values with reliability=low are included and flagged in warnings",
        ),
        warnings=tuple(warnings),
        snapshot_hash=ctx.store.snapshot_hash(),
    )


def _by_unit(rows: tuple[ParameterObservation, ...], unit: Unit) -> dict[str, float]:
    """Collapse numeric rows to one value per analysis unit. Rows without the unit id drop out."""
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if not row.is_numeric:
            continue
        unit_key = row.shot_id if unit == "shot" else row.session_id
        if unit_key is None:
            continue
        grouped[unit_key].append(row.numeric())
    return {key: sum(values) / len(values) for key, values in grouped.items()}


class StatsEffectsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archer_id: str
    outcome_key: str = Field(description="The dependent variable, e.g. 'outcome.score_mean'.")
    candidate_keys: list[str] = Field(min_length=1, max_length=20)
    window_days: int = Field(default=90, ge=7, le=730)
    unit: Literal["auto", "shot", "session"] = Field(
        default="auto",
        description="Analysis unit. 'shot' gives many more paired observations and a stronger "
        "claim; 'session' is a coarser fallback when shot ids are missing.",
    )


def _stats_effects(payload: BaseModel, ctx: ToolContext) -> ToolResult:
    assert isinstance(payload, StatsEffectsInput)
    if ctx.store is None:
        return ToolResult.failure("no ledger store is attached to this run")
    registry.get(payload.outcome_key)
    for key in payload.candidate_keys:
        registry.get(key)

    since = datetime.now(UTC) - timedelta(days=payload.window_days)

    def rows_for(key: str) -> tuple[ParameterObservation, ...]:
        return ctx.store.query(
            ObservationFilter(archer_id=payload.archer_id, keys=(key,), since=since)
        )

    outcome_rows = rows_for(payload.outcome_key)
    unit: Unit
    if payload.unit == "auto":
        unit = "shot" if any(r.shot_id for r in outcome_rows) else "session"
    else:
        unit = payload.unit

    outcome_by_unit = _by_unit(outcome_rows, unit)
    if len(outcome_by_unit) < 2:
        return ToolResult.failure(
            f"only {len(outcome_by_unit)} {unit}-level observations of {payload.outcome_key} in "
            f"the last {payload.window_days} days — there is nothing to regress yet. Say so "
            "plainly and propose which parameters to start recording."
        )

    candidate_maps = {key: _by_unit(rows_for(key), unit) for key in payload.candidate_keys}
    min_n = MIN_SHOTS_FOR_EFFECT if unit == "shot" else MIN_SESSIONS_FOR_PAIRED_EFFECT

    estimates = effects(
        outcome_key=payload.outcome_key,
        outcome_by_unit=outcome_by_unit,
        candidates=candidate_maps,
        min_n=min_n,
    )

    results: list[dict[str, object]] = []
    for est in estimates:
        label = (
            claim_label_for(n=est.n, q=est.q)
            if unit == "shot"
            else trend_label_for(n_sessions=est.n, q=est.q)
        )
        results.append(
            {
                "parameter": est.parameter_key,
                "n_paired": est.n,
                "r": round(est.r, 3) if est.r is not None else None,
                "q": round(est.q, 5) if est.q is not None else None,
                "ci_95": [round(est.ci_low, 3), round(est.ci_high, 3)]
                if est.ci_low is not None and est.ci_high is not None
                else None,
                "label": label.value,
                "caveats": list(est.caveats),
            }
        )

    excluded = {
        key: len(outcome_by_unit) - len(set(outcome_by_unit) & set(mapping))
        for key, mapping in candidate_maps.items()
    }
    warnings = ["association only — never present these as causes without a controlled change"]
    if unit == "session":
        warnings.append(
            "session-level analysis: fewer paired points and coarser measurement than shot level"
        )
    if not any(r["label"] in {"supported", "preliminary"} for r in results):
        warnings.append(
            "no parameter reached even a preliminary threshold — say so plainly and propose what "
            "to measure next, rather than presenting the least-bad correlation"
        )

    return ToolResult.success(
        {
            "analysis_unit": unit,
            "outcome_key": payload.outcome_key,
            "outcome_observations": len(outcome_by_unit),
            "min_pairs_required": min_n,
            "excluded_pairs": excluded,
            "results": results,
        },
        n=len(outcome_by_unit),
        confidence=Confidence.DERIVED,
        assumptions=(
            f"one value per {unit} (mean of repeats within the {unit})",
            "each candidate is paired with the outcome only on units where both exist",
            "Benjamini-Hochberg correction across the candidates in this call",
            "no confounder adjustment — equipment, distance and weather are not controlled",
        ),
        warnings=tuple(warnings),
        snapshot_hash=ctx.store.snapshot_hash(),
    )


class StatsTrendInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archer_id: str
    key: str
    window_days: int = Field(default=180, ge=7, le=1460)


def _stats_trend(payload: BaseModel, ctx: ToolContext) -> ToolResult:
    assert isinstance(payload, StatsTrendInput)
    if ctx.store is None:
        return ToolResult.failure("no ledger store is attached to this run")
    definition = registry.get(payload.key)
    since = datetime.now(UTC) - timedelta(days=payload.window_days)
    rows = ctx.store.query(
        ObservationFilter(archer_id=payload.archer_id, keys=(payload.key,), since=since)
    )

    by_session = _by_unit(rows, "session")
    if not by_session:
        return ToolResult.failure(
            f"{payload.key} has no session-tagged observations in the last "
            f"{payload.window_days} days — a trend needs repeated measurements"
        )

    session_means = [by_session[key] for key in sorted(by_session)]
    trend = ols_trend(session_means, unit=definition.unit or "")

    return ToolResult.success(
        {
            "key": payload.key,
            "sessions": len(session_means),
            "means": [round(v, 3) for v in session_means],
            "slope_per_session": round(trend.slope_per_session, 4)
            if trend.slope_per_session is not None
            else None,
            "ci_95": [round(trend.ci_low, 4), round(trend.ci_high, 4)]
            if trend.ci_low is not None and trend.ci_high is not None
            else None,
            "r2": round(trend.r2, 3) if trend.r2 is not None else None,
            "p": round(trend.p, 5) if trend.p is not None else None,
            "label": trend.label.value,
            "unit": definition.unit,
            "caveats": list(trend.caveats),
        },
        n=len(session_means),
        confidence=Confidence.DERIVED,
        warnings=("session-level means only — intra-session variation is not visible here",),
        snapshot_hash=ctx.store.snapshot_hash(),
    )


SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="ledger.append",
        summary="Validate and commit parameter observations. Rejected rows come back with "
        "reasons and suggestions.",
        risk=RiskLevel.WRITE_DRAFT,
        input_model=LedgerAppendInput,
        handler=_ledger_append,
        tags=("capture", "ledger"),
    ),
    ToolSpec(
        name="ledger.read",
        summary="Read raw ledger rows for a window (use sparingly; prefer ledger.summary).",
        risk=RiskLevel.READ,
        input_model=LedgerReadInput,
        handler=_ledger_read,
        tags=("ledger",),
    ),
    ToolSpec(
        name="ledger.summary",
        summary="Deterministic per-parameter summary (n, mean, sd, median, p10/p90, target band) "
        "over a window.",
        risk=RiskLevel.READ,
        input_model=LedgerSummaryInput,
        handler=_ledger_summary,
        tags=("ledger", "context"),
    ),
    ToolSpec(
        name="stats.effects",
        summary="Rank which recorded parameters move with an outcome, with n, r, corrected q and "
        "a confidence label. Refuses to rank insufficient data.",
        risk=RiskLevel.READ,
        input_model=StatsEffectsInput,
        handler=_stats_effects,
        tags=("analysis", "regression"),
    ),
    ToolSpec(
        name="stats.trend",
        summary="Least-squares trend of one parameter across sessions, with CI and a label.",
        risk=RiskLevel.READ,
        input_model=StatsTrendInput,
        handler=_stats_trend,
        tags=("analysis",),
    ),
)
