"""Arrow setup simulator: mass, balance point, FOC, kinetic energy, momentum, speed estimate.

The brief asks for a calculator where an archer enters *brand / poundage / fletching* and gets
an optimised setup for their case. This module is the deterministic half of that; the agent's
job is to ask for the missing inputs, run this, and report it with the assumptions attached.

Honesty rules implemented here:

* **Catalog mass is not measured mass.** If the archer has weighed the arrow, that value wins
  and the derived value is labelled MEASURED; otherwise it is ESTIMATED.
* **Speed is never invented.** Either it was measured with a chronograph (MEASURED), or it is
  estimated from a bow's IBO rating with a documented rule-of-thumb model (ESTIMATED) that
  carries the model constants in ``assumptions``.
* **Every estimate names its calibration step.** "Chronograph this setup" is part of the
  output, not optional advice.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from archery_agent.domain.entities import ArrowSetup
from archery_agent.domain.enums import Confidence
from archery_agent.domain.units import kinetic_energy_ft_lb, momentum_lb_s

#: The two grains-per-pound thresholds, named because they mean different things and were
#: previously the same magic number in two places. 5 gr/lb is the widely quoted *guidance*; 4 is
#: the point past which dry-fire risk is real enough that the harness warns loudly rather than
#: mentioning it. Do not merge them.
COMMON_MIN_GRAINS_PER_POUND: float = 5.0
DRY_FIRE_RISK_GRAINS_PER_POUND: float = 4.0

#: Default mass positions (inches from the nock end of the shaft).
DEFAULT_VANE_POSITION_IN: float = 1.5
DEFAULT_INSERT_POSITION_OFFSET_FROM_TIP_IN: float = 0.0


class ArrowBuild(BaseModel):
    """A complete arrow specification. Component masses are catalog or measured values."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    brand: str = ""
    model: str = ""
    shaft_length_in: float = Field(gt=0.0, le=34.0)
    shaft_mass_grains: float = Field(gt=0.0)

    insert_mass_grains: Annotated[float, Field(ge=0.0)] = 0.0
    point_mass_grains: Annotated[float, Field(ge=0.0)] = 0.0
    nock_mass_grains: Annotated[float, Field(ge=0.0)] = 0.0
    vane_mass_grains: Annotated[float, Field(ge=0.0)] = 0.0
    vane_position_in: float = Field(default=DEFAULT_VANE_POSITION_IN, ge=0.0, le=12.0)

    measured_total_mass_grains: float | None = Field(default=None, gt=0.0)
    static_spine_thou: float | None = Field(default=None, gt=0.0)

    @model_validator(mode="after")
    def _front_mass_is_real(self) -> ArrowBuild:
        if self.vane_position_in > self.shaft_length_in:
            raise ValueError("vane position cannot be beyond the front of the shaft")
        return self

    @property
    def component_mass_grains(self) -> float:
        return (
            self.shaft_mass_grains
            + self.insert_mass_grains
            + self.point_mass_grains
            + self.nock_mass_grains
            + self.vane_mass_grains
        )


def arrow_build_from_setup(setup: ArrowSetup) -> ArrowBuild:
    """Bridge a stored :class:`~archery_agent.domain.entities.ArrowSetup` into a sim build.

    Raises ``ValueError`` with the missing field named rather than guessing a default: an
    invented shaft mass silently corrupts FOC, grains per pound and speed all at once.
    """
    if setup.shaft_length_in is None or setup.shaft_mass_grains is None:
        missing = [
            name
            for name, value in (
                ("shaft_length_in", setup.shaft_length_in),
                ("shaft_mass_grains", setup.shaft_mass_grains),
            )
            if value is None
        ]
        raise ValueError("missing " + " and ".join(missing))
    return ArrowBuild(
        brand=setup.brand,
        model=setup.model,
        shaft_length_in=float(setup.shaft_length_in),
        shaft_mass_grains=float(setup.shaft_mass_grains),
        insert_mass_grains=float(setup.insert_mass_grains or 0.0),
        point_mass_grains=float(setup.point_mass_grains or 0.0),
        nock_mass_grains=float(setup.nock_mass_grains or 0.0),
        measured_total_mass_grains=(
            float(setup.measured_total_mass_grains)
            if setup.measured_total_mass_grains is not None
            else None
        ),
        static_spine_thou=(
            float(setup.shaft_spine_thou) if setup.shaft_spine_thou is not None else None
        ),
    )


def total_mass_grains(build: ArrowBuild) -> tuple[float, Confidence, tuple[str, ...]]:
    """Measured mass wins over summed component mass. Returns (value, confidence, notes)."""
    if build.measured_total_mass_grains is not None:
        notes = (
            f"using measured total mass {build.measured_total_mass_grains:.1f} gr",
            f"summed component mass is {build.component_mass_grains:.1f} gr",
        )
        return build.measured_total_mass_grains, Confidence.MEASURED, notes
    return (
        build.component_mass_grains,
        Confidence.ESTIMATED,
        (
            "total mass summed from catalog component masses — catalog values are routinely "
            "0.5-2 % optimistic; weigh a finished arrow for a MEASURED value",
        ),
    )


def balance_point_in(build: ArrowBuild) -> float:
    """Balance point measured from the nock end, in inches.

    Treated as a mass distribution along the shaft axis: the shaft is uniform, the insert and
    point sit at the front, the nock at the rear, vanes near the rear.
    """
    length = build.shaft_length_in
    contributions = [
        (build.shaft_mass_grains, length / 2.0),
        (build.insert_mass_grains, length - DEFAULT_INSERT_POSITION_OFFSET_FROM_TIP_IN),
        (build.point_mass_grains, length),
        (build.nock_mass_grains, 0.0),
        (build.vane_mass_grains, build.vane_position_in),
    ]
    total = sum(mass for mass, _ in contributions)
    if total <= 0:
        raise ValueError("arrow has no mass")
    return sum(mass * position for mass, position in contributions) / total


def foc_pct(build: ArrowBuild) -> float:
    """Front-of-centre percentage: ``(balance_point - L/2) / L * 100``.

    Positive means the balance point is forward of the shaft's midpoint.
    """
    return (balance_point_in(build) - build.shaft_length_in / 2.0) / build.shaft_length_in * 100.0


class SpeedModelParams(BaseModel):
    """Rule-of-thumb sensitivity used to project a bow's IBO rating onto a real setup.

    These are *estimates of sensitivity*, not physics. They exist so the archer can compare
    candidate arrows before buying, and they are reported in the output so anyone can
    disagree with them explicitly.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ibo_draw_weight_lb: float = 70.0
    ibo_draw_length_in: float = 30.0
    ibo_arrow_mass_grains: float = 350.0  # = 5 gr/lb at 70 lb
    fps_per_extra_grain: float = 0.35
    fps_per_draw_weight_lb: float = 2.0
    fps_per_draw_length_in: float = 10.0
    source: str = (
        "Community rule-of-thumb sensitivities (≈2 fps per lb of draw weight, ≈10 fps per inch "
        "of draw length, ≈0.35 fps per grain of arrow mass). NOT a manufacturer curve."
    )


class ShotContext(BaseModel):
    """The archer's setup as it affects arrow behaviour."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    draw_weight_lb: float = Field(gt=0.0, le=100.0)
    draw_length_in: float = Field(gt=0.0, le=35.0)
    ibo_fps: float | None = Field(default=None, gt=0.0, le=400.0)
    measured_speed_fps: float | None = Field(default=None, gt=0.0, le=400.0)
    distance_m: float | None = Field(default=None, gt=0.0, le=100.0)


class ArrowSetupResult(BaseModel):
    """Everything the calculator knows, with the honesty labels attached."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    build: ArrowBuild
    total_mass_grains: float
    balance_point_in: float
    foc_pct: float
    grains_per_pound: float
    kinetic_energy_ft_lb: float | None = None
    momentum_lb_s: float | None = None
    speed_fps: float | None = None
    speed_confidence: Confidence = Confidence.INSUFFICIENT_DATA
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def summary(self) -> str:
        speed = f"{self.speed_fps:.0f} fps ({self.speed_confidence})" if self.speed_fps else "n/a"
        ke = f"{self.kinetic_energy_ft_lb:.1f} ft·lb" if self.kinetic_energy_ft_lb else "n/a"
        return (
            f"{self.build.brand} {self.build.model}".strip()
            + f": {self.total_mass_grains:.0f} gr, FOC {self.foc_pct:.1f} %, "
            f"{self.grains_per_pound:.2f} gr/lb, {speed}, KE {ke}"
        )


def estimate_speed_fps(
    build: ArrowBuild, context: ShotContext, model: SpeedModelParams
) -> tuple[float, Confidence, tuple[str, ...]]:
    """Speed for this arrow on this bow — measured if possible, projected if not."""
    if context.measured_speed_fps is not None:
        return (
            context.measured_speed_fps,
            Confidence.MEASURED,
            ("chronograph reading supplied for this exact setup",),
        )

    mass, mass_conf, mass_notes = total_mass_grains(build)

    if context.ibo_fps is None:
        return (
            0.0,  # callers must treat 0.0 as "not available" and never report it
            Confidence.INSUFFICIENT_DATA,
            (
                *mass_notes,
                "no chronograph reading and no IBO rating — speed cannot be estimated; ask for "
                "the bow's IBO rating or a chronograph measurement rather than guessing one",
            ),
        )

    assumptions: list[str] = [
        f"IBO reference: {context.ibo_fps:.0f} fps at {model.ibo_draw_weight_lb:.0f} lb / "
        f"{model.ibo_draw_length_in:.0f} in / {model.ibo_arrow_mass_grains:.0f} gr",
        model.source,
        *mass_notes,
    ]

    draw_weight_delta = context.draw_weight_lb - model.ibo_draw_weight_lb
    draw_length_delta = context.draw_length_in - model.ibo_draw_length_in
    mass_delta = mass - model.ibo_arrow_mass_grains

    speed = (
        context.ibo_fps
        + draw_weight_delta * model.fps_per_draw_weight_lb
        + draw_length_delta * model.fps_per_draw_length_in
        - mass_delta * model.fps_per_extra_grain
    )

    assumptions.append(
        f"applied sensitivities: {model.fps_per_draw_weight_lb:+.2f} fps/lb draw weight, "
        f"{model.fps_per_draw_length_in:+.1f} fps/in draw length, "
        f"{-model.fps_per_extra_grain:+.2f} fps/gr arrow mass"
    )
    if mass_conf is Confidence.MEASURED:
        assumptions.append(
            "arrow mass is measured, but the speed curve is still a projection — chronograph "
            "this setup before making tuning decisions on it"
        )
    return max(speed, 0.0), Confidence.ESTIMATED, tuple(assumptions)


def evaluate_arrow_setup(
    build: ArrowBuild,
    context: ShotContext,
    model: SpeedModelParams | None = None,
) -> ArrowSetupResult:
    """Full evaluation of one candidate arrow on one bow."""
    model = model or SpeedModelParams()
    mass, _mass_conf, mass_notes = total_mass_grains(build)
    speed_fps, speed_conf, speed_notes = estimate_speed_fps(build, context, model)

    warnings: list[str] = []
    grains_per_pound = mass / context.draw_weight_lb
    if grains_per_pound < DRY_FIRE_RISK_GRAINS_PER_POUND:
        warnings.append(
            f"{grains_per_pound:.2f} gr/lb is below the common "
            f"~{COMMON_MIN_GRAINS_PER_POUND:g} gr/lb guidance — dry-fire risk and string/vibration "
            f"wear rise sharply below {COMMON_MIN_GRAINS_PER_POUND:g} gr/lb; check the bow "
            "manufacturer's minimum before shooting this"
        )
    if grains_per_pound > 8.0:
        warnings.append(
            f"{grains_per_pound:.2f} gr/lb is heavy; expect a noticeably arced trajectory and "
            "wider sight-mark gaps at longer distances"
        )

    has_speed = speed_conf is not Confidence.INSUFFICIENT_DATA and speed_fps > 0.0
    return ArrowSetupResult(
        build=build,
        total_mass_grains=mass,
        balance_point_in=balance_point_in(build),
        foc_pct=foc_pct(build),
        grains_per_pound=grains_per_pound,
        kinetic_energy_ft_lb=kinetic_energy_ft_lb(mass, speed_fps) if has_speed else None,
        momentum_lb_s=momentum_lb_s(mass, speed_fps) if has_speed else None,
        speed_fps=speed_fps if has_speed else None,
        speed_confidence=speed_conf,
        # ``speed_notes`` already carries the mass notes (they change the speed estimate), so
        # concatenating both here would print the same caveat twice.
        assumptions=tuple(dict.fromkeys((*mass_notes, *speed_notes))),
        warnings=tuple(warnings),
    )


def optimize_arrow_setup(
    candidates: Sequence[ArrowBuild],
    context: ShotContext,
    *,
    target_speed_fps: float | None = None,
    prefer_grains_per_pound: tuple[float, float] = (5.0, 7.0),
    prefer_foc_pct: tuple[float, float] = (8.0, 16.0),
    model: SpeedModelParams | None = None,
) -> tuple[ArrowSetupResult, ...]:
    """Rank candidate arrows for this archer, best first.

    The ranking is **not** a single opaque score. It is a documented preference order over
    measurable properties, and every candidate's report states which preference it failed and
    by how much — because the honest answer to "which arrow should I buy" is a trade-off, not
    a verdict.

    Ranking key (all deterministic):
      1. in the preferred gr/lb band (else distance outside it),
      2. within 3 fps of ``target_speed_fps`` if one is given (else any),
      3. FOC closer to the middle of ``prefer_foc_pct``,
      4. lower kinetic-energy downside (tie-break: higher KE).
    """
    model = model or SpeedModelParams()
    results = [evaluate_arrow_setup(build, context, model) for build in candidates]

    def penalty(result: ArrowSetupResult) -> tuple[float, float, float, float]:
        gpp = result.grains_per_pound
        lo, hi = prefer_grains_per_pound
        gpp_penalty = 0.0 if lo <= gpp <= hi else min(abs(gpp - lo), abs(gpp - hi))
        speed_penalty = (
            0.0
            if target_speed_fps is None or result.speed_fps is None
            else max(0.0, abs(result.speed_fps - target_speed_fps) - 3.0)
        )
        foc_lo, foc_hi = prefer_foc_pct
        foc_mid = (foc_lo + foc_hi) / 2.0
        foc_penalty = 0.0 if foc_lo <= result.foc_pct <= foc_hi else abs(result.foc_pct - foc_mid)
        ke = result.kinetic_energy_ft_lb or 0.0
        return (gpp_penalty + speed_penalty + foc_penalty, gpp_penalty, foc_penalty, -ke)

    return tuple(sorted(results, key=penalty))
