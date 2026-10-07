"""``sim.*`` — deterministic equipment and trajectory calculations.

The brief's arrow simulator, exposed as tools. Every handler returns the numbers *and* the
assumptions behind them, because an archer who cannot see the assumption cannot disagree with it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from archery_agent.domain.enums import RiskLevel
from archery_agent.sim.arrow import (
    ArrowBuild,
    ShotContext,
    evaluate_arrow_setup,
)
from archery_agent.sim.sights import SightMark, predict_sight_mark
from archery_agent.sim.spine import DEFAULT_SPINE_CHART, check_spine
from archery_agent.sim.tune import TuneSymptom, advise_tuning
from archery_agent.tools.registry import ToolContext, ToolResult, ToolSpec


class ArrowBuildInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand: str = ""
    model: str = ""
    shaft_length_in: float = Field(gt=0, le=34, description="Cut shaft length, inches.")
    shaft_mass_grains: float = Field(gt=0, description="Bare shaft mass in grains.")
    insert_mass_grains: float = Field(default=0, ge=0)
    point_mass_grains: float = Field(default=0, ge=0)
    nock_mass_grains: float = Field(default=0, ge=0)
    vane_mass_grains: float = Field(default=0, ge=0)
    measured_total_mass_grains: float | None = Field(
        default=None, gt=0, description="Weighed finished arrow — always preferred when present."
    )
    static_spine_thou: float | None = Field(default=None, gt=0)


class ArrowSetupInput(ArrowBuildInput):
    draw_weight_lb: float = Field(gt=0, le=100, description="Peak draw weight of the bow.")
    draw_length_in: float = Field(gt=0, le=35, description="Archer's draw length.")
    ibo_fps: float | None = Field(default=None, gt=0, le=400, description="Bow's IBO rating.")
    measured_speed_fps: float | None = Field(
        default=None, gt=0, le=400, description="Chronograph reading for this exact setup."
    )
    run_spine_check: bool = Field(default=True)


def _arrow_setup(payload: BaseModel, ctx: ToolContext) -> ToolResult:
    assert isinstance(payload, ArrowSetupInput)
    build = ArrowBuild(
        brand=payload.brand,
        model=payload.model,
        shaft_length_in=payload.shaft_length_in,
        shaft_mass_grains=payload.shaft_mass_grains,
        insert_mass_grains=payload.insert_mass_grains,
        point_mass_grains=payload.point_mass_grains,
        nock_mass_grains=payload.nock_mass_grains,
        vane_mass_grains=payload.vane_mass_grains,
        measured_total_mass_grains=payload.measured_total_mass_grains,
        static_spine_thou=payload.static_spine_thou,
    )
    context = ShotContext(
        draw_weight_lb=payload.draw_weight_lb,
        draw_length_in=payload.draw_length_in,
        ibo_fps=payload.ibo_fps,
        measured_speed_fps=payload.measured_speed_fps,
    )
    result = evaluate_arrow_setup(build, context)

    data: dict[str, object] = {
        "total_mass_grains": round(result.total_mass_grains, 1),
        "grains_per_pound": round(result.grains_per_pound, 2),
        "foc_pct": round(result.foc_pct, 2),
        "balance_point_in": round(result.balance_point_in, 2),
    }
    if result.speed_fps is not None:
        data["speed_fps"] = round(result.speed_fps, 1)
        data["speed_confidence"] = result.speed_confidence.value
        data["kinetic_energy_ft_lb"] = round(result.kinetic_energy_ft_lb or 0.0, 1)
        data["momentum_lb_s"] = round(result.momentum_lb_s or 0.0, 3)
    else:
        data["speed_fps"] = None
        data["speed_note"] = (
            "no chronograph reading and no IBO rating supplied — ask for one of the two"
        )

    warnings = list(result.warnings)
    if payload.run_spine_check and payload.static_spine_thou:
        check = check_spine(
            draw_weight_lb=payload.draw_weight_lb,
            arrow_length_in=payload.shaft_length_in,
            actual_spine_thou=payload.static_spine_thou,
            point_mass_grains=payload.point_mass_grains or 100.0,
        )
        data["spine"] = {
            "verdict": check.verdict,
            "actual_thou": check.actual_spine_thou,
            "recommended_thou": round(check.recommended_spine_thou, 0),
            "delta_thou": round(check.delta_thou, 0),
            "verification_step": check.verification_step,
        }
        warnings.extend(a for a in check.assumptions if "NOT SOURCED" in a)

    return ToolResult.success(
        data,
        confidence=result.speed_confidence,
        units={
            "total_mass_grains": "gr",
            "foc_pct": "%",
            "grains_per_pound": "gr/lb",
            "speed_fps": "fps",
            "kinetic_energy_ft_lb": "ft·lb",
        },
        assumptions=result.assumptions,
        warnings=tuple(warnings),
        snapshot_hash=ctx.data_snapshot_hash,
    )


class SpineCheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draw_weight_lb: float = Field(gt=0, le=100)
    arrow_length_in: float = Field(gt=0, le=34)
    actual_spine_thou: float = Field(gt=0)
    point_mass_grains: float = Field(default=100.0, gt=0)


def _spine_check(payload: BaseModel, ctx: ToolContext) -> ToolResult:
    assert isinstance(payload, SpineCheckInput)
    check = check_spine(
        draw_weight_lb=payload.draw_weight_lb,
        arrow_length_in=payload.arrow_length_in,
        actual_spine_thou=payload.actual_spine_thou,
        point_mass_grains=payload.point_mass_grains,
    )
    return ToolResult.success(
        {
            "verdict": check.verdict,
            "actual_spine_thou": check.actual_spine_thou,
            "recommended_spine_thou": round(check.recommended_spine_thou, 0),
            "delta_thou": round(check.delta_thou, 0),
            "registry_value": round(check.as_registry_value(), 0),
            "verification_step": check.verification_step,
        },
        confidence=check.confidence,
        units={"delta_thou": "thou"},
        assumptions=check.assumptions,
        warnings=("chart is not sourced — treat as a plausibility check, not tuning advice",)
        if not DEFAULT_SPINE_CHART.verified
        else (),
        snapshot_hash=ctx.data_snapshot_hash,
    )


class SightMarkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marks: list[tuple[float, float]] = Field(
        min_length=2,
        description="Measured [distance_m, sight_mark] pairs, at least two.",
    )
    target_distance_m: float = Field(gt=0, le=100)


def _sight_marks(payload: BaseModel, ctx: ToolContext) -> ToolResult:
    assert isinstance(payload, SightMarkInput)
    marks = [SightMark(distance_m=d, mark=m) for d, m in payload.marks]
    prediction = predict_sight_mark(marks, payload.target_distance_m)
    data = {
        "predicted_mark": (
            round(prediction.predicted_mark, 1) if prediction.predicted_mark is not None else None
        ),
        "method": prediction.method,
        "used_marks": [[m.distance_m, m.mark] for m in prediction.used_marks],
        "verification_step": prediction.verification_step,
    }
    if not prediction.ok:
        return ToolResult.failure(prediction.warning, warnings=(prediction.verification_step,))
    return ToolResult.success(
        data,
        confidence=prediction.confidence,
        assumptions=("linear behaviour between the bracketing marks",),
        warnings=(prediction.warning,) if prediction.warning else (),
        snapshot_hash=ctx.data_snapshot_hash,
    )


class TuneAdviceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symptom: TuneSymptom
    arrows_observed: int | None = Field(default=None, ge=0, le=200)
    group_radius_cm: float | None = Field(default=None, ge=0)
    distance_m: float | None = Field(default=None, gt=0, le=100)


def _tune_advice(payload: BaseModel, ctx: ToolContext) -> ToolResult:
    assert isinstance(payload, TuneAdviceInput)
    advice = advise_tuning(
        payload.symptom,
        arrows_observed=payload.arrows_observed,
        group_radius_cm=payload.group_radius_cm,
        distance_m=payload.distance_m,
    )
    if not advice.actionable:
        return ToolResult.failure(
            advice.blocked_by,
            warnings=(advice.verification_protocol,) if advice.verification_protocol else (),
        )
    return ToolResult.success(
        {
            "symptom": advice.symptom.value,
            "candidates": [
                {
                    "adjustment": c.adjustment,
                    "expected_effect": c.expected_effect,
                    "cost": c.cost,
                    "risk": c.risk,
                }
                for c in advice.candidates
            ],
            "verification_protocol": advice.verification_protocol,
        },
        confidence=advice.confidence,
        assumptions=advice.assumptions,
        snapshot_hash=ctx.data_snapshot_hash,
    )


SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="sim.arrow_setup",
        summary="Compute arrow mass, FOC, grains-per-pound, speed, KE and momentum for a build; "
        "optionally check spine coherence.",
        risk=RiskLevel.READ,
        input_model=ArrowSetupInput,
        handler=_arrow_setup,
        tags=("equipment", "simulator"),
        output_hint="object with mass/foc/speed/ke numbers plus assumption and confidence fields",
    ),
    ToolSpec(
        name="sim.spine_check",
        summary="Compare a shaft's static spine with the chart recommendation for this draw.",
        risk=RiskLevel.READ,
        input_model=SpineCheckInput,
        handler=_spine_check,
        tags=("equipment", "simulator"),
    ),
    ToolSpec(
        name="sim.sight_marks",
        summary="Predict a sight mark from measured marks (interpolation only; bounded "
        "extrapolation).",
        risk=RiskLevel.READ,
        input_model=SightMarkInput,
        handler=_sight_marks,
        tags=("equipment", "simulator"),
    ),
    ToolSpec(
        name="sim.tune_advisor",
        summary="Rank reversible tuning changes for a symptom — refuses to advise while the "
        "archer's own execution still dominates the spread.",
        risk=RiskLevel.READ,
        input_model=TuneAdviceInput,
        handler=_tune_advice,
        tags=("equipment", "simulator"),
    ),
)
