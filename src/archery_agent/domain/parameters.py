"""The parameter registry — the vocabulary of the whole system.

This module is the answer to the original brief's *"Parameters affecting the shooting
cycle (maybe more)"*. "Maybe more" is handled by making the registry **versioned code**:
adding a parameter is a pull request that must declare a unit, a plausible range, how much
it costs the archer to capture, and which outcome it plausibly affects. That is what makes
the later regression (`docs/00-product-brief.md` S5) possible instead of aspirational.

Design rules encoded here:
* the unit lives in the key suffix (``cycle.hold_time_s``), and the registry asserts that the
  declared unit matches the suffix — a typo becomes an import error, not silent corruption;
* ordinal scales (1-5) must document what 1 and 5 mean, so "back tension 4" means the same
  thing in March and in August, and across two different coaches;
* ``plausible_range`` is a typo guard, not a performance judgement. It answers
  "is this physically possible?", never "is this good?".
"""

from __future__ import annotations

from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field, model_validator

from archery_agent.domain.enums import (
    BetterDirection,
    CaptureCost,
    ObservationSource,
    ParameterCategory,
    ParameterKind,
    Reliability,
)

#: The parameters the archer committed to recording **every session** (Q5, answered 2026-10-08:
#: "the recommended ten first, keep all 74 in the bank and review later"). Everything else stays
#: registered and queryable — it is simply not mandatory, and the capture UI must not ask for it
#: by default. ``SessionMode`` and distance are session fields, not registry parameters, so the
#: ten concepts land as eleven keys (the group centre is stored as an x/y pair).
CORE_PARAMETERS: tuple[str, ...] = (
    "outcome.score_mean",
    "outcome.group_center_x_cm",
    "outcome.group_center_y_cm",
    "load.arrows_shot",
    "env.distance_m",
    "load.rpe_1_10",
    "mental.readiness_1_10",
    "cycle.hold_time_s",
    "tension.grip_pressure_1_5",
    "aim.aim_float_radius_cm",
    "mental.routine_adherence_pct",
)

#: key suffix -> canonical unit. Longest match wins, so ``_lb_s`` beats ``_s``.
UNIT_SUFFIXES: dict[str, str] = {
    "_lb_reps": "lb·reps",
    "_lb_s": "lb·ft/s",
    "_ftlb": "ft·lb",
    "_1_10": "1-10",
    "_1_5": "1-5",
    "_pct": "%",
    "_fps": "fps",
    "_mps": "m/s",
    "_bpm": "bpm",
    "_thou": "thou",
    "_deg": "°",
    "_min": "min",
    "_cm": "cm",
    "_mm": "mm",
    "_grains": "gr",
    "_gr": "gr",
    "_lb": "lb",
    "_oz": "oz",
    "_in": "in",
    "_ms": "ms",
    "_kg": "kg",
    "_m": "m",
    "_s": "s",
    "_c": "°C",
}


class ParameterDefinition(BaseModel):
    """One row of the registry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*\.[a-z0-9_]+$")
    label: str
    category: ParameterCategory
    unit: str | None = None
    kind: ParameterKind
    scale_anchor: str | None = Field(
        default=None, description="For ordinals: what 1 and the top of the scale mean."
    )
    plausible_range: tuple[float, float] | None = Field(
        default=None, description="Physical plausibility (typo guard), never a quality judgement."
    )
    better: BetterDirection = BetterDirection.NONE
    target_band: tuple[float, float] | None = None
    capture_cost: CaptureCost = CaptureCost.LOW
    source_kinds: tuple[ObservationSource, ...] = (ObservationSource.SELF_REPORTED,)
    reliability_default: Reliability = Reliability.MEDIUM
    affects: tuple[str, ...] = ()
    notes: str = ""

    @model_validator(mode="after")
    def _check_internal_consistency(self) -> ParameterDefinition:
        suffix_unit = _unit_from_key(self.key)
        if self.unit is None and suffix_unit is not None:
            raise ValueError(
                f"{self.key!r} declares no unit but its suffix implies {suffix_unit!r}; "
                "either set unit= or rename the key"
            )
        if (
            self.unit is not None
            and suffix_unit != self.unit
            and self.kind is not ParameterKind.CATEGORICAL
        ):
            raise ValueError(
                f"{self.key!r} declares unit {self.unit!r} but the key suffix implies "
                f"{suffix_unit!r} — units must live in the key (AGENTS.md rule 6)"
            )
        if self.plausible_range is not None:
            lo, hi = self.plausible_range
            if lo >= hi:
                raise ValueError(
                    f"{self.key!r}: plausible_range must be (low, high) with low < high"
                )
        if self.better is BetterDirection.BAND and self.target_band is None:
            raise ValueError(f"{self.key!r}: better='band' requires a target_band")
        if self.target_band is not None and self.plausible_range is not None:
            lo, hi = self.plausible_range
            band_lo, band_hi = self.target_band
            if not (lo <= band_lo <= band_hi <= hi):
                raise ValueError(f"{self.key!r}: target_band must sit inside plausible_range")
        if self.kind is ParameterKind.ORDINAL and self.scale_anchor is None:
            raise ValueError(
                f"{self.key!r} is ordinal and must document its scale anchors (1 = ? / top = ?)"
            )
        return self


def _unit_from_key(key: str) -> str | None:
    """Longest known unit suffix of the key, or None."""
    for suffix in sorted(UNIT_SUFFIXES, key=len, reverse=True):
        if key.endswith(suffix):
            return UNIT_SUFFIXES[suffix]
    return None


def _p(
    key: str,
    label: str,
    category: ParameterCategory,
    unit: str | None,
    kind: ParameterKind,
    *,
    scale_anchor: str | None = None,
    plausible_range: tuple[float, float] | None = None,
    better: BetterDirection = BetterDirection.NONE,
    target_band: tuple[float, float] | None = None,
    capture_cost: CaptureCost = CaptureCost.LOW,
    source_kinds: tuple[ObservationSource, ...] = (ObservationSource.SELF_REPORTED,),
    reliability_default: Reliability = Reliability.MEDIUM,
    affects: tuple[str, ...] = (),
    notes: str = "",
) -> ParameterDefinition:
    """Terse constructor so the registry below reads like a table, not like code."""
    return ParameterDefinition(
        key=key,
        label=label,
        category=category,
        unit=unit,
        kind=kind,
        scale_anchor=scale_anchor,
        plausible_range=plausible_range,
        better=better,
        target_band=target_band,
        capture_cost=capture_cost,
        source_kinds=source_kinds,
        reliability_default=reliability_default,
        affects=affects,
        notes=notes,
    )


_SR = ObservationSource.SELF_REPORTED
_CR = ObservationSource.COACH_RATED
_SE = ObservationSource.SENSOR
_DV = ObservationSource.DERIVED

_DEFINITIONS: tuple[ParameterDefinition, ...] = (
    # ---------------------------------------------------------- anthropometric
    _p(
        "anthropometric.height_cm",
        "Height",
        ParameterCategory.ANTHROPOMETRIC,
        "cm",
        ParameterKind.RATIO,
        plausible_range=(100.0, 230.0),
        capture_cost=CaptureCost.FREE,
        notes="Reference value for draw-length sanity checks.",
    ),
    _p(
        "anthropometric.wingspan_cm",
        "Wingspan",
        ParameterCategory.ANTHROPOMETRIC,
        "cm",
        ParameterKind.RATIO,
        plausible_range=(120.0, 230.0),
        capture_cost=CaptureCost.LOW,
        notes="Wingspan/2.5 is a rough draw-length starting point, not a measurement.",
    ),
    _p(
        "anthropometric.draw_length_in",
        "Draw length",
        ParameterCategory.ANTHROPOMETRIC,
        "in",
        ParameterKind.RATIO,
        plausible_range=(15.0, 35.0),
        capture_cost=CaptureCost.LOW,
        source_kinds=(_CR, _SE, _SR),
        notes="Measured at full draw (ATA + 1.75 in is a common approximation).",
    ),
    # ------------------------------------------------------------- bow setup
    _p(
        "bow.draw_weight_lb",
        "Peak draw weight",
        ParameterCategory.BOW_SETUP,
        "lb",
        ParameterKind.RATIO,
        plausible_range=(10.0, 100.0),
        better=BetterDirection.BAND,
        target_band=(40.0, 70.0),
        capture_cost=CaptureCost.FREE,
        source_kinds=(_SR, _SE),
        affects=("outcome.score_mean", "arrow.speed_fps"),
        notes="Rule-of-thumb ranges only; the real band depends on the archer and the class.",
    ),
    _p(
        "bow.let_off_pct",
        "Let-off",
        ParameterCategory.BOW_SETUP,
        "%",
        ParameterKind.RATIO,
        plausible_range=(0.0, 90.0),
        better=BetterDirection.BAND,
        target_band=(65.0, 85.0),
        capture_cost=CaptureCost.FREE,
        affects=("cycle.hold_time_s", "cycle.expansion_time_s"),
        notes="Higher let-off eases hold; too soft a wall can encourage creep.",
    ),
    _p(
        "bow.axle_to_axle_in",
        "Axle to axle",
        ParameterCategory.BOW_SETUP,
        "in",
        ParameterKind.RATIO,
        plausible_range=(20.0, 45.0),
        capture_cost=CaptureCost.FREE,
        notes="Shorter bows are less forgiving of form variation; a real confounder.",
    ),
    _p(
        "bow.brace_height_in",
        "Brace height",
        ParameterCategory.BOW_SETUP,
        "in",
        ParameterKind.RATIO,
        plausible_range=(4.0, 9.0),
        capture_cost=CaptureCost.LOW,
        notes="Out-of-spec brace height invalidates scoring comparisons across sessions.",
    ),
    _p(
        "bow.bow_mass_oz",
        "Bow mass",
        ParameterCategory.BOW_SETUP,
        "oz",
        ParameterKind.RATIO,
        plausible_range=(30.0, 100.0),
        capture_cost=CaptureCost.LOW,
        notes="Affects hold stability and fatigue over a long session.",
    ),
    _p(
        "bow.cam_timing_offset_in",
        "Cam timing offset",
        ParameterCategory.BOW_SETUP,
        "in",
        ParameterKind.INTERVAL,
        plausible_range=(-1.0, 1.0),
        better=BetterDirection.BAND,
        target_band=(-0.06, 0.06),
        capture_cost=CaptureCost.MEDIUM,
        source_kinds=(_SE, _CR),
        affects=("outcome.group_center_x_cm", "outcome.group_center_y_cm"),
        notes="Out-of-sync cams show up as vertical or nock-travel oddities.",
    ),
    _p(
        "bow.wall_stiffness_1_5",
        "Wall stiffness",
        ParameterCategory.BOW_SETUP,
        "1-5",
        ParameterKind.ORDINAL,
        scale_anchor="1 = spongy, creeps through the wall; 5 = rock solid stop",
        plausible_range=(1.0, 5.0),
        better=BetterDirection.BAND,
        target_band=(3.0, 5.0),
        capture_cost=CaptureCost.FREE,
        source_kinds=(_SR,),
        affects=("tension.back_tension_1_5", "aim.aim_float_radius_cm"),
    ),
    # --------------------------------------------------------------- release
    _p(
        "release.sear_travel_1_5",
        "Sear travel",
        ParameterCategory.RELEASE,
        "1-5",
        ParameterKind.ORDINAL,
        scale_anchor="1 = hair trigger; 5 = long travel",
        plausible_range=(1.0, 5.0),
        better=BetterDirection.BAND,
        target_band=(2.0, 4.0),
        capture_cost=CaptureCost.FREE,
        source_kinds=(_SR,),
        affects=("cycle.release_latency_ms", "mental.target_panic_flag"),
        notes="Very short travel raises accidental-release and punch risk.",
    ),
    _p(
        "release.thumb_pressure_1_5",
        "Thumb pressure",
        ParameterCategory.RELEASE,
        "1-5",
        ParameterKind.ORDINAL,
        scale_anchor="1 = barely touching; 5 = pressing hard",
        plausible_range=(1.0, 5.0),
        better=BetterDirection.BAND,
        target_band=(1.0, 3.0),
        capture_cost=CaptureCost.LOW,
        source_kinds=(_SR, _CR),
        notes="Used as a cycle cue; consistency matters more than the absolute value.",
    ),
    _p(
        "release.punch_tendency_1_5",
        "Punch tendency (self-rated)",
        ParameterCategory.RELEASE,
        "1-5",
        ParameterKind.ORDINAL,
        scale_anchor="1 = never punch; 5 = often punch the trigger",
        plausible_range=(1.0, 5.0),
        better=BetterDirection.LOWER,
        capture_cost=CaptureCost.FREE,
        source_kinds=(_SR,),
        affects=("outcome.group_center_x_cm", "outcome.group_radius_cm"),
        notes="Self-rating is deliberately allowed to be subjective — it is a trend signal, "
        "not a measurement, and is labelled reliability=low.",
        reliability_default=Reliability.LOW,
    ),
    # ----------------------------------------------------------------- arrow
    _p(
        "arrow.total_mass_grains",
        "Total arrow mass",
        ParameterCategory.ARROW,
        "gr",
        ParameterKind.RATIO,
        plausible_range=(100.0, 800.0),
        better=BetterDirection.BAND,
        target_band=(300.0, 500.0),
        capture_cost=CaptureCost.LOW,
        source_kinds=(_SR, _SE),
        affects=("arrow.speed_fps", "arrow.ke_ftlb", "outcome.group_radius_cm"),
        notes="Weigh a finished arrow; catalog masses are usually optimistic.",
    ),
    _p(
        "arrow.shaft_length_in",
        "Shaft length",
        ParameterCategory.ARROW,
        "in",
        ParameterKind.RATIO,
        plausible_range=(15.0, 34.0),
        capture_cost=CaptureCost.LOW,
    ),
    _p(
        "arrow.static_spine_thou",
        "Static spine (deflection)",
        ParameterCategory.ARROW,
        "thou",
        ParameterKind.RATIO,
        plausible_range=(200.0, 1200.0),
        capture_cost=CaptureCost.MEDIUM,
        source_kinds=(_SR, _SE),
        notes="Deflection in thousandths of an inch (0.500 deflection = 500).",
    ),
    _p(
        "arrow.foc_pct",
        "Front of centre",
        ParameterCategory.ARROW,
        "%",
        ParameterKind.RATIO,
        plausible_range=(0.0, 30.0),
        better=BetterDirection.BAND,
        target_band=(8.0, 16.0),
        capture_cost=CaptureCost.MEDIUM,
        source_kinds=(_DV, _SR),
        affects=("outcome.group_radius_cm", "outcome.drop_cm"),
        notes="Derived from measured component masses (sim.arrow_setup), not estimated by eye.",
    ),
    _p(
        "arrow.point_mass_grains",
        "Point mass",
        ParameterCategory.ARROW,
        "gr",
        ParameterKind.RATIO,
        plausible_range=(50.0, 300.0),
        capture_cost=CaptureCost.LOW,
    ),
    _p(
        "arrow.fletch_angle_deg",
        "Fletching helical",
        ParameterCategory.ARROW,
        "°",
        ParameterKind.RATIO,
        plausible_range=(0.0, 12.0),
        capture_cost=CaptureCost.HIGH,
        notes="High-cost to measure; usually set once at build time and kept in equipment.",
    ),
    _p(
        "arrow.speed_fps",
        "Arrow speed",
        ParameterCategory.ARROW,
        "fps",
        ParameterKind.RATIO,
        plausible_range=(100.0, 400.0),
        capture_cost=CaptureCost.MEDIUM,
        source_kinds=(_SE, _DV),
        affects=("outcome.drop_cm", "outcome.score_mean"),
        notes="Measured with a chronograph (reliability high) or derived from sight marks "
        "(labelled INTERPOLATED and never used for a SUPPORTED claim).",
    ),
    _p(
        "arrow.ke_ftlb",
        "Kinetic energy",
        ParameterCategory.ARROW,
        "ft·lb",
        ParameterKind.RATIO,
        plausible_range=(10.0, 120.0),
        capture_cost=CaptureCost.FREE,
        source_kinds=(_DV,),
        notes="Derived in sim/, never computed by the model.",
    ),
    _p(
        "arrow.momentum_lb_s",
        "Momentum",
        ParameterCategory.ARROW,
        "lb·ft/s",
        ParameterKind.RATIO,
        plausible_range=(0.2, 2.0),
        capture_cost=CaptureCost.FREE,
        source_kinds=(_DV,),
        notes="Better penetration predictor than kinetic energy.",
    ),
    _p(
        "arrow.spine_fit_delta",
        "Spine fit delta",
        ParameterCategory.ARROW,
        None,
        ParameterKind.INTERVAL,
        plausible_range=(-500.0, 500.0),
        better=BetterDirection.BAND,
        target_band=(-150.0, 150.0),
        capture_cost=CaptureCost.FREE,
        source_kinds=(_DV,),
        affects=("outcome.group_center_x_cm",),
        notes="Signed agreement between the shaft's rated spine and the archer's draw "
        "(negative = stiffer than recommended). Derived by sim.spine_check; the shipped "
        "chart is a placeholder until a sourced chart is loaded.",
    ),
    _p(
        "arrow.bareshaft_tear_mm",
        "Bare-shaft tear",
        ParameterCategory.ARROW,
        "mm",
        ParameterKind.INTERVAL,
        plausible_range=(-100.0, 100.0),
        better=BetterDirection.BAND,
        target_band=(-6.0, 6.0),
        capture_cost=CaptureCost.MEDIUM,
        source_kinds=(_CR, _SR),
        affects=("outcome.group_center_x_cm",),
        notes="Signed: negative = nock left/tear left depending on convention - record which "
        "convention was used.",
    ),
    # ------------------------------------------------------------ cycle timing
    _p(
        "cycle.nock_to_release_s",
        "Whole-cycle tempo",
        ParameterCategory.CYCLE_TIMING,
        "s",
        ParameterKind.RATIO,
        plausible_range=(3.0, 60.0),
        better=BetterDirection.BAND,
        target_band=(8.0, 20.0),
        capture_cost=CaptureCost.LOW,
        source_kinds=(_SR, _CR, _SE),
        affects=("outcome.group_radius_cm",),
        notes="Nock on string to arrow impact. Faster is not better; consistent is better.",
    ),
    _p(
        "cycle.draw_time_s",
        "Draw time",
        ParameterCategory.CYCLE_TIMING,
        "s",
        ParameterKind.RATIO,
        plausible_range=(0.5, 15.0),
        better=BetterDirection.BAND,
        target_band=(2.0, 5.0),
        capture_cost=CaptureCost.LOW,
        source_kinds=(_SR, _CR, _SE),
        affects=("aim.aim_float_radius_cm",),
        notes="A rushed draw is a classic precursor to a rushed release.",
    ),
    _p(
        "cycle.hold_time_s",
        "Hold time",
        ParameterCategory.CYCLE_TIMING,
        "s",
        ParameterKind.RATIO,
        plausible_range=(0.2, 30.0),
        better=BetterDirection.BAND,
        target_band=(2.0, 5.0),
        capture_cost=CaptureCost.LOW,
        source_kinds=(_SR, _CR, _SE),
        affects=("outcome.group_radius_cm", "mental.target_panic_flag"),
        notes="The single most-cited compound lever in practice. Self-estimates are "
        "reliability=low; a stopwatch or shot timer upgrades them to medium.",
    ),
    _p(
        "cycle.expansion_time_s",
        "Expansion time",
        ParameterCategory.CYCLE_TIMING,
        "s",
        ParameterKind.RATIO,
        plausible_range=(0.2, 20.0),
        better=BetterDirection.BAND,
        target_band=(1.0, 4.0),
        capture_cost=CaptureCost.MEDIUM,
        source_kinds=(_SR, _CR),
        affects=("outcome.group_radius_cm",),
        notes="Time from aim settle to release; long expansion usually means hesitation.",
    ),
    _p(
        "cycle.aim_time_s",
        "Aim time",
        ParameterCategory.CYCLE_TIMING,
        "s",
        ParameterKind.RATIO,
        plausible_range=(0.2, 20.0),
        better=BetterDirection.BAND,
        target_band=(1.0, 5.0),
        capture_cost=CaptureCost.LOW,
        source_kinds=(_SR, _CR),
        affects=("aim.aim_float_radius_cm",),
    ),
    _p(
        "cycle.release_latency_ms",
        "Release latency",
        ParameterCategory.CYCLE_TIMING,
        "ms",
        ParameterKind.RATIO,
        plausible_range=(5.0, 2000.0),
        better=BetterDirection.LOWER,
        capture_cost=CaptureCost.HIGH,
        source_kinds=(_SE,),
        notes="Not measurable by hand; video/IMU only. Stored, but never a SUPPORTED claim "
        "until a real measurement source exists.",
        reliability_default=Reliability.LOW,
    ),
    _p(
        "cycle.follow_through_s",
        "Follow-through hold",
        ParameterCategory.CYCLE_TIMING,
        "s",
        ParameterKind.RATIO,
        plausible_range=(0.0, 20.0),
        better=BetterDirection.HIGHER,
        capture_cost=CaptureCost.MEDIUM,
        source_kinds=(_SR, _CR, _SE),
        notes="Time the archer stays still after the shot. Cheap proxy for commitment.",
    ),
    _p(
        "cycle.end_duration_s",
        "End duration",
        ParameterCategory.CYCLE_TIMING,
        "s",
        ParameterKind.RATIO,
        plausible_range=(20.0, 1800.0),
        better=BetterDirection.NONE,
        capture_cost=CaptureCost.FREE,
        source_kinds=(_DV, _SE),
        notes="Computed from shot timestamps when available.",
    ),
    # ----------------------------------------------------------- cycle tension
    _p(
        "tension.back_tension_1_5",
        "Back tension",
        ParameterCategory.CYCLE_TENSION,
        "1-5",
        ParameterKind.ORDINAL,
        scale_anchor="1 = no awareness of back engagement; 5 = continuous, unmistakable pull",
        plausible_range=(1.0, 5.0),
        better=BetterDirection.HIGHER,
        capture_cost=CaptureCost.LOW,
        source_kinds=(_SR, _CR),
        affects=("cycle.hold_time_s", "outcome.group_radius_cm"),
    ),
    _p(
        "tension.grip_pressure_1_5",
        "Bow-hand grip pressure",
        ParameterCategory.CYCLE_TENSION,
        "1-5",
        ParameterKind.ORDINAL,
        scale_anchor="1 = fingers barely closed, relaxed; 5 = tight, white-knuckle",
        plausible_range=(1.0, 5.0),
        better=BetterDirection.LOWER,
        capture_cost=CaptureCost.LOW,
        source_kinds=(_SR, _CR),
        affects=("outcome.group_center_x_cm",),
        notes="Over-grip is a common source of torque and left/right spread.",
    ),
    _p(
        "tension.anchor_pressure_1_5",
        "Anchor pressure",
        ParameterCategory.CYCLE_TENSION,
        "1-5",
        ParameterKind.ORDINAL,
        scale_anchor="1 = feather-light contact; 5 = hard pressure into the wall/face",
        plausible_range=(1.0, 5.0),
        better=BetterDirection.BAND,
        target_band=(2.0, 4.0),
        capture_cost=CaptureCost.LOW,
        source_kinds=(_SR, _CR),
        affects=("aim.aim_float_radius_cm",),
    ),
    _p(
        "tension.draw_smoothness_1_5",
        "Draw smoothness",
        ParameterCategory.CYCLE_TENSION,
        "1-5",
        ParameterKind.ORDINAL,
        scale_anchor="1 = jerky, stalling draw; 5 = one continuous, accelerating motion",
        plausible_range=(1.0, 5.0),
        better=BetterDirection.HIGHER,
        capture_cost=CaptureCost.LOW,
        source_kinds=(_SR, _CR),
        affects=("cycle.hold_time_s",),
    ),
    _p(
        "tension.shoulder_load_1_5",
        "Perceived shoulder load",
        ParameterCategory.CYCLE_TENSION,
        "1-5",
        ParameterKind.ORDINAL,
        scale_anchor="1 = effortless; 5 = near-maximal effort / discomfort",
        plausible_range=(1.0, 5.0),
        better=BetterDirection.LOWER,
        capture_cost=CaptureCost.FREE,
        source_kinds=(_SR,),
        notes="A *safety* input, not a performance one: sustained 4-5 feeds the load sensor and "
        "can trigger a rest recommendation. Never a diagnosis.",
    ),
    _p(
        "tension.wrist_relaxation_1_5",
        "Release-hand relaxation",
        ParameterCategory.CYCLE_TENSION,
        "1-5",
        ParameterKind.ORDINAL,
        scale_anchor="1 = tense, actively holding; 5 = fully relaxed throughout",
        plausible_range=(1.0, 5.0),
        better=BetterDirection.HIGHER,
        capture_cost=CaptureCost.LOW,
        source_kinds=(_SR, _CR),
        affects=("release.punch_tendency_1_5",),
    ),
    # ------------------------------------------------------------------- aim
    _p(
        "aim.aim_float_radius_cm",
        "Aim float radius",
        ParameterCategory.AIM,
        "cm",
        ParameterKind.RATIO,
        plausible_range=(0.0, 60.0),
        better=BetterDirection.LOWER,
        capture_cost=CaptureCost.MEDIUM,
        source_kinds=(_SR, _CR, _SE),
        affects=("outcome.group_radius_cm",),
        notes="Estimated at the target face from scope-ring fill; label the estimate source.",
    ),
    _p(
        "aim.aim_settle_s",
        "Time to settle",
        ParameterCategory.AIM,
        "s",
        ParameterKind.RATIO,
        plausible_range=(0.1, 15.0),
        better=BetterDirection.LOWER,
        capture_cost=CaptureCost.MEDIUM,
        source_kinds=(_SR, _CR, _SE),
        affects=("cycle.hold_time_s",),
    ),
    _p(
        "aim.scope_ring_fill_pct",
        "Scope ring fill",
        ParameterCategory.AIM,
        "%",
        ParameterKind.RATIO,
        plausible_range=(0.0, 100.0),
        better=BetterDirection.BAND,
        target_band=(50.0, 90.0),
        capture_cost=CaptureCost.LOW,
        source_kinds=(_CR, _SE),
        notes="How much of the scope housing the target fills; a proxy for float magnitude.",
    ),
    _p(
        "aim.float_consistency_1_5",
        "Float consistency",
        ParameterCategory.AIM,
        "1-5",
        ParameterKind.ORDINAL,
        scale_anchor="1 = float pattern differs every shot; 5 = repeatable signature",
        plausible_range=(1.0, 5.0),
        better=BetterDirection.HIGHER,
        capture_cost=CaptureCost.MEDIUM,
        source_kinds=(_SR, _CR),
    ),
    # ---------------------------------------------------------------- mental
    _p(
        "mental.arousal_1_10",
        "Arousal",
        ParameterCategory.MENTAL,
        "1-10",
        ParameterKind.ORDINAL,
        scale_anchor="1 = flat, sleepy; 10 = over-activated, shaky",
        plausible_range=(1.0, 10.0),
        better=BetterDirection.BAND,
        target_band=(4.0, 7.0),
        capture_cost=CaptureCost.FREE,
        source_kinds=(_SR,),
        affects=("outcome.score_mean", "cycle.hold_time_s"),
    ),
    _p(
        "mental.readiness_1_10",
        "Readiness",
        ParameterCategory.MENTAL,
        "1-10",
        ParameterKind.ORDINAL,
        scale_anchor="1 = not fit to shoot well today; 10 = fresh and confident",
        plausible_range=(1.0, 10.0),
        better=BetterDirection.HIGHER,
        capture_cost=CaptureCost.FREE,
        source_kinds=(_SR,),
        affects=("outcome.score_mean",),
    ),
    _p(
        "mental.focus_quality_1_5",
        "Focus quality",
        ParameterCategory.MENTAL,
        "1-5",
        ParameterKind.ORDINAL,
        scale_anchor="1 = distracted, mind elsewhere; 5 = locked on the process",
        plausible_range=(1.0, 5.0),
        better=BetterDirection.HIGHER,
        capture_cost=CaptureCost.FREE,
        source_kinds=(_SR, _CR),
    ),
    _p(
        "mental.routine_adherence_pct",
        "Routine adherence",
        ParameterCategory.MENTAL,
        "%",
        ParameterKind.RATIO,
        plausible_range=(0.0, 100.0),
        better=BetterDirection.HIGHER,
        capture_cost=CaptureCost.LOW,
        source_kinds=(_SR, _CR),
        affects=("outcome.group_radius_cm", "outcome.score_mean"),
        notes="Percentage of shots where the full pre-shot routine was executed. "
        "The cheapest high-signal mental metric that exists.",
    ),
    _p(
        "mental.target_panic_flag",
        "Target-panic flag",
        ParameterCategory.MENTAL,
        None,
        ParameterKind.BOOLEAN,
        capture_cost=CaptureCost.FREE,
        source_kinds=(_SR, _CR),
        notes="Triggers a *drill pathway*, never a diagnosis or a clinical claim.",
    ),
    _p(
        "mental.confidence_1_5",
        "Confidence",
        ParameterCategory.MENTAL,
        "1-5",
        ParameterKind.ORDINAL,
        scale_anchor="1 = no belief in the shot; 5 = fully committed",
        plausible_range=(1.0, 5.0),
        better=BetterDirection.HIGHER,
        capture_cost=CaptureCost.FREE,
        source_kinds=(_SR,),
    ),
    _p(
        "mental.pressure_sim_quality_1_5",
        "Pressure realism",
        ParameterCategory.MENTAL,
        "1-5",
        ParameterKind.ORDINAL,
        scale_anchor="1 = casual practice, no stakes; 5 = genuine competition stress",
        plausible_range=(1.0, 5.0),
        better=BetterDirection.HIGHER,
        capture_cost=CaptureCost.LOW,
        source_kinds=(_SR, _CR),
        affects=("outcome.score_mean",),
        notes="A scoring session at 25 m with no consequence is not competition practice.",
    ),
    _p(
        "mental.self_talk_quality_1_5",
        "Self-talk quality",
        ParameterCategory.MENTAL,
        "1-5",
        ParameterKind.ORDINAL,
        scale_anchor="1 = self-critical, outcome-focused; 5 = neutral, process-focused",
        plausible_range=(1.0, 5.0),
        better=BetterDirection.HIGHER,
        capture_cost=CaptureCost.LOW,
        source_kinds=(_SR, _CR),
    ),
    # --------------------------------------------------------------- outcome
    _p(
        "outcome.score_total",
        "Total score",
        ParameterCategory.OUTCOME,
        None,
        ParameterKind.COUNT,
        plausible_range=(0.0, 1800.0),
        better=BetterDirection.HIGHER,
        capture_cost=CaptureCost.FREE,
        source_kinds=(_SR, _DV),
        notes="Interpretation depends on the round; always record the round with it.",
    ),
    _p(
        "outcome.score_mean",
        "Mean arrow score",
        ParameterCategory.OUTCOME,
        None,
        ParameterKind.RATIO,
        plausible_range=(0.0, 10.0),
        better=BetterDirection.HIGHER,
        capture_cost=CaptureCost.FREE,
        source_kinds=(_DV, _SR),
        notes="Preferred over total score for comparisons: it is per-arrow, so arrow count "
        "cannot masquerade as improvement.",
    ),
    _p(
        "outcome.x_count",
        "Inner-10 count",
        ParameterCategory.OUTCOME,
        None,
        ParameterKind.COUNT,
        plausible_range=(0.0, 200.0),
        better=BetterDirection.HIGHER,
        capture_cost=CaptureCost.FREE,
        source_kinds=(_SR, _DV),
    ),
    _p(
        "outcome.group_radius_cm",
        "Group radius",
        ParameterCategory.OUTCOME,
        "cm",
        ParameterKind.RATIO,
        plausible_range=(0.0, 120.0),
        better=BetterDirection.LOWER,
        capture_cost=CaptureCost.FREE,
        source_kinds=(_DV,),
        affects=("outcome.score_mean",),
        notes="Mean distance from the group centroid — precision, not accuracy.",
    ),
    _p(
        "outcome.group_center_x_cm",
        "Group centre X (signed)",
        ParameterCategory.OUTCOME,
        "cm",
        ParameterKind.INTERVAL,
        plausible_range=(-120.0, 120.0),
        better=BetterDirection.BAND,
        target_band=(-2.0, 2.0),
        capture_cost=CaptureCost.FREE,
        source_kinds=(_DV,),
        notes="Positive = right of the point of aim (archer-frame convention; recorded once).",
    ),
    _p(
        "outcome.group_center_y_cm",
        "Group centre Y (signed)",
        ParameterCategory.OUTCOME,
        "cm",
        ParameterKind.INTERVAL,
        plausible_range=(-120.0, 120.0),
        better=BetterDirection.BAND,
        target_band=(-2.0, 2.0),
        capture_cost=CaptureCost.FREE,
        source_kinds=(_DV,),
        notes="Positive = above the point of aim.",
    ),
    _p(
        "outcome.drop_cm",
        "Drop vs sight setting",
        ParameterCategory.OUTCOME,
        "cm",
        ParameterKind.INTERVAL,
        plausible_range=(-200.0, 200.0),
        better=BetterDirection.BAND,
        target_band=(-3.0, 3.0),
        capture_cost=CaptureCost.FREE,
        source_kinds=(_DV,),
        notes="Systematic vertical bias — a sight-mark conversation, not a form one.",
    ),
    # ------------------------------------------------------------------ load
    _p(
        "load.arrows_shot",
        "Arrows shot",
        ParameterCategory.LOAD,
        None,
        ParameterKind.COUNT,
        plausible_range=(0.0, 1000.0),
        better=BetterDirection.BAND,
        target_band=(60.0, 250.0),
        capture_cost=CaptureCost.FREE,
        source_kinds=(_SR, _DV),
        notes="Acute volume. The band is a placeholder for 'usual practice', not a limit.",
    ),
    _p(
        "load.draw_volume_lb_reps",
        "Draw volume",
        ParameterCategory.LOAD,
        "lb·reps",
        ParameterKind.RATIO,
        plausible_range=(0.0, 300000.0),
        better=BetterDirection.NONE,
        capture_cost=CaptureCost.FREE,
        source_kinds=(_DV,),
        notes="Sum of draw weight x reps across range and gym work — the honest load unit for "
        "a sport where every repetition is a pull at a known force.",
    ),
    _p(
        "load.rpe_1_10",
        "Session RPE",
        ParameterCategory.LOAD,
        "1-10",
        ParameterKind.ORDINAL,
        scale_anchor="1 = trivial; 10 = maximal effort",
        plausible_range=(1.0, 10.0),
        better=BetterDirection.BAND,
        target_band=(3.0, 8.0),
        capture_cost=CaptureCost.FREE,
        source_kinds=(_SR,),
    ),
    _p(
        "load.session_duration_min",
        "Session duration",
        ParameterCategory.LOAD,
        "min",
        ParameterKind.RATIO,
        plausible_range=(5.0, 400.0),
        capture_cost=CaptureCost.FREE,
        source_kinds=(_SR, _SE),
    ),
    _p(
        "load.acwr",
        "Acute:chronic workload ratio",
        ParameterCategory.LOAD,
        None,
        ParameterKind.RATIO,
        plausible_range=(0.0, 5.0),
        better=BetterDirection.BAND,
        target_band=(0.8, 1.3),
        capture_cost=CaptureCost.FREE,
        source_kinds=(_DV,),
        notes="7-day load / 28-day rolling average. A caution signal, not a verdict.",
    ),
    _p(
        "load.weekly_ramp_pct",
        "Weekly load change",
        ParameterCategory.LOAD,
        "%",
        ParameterKind.RATIO,
        plausible_range=(-100.0, 300.0),
        better=BetterDirection.BAND,
        target_band=(-20.0, 10.0),
        capture_cost=CaptureCost.FREE,
        source_kinds=(_DV,),
        notes="Common guidance caps increases near +10 %/week.",
    ),
    _p(
        "load.sleep_hours",
        "Sleep",
        ParameterCategory.LOAD,
        None,
        ParameterKind.RATIO,
        plausible_range=(0.0, 16.0),
        better=BetterDirection.BAND,
        target_band=(7.0, 9.5),
        capture_cost=CaptureCost.FREE,
        source_kinds=(_SR,),
        affects=("outcome.score_mean", "mental.focus_quality_1_5"),
    ),
    _p(
        "load.soreness_1_5",
        "Soreness",
        ParameterCategory.LOAD,
        "1-5",
        ParameterKind.ORDINAL,
        scale_anchor="1 = none; 5 = limiting normal movement",
        plausible_range=(1.0, 5.0),
        better=BetterDirection.LOWER,
        capture_cost=CaptureCost.FREE,
        source_kinds=(_SR,),
        notes="Level 4-5 combined with pain vocabulary routes to the referral template.",
    ),
    _p(
        "load.resting_hr_bpm",
        "Resting heart rate",
        ParameterCategory.LOAD,
        "bpm",
        ParameterKind.RATIO,
        plausible_range=(30.0, 120.0),
        capture_cost=CaptureCost.LOW,
        source_kinds=(_SR, _SE),
    ),
    # ----------------------------------------------------------- environment
    _p(
        "env.distance_m",
        "Distance",
        ParameterCategory.ENVIRONMENT,
        "m",
        ParameterKind.RATIO,
        plausible_range=(1.0, 100.0),
        capture_cost=CaptureCost.FREE,
        source_kinds=(_SR, _SE),
        notes="A mandatory context field for any outcome parameter.",
    ),
    _p(
        "env.wind_speed_mps",
        "Wind speed",
        ParameterCategory.ENVIRONMENT,
        "m/s",
        ParameterKind.RATIO,
        plausible_range=(0.0, 30.0),
        capture_cost=CaptureCost.LOW,
        source_kinds=(_SR, _SE),
        notes="A confounder. If it is not recorded, outdoor comparisons are not controlled.",
    ),
    _p(
        "env.wind_direction_deg",
        "Wind direction",
        ParameterCategory.ENVIRONMENT,
        "°",
        ParameterKind.INTERVAL,
        plausible_range=(0.0, 360.0),
        capture_cost=CaptureCost.LOW,
        source_kinds=(_SR,),
        notes="Degrees clockwise from the archer's 12 o'clock.",
    ),
    _p(
        "env.temperature_c",
        "Temperature",
        ParameterCategory.ENVIRONMENT,
        "°C",
        ParameterKind.RATIO,
        plausible_range=(-20.0, 50.0),
        capture_cost=CaptureCost.LOW,
        source_kinds=(_SR, _SE),
    ),
    _p(
        "env.humidity_pct",
        "Humidity",
        ParameterCategory.ENVIRONMENT,
        "%",
        ParameterKind.RATIO,
        plausible_range=(0.0, 100.0),
        capture_cost=CaptureCost.LOW,
        source_kinds=(_SR, _SE),
    ),
    # ------------------------------------------------------------- adherence
    _p(
        "adherence.planned_completion_pct",
        "Planned volume completed",
        ParameterCategory.ADHERENCE,
        "%",
        ParameterKind.RATIO,
        plausible_range=(0.0, 200.0),
        better=BetterDirection.BAND,
        target_band=(85.0, 115.0),
        capture_cost=CaptureCost.FREE,
        source_kinds=(_DV,),
        affects=("outcome.score_mean",),
        notes="Both under- and over-execution are signals. Over-execution is the one that "
        "predicts injury, and it is the one training logs usually fail to show.",
    ),
    _p(
        "adherence.sessions_planned_per_week",
        "Planned sessions per week",
        ParameterCategory.ADHERENCE,
        None,
        ParameterKind.COUNT,
        plausible_range=(0.0, 21.0),
        capture_cost=CaptureCost.FREE,
        source_kinds=(_SR,),
    ),
    _p(
        "adherence.standard_pass_rate_pct",
        "Standard pass rate",
        ParameterCategory.ADHERENCE,
        "%",
        ParameterKind.RATIO,
        plausible_range=(0.0, 100.0),
        better=BetterDirection.BAND,
        target_band=(60.0, 85.0),
        capture_cost=CaptureCost.FREE,
        source_kinds=(_DV,),
        notes="A standard that is always passed is not a standard; one never passed is a wall.",
    ),
)

REGISTRY: MappingProxyType[str, ParameterDefinition] = MappingProxyType(
    {d.key: d for d in _DEFINITIONS}
)


class UnknownParameterError(KeyError):
    """Raised when a parameter key is used that is not in the registry."""

    def __init__(self, key: str) -> None:
        import difflib

        close = difflib.get_close_matches(key, list(REGISTRY), n=3, cutoff=0.6)
        if not close:
            close = difflib.get_close_matches(key.split(".")[-1], list(REGISTRY), n=3, cutoff=0.4)
        suggestions = close or list(REGISTRY)[:3]
        super().__init__(
            f"unknown parameter {key!r}. Parameters are registry-versioned "
            f"(domain/parameters.py) — add a ParameterDefinition before using it. "
            f"Did you mean one of: {', '.join(sorted(suggestions))}?"
        )
        self.key = key


def get(key: str) -> ParameterDefinition:
    """Look up a definition, with a helpful failure message."""
    try:
        return REGISTRY[key]
    except KeyError:
        raise UnknownParameterError(key) from None


def exists(key: str) -> bool:
    return key in REGISTRY


def keys() -> tuple[str, ...]:
    return tuple(REGISTRY)


def by_category(category: ParameterCategory) -> tuple[ParameterDefinition, ...]:
    return tuple(d for d in REGISTRY.values() if d.category is category)


def low_capture_cost(max_cost: CaptureCost = CaptureCost.LOW) -> tuple[ParameterDefinition, ...]:
    """The practical subset: what a coach can ask for without a lab."""
    order = [CaptureCost.FREE, CaptureCost.LOW, CaptureCost.MEDIUM, CaptureCost.HIGH]
    ceiling = order.index(max_cost)
    return tuple(d for d in REGISTRY.values() if order.index(d.capture_cost) <= ceiling)


def validate_registry() -> None:
    """Import-time / CI-time self-check. Raises AssertionError listing every problem found.

    This exists because the registry is the vocabulary of the whole system: a registry that
    is internally inconsistent produces silently wrong statistics later, when nobody is
    looking at this file any more.
    """
    problems: list[str] = []
    seen: set[str] = set()
    for key, definition in REGISTRY.items():
        if key != definition.key:
            problems.append(f"{key}: dict key does not match definition.key {definition.key!r}")
        if key in seen:
            problems.append(f"{key}: duplicate key")
        seen.add(key)
        if definition.kind is ParameterKind.ORDINAL and not definition.scale_anchor:
            problems.append(f"{key}: ordinal without scale_anchor")
        if definition.better is BetterDirection.BAND and definition.target_band is None:
            problems.append(f"{key}: better=band without target_band")
        if (
            definition.source_kinds
            and ObservationSource.DERIVED in definition.source_kinds
            and len(definition.source_kinds) == 1
            and definition.capture_cost is not CaptureCost.FREE
        ):
            problems.append(
                f"{key}: derived-only parameters should be capture_cost=free "
                "(they cost the archer nothing)"
            )
    # outcome parameters are the dependent variables: they must never be empty
    if not by_category(ParameterCategory.OUTCOME):
        problems.append("no OUTCOME parameters registered — the regression would have no target")
    for key in CORE_PARAMETERS:
        if key not in REGISTRY:
            problems.append(
                f"core parameter {key!r} is not registered — the mandatory capture set must be "
                "a subset of the registry (Q5, docs/07-open-questions.md)"
            )
    if not CORE_PARAMETERS:
        problems.append("the mandatory capture set is empty; nothing would ever be recorded")
    if problems:
        raise AssertionError("parameter registry problems:\n  - " + "\n  - ".join(problems))
