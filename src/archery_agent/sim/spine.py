"""Spine coherence: does this shaft match this draw, this length and this front weight?

A spine chart is manufacturer data, not physics. This module therefore models the *chart* as
data (:class:`SpineChart`) with provenance, and returns ``UNVERIFIED`` whenever the loaded chart
is not sourced. That is the honest behaviour: an archer can still be warned that a shaft is
clearly out of range, but the app never presents a placeholder curve as tuning advice.
"""

from __future__ import annotations

from itertools import pairwise

from pydantic import BaseModel, ConfigDict, Field, model_validator

from archery_agent.domain.enums import Confidence
from archery_agent.domain.units import UNVERIFIED_CONSTANTS

_SPINE_KEY = "sim.spine.DEFAULT_SPINE_CHART"


class SpineChart(BaseModel):
    """A manufacturer's static-spine chart, as data.

    ``rows`` maps a draw-weight band (lb) to a mapping of arrow length (in) -> static spine
    deflection (thousandths of an inch). Deflection decreases (stiffer) as draw weight rises
    and as arrow length falls — the shape every chart shares, whatever the numbers are.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    chart_id: str
    manufacturer: str
    bow_type: str = "compound"
    cam_aggressiveness: str = Field(
        default="moderate", description="'soft' | 'moderate' | 'hard' cam profile."
    )
    rows: tuple[tuple[float, tuple[tuple[float, float], ...]], ...]
    point_mass_assumption_grains: float = 100.0
    verified: bool = False
    source: str = ""
    notes: str = ""

    @model_validator(mode="after")
    def _monotonic(self) -> SpineChart:
        """Charts must behave in both directions, because a transposed chart is worse than none.

        Stiffness conventions matter here: *static spine* is measured as deflection, so a
        **smaller number means a stiffer shaft**.

        * within a draw-weight row: a longer arrow flexes more in flight, so it needs a stiffer
          shaft -> deflection must be non-increasing as length increases;
        * across rows: a heavier draw bends the shaft more, so it needs a stiffer shaft ->
          for the same length, deflection must be non-increasing as draw weight increases.
        """
        for _weight, series in self.rows:
            lengths = [length for length, _ in series]
            spines = [spine for _, spine in series]
            if lengths != sorted(lengths):
                raise ValueError(f"{self.chart_id}: arrow lengths must be ascending")
            if any(later > earlier for earlier, later in pairwise(spines)):
                raise ValueError(
                    f"{self.chart_id}: within a draw-weight row, deflection must not increase "
                    "with arrow length — a longer arrow needs a stiffer (lower-deflection) "
                    "shaft. The chart looks transposed or corrupt."
                )

        weights = [weight for weight, _ in self.rows]
        if weights != sorted(weights):
            raise ValueError(f"{self.chart_id}: draw-weight rows must be ascending")
        first_lengths = [length for length, _ in self.rows[0][1]]
        for index in range(len(self.rows) - 1):
            _w_lo, lower_series = self.rows[index]
            _w_hi, upper_series = self.rows[index + 1]
            if [length for length, _ in lower_series] != first_lengths:
                raise ValueError(
                    f"{self.chart_id}: every draw-weight row must cover the same arrow lengths"
                )
            for (_len_lo, spine_lo), (_len_hi, spine_hi) in zip(
                lower_series, upper_series, strict=True
            ):
                if spine_hi > spine_lo:
                    raise ValueError(
                        f"{self.chart_id}: at the same arrow length, a heavier draw weight must "
                        "not recommend a weaker (higher-deflection) shaft"
                    )
        return self

    def row_for(self, draw_weight_lb: float) -> tuple[tuple[float, float], ...]:
        """The nearest draw-weight band, rounded up (the conservative direction: stiffer)."""
        weights = [weight for weight, _ in self.rows]
        chosen = min((w for w in weights if w >= draw_weight_lb), default=max(weights))
        for weight, series in self.rows:
            if weight == chosen:
                return series
        raise ValueError(f"{self.chart_id}: no row for {draw_weight_lb} lb")

    def recommended_spine_thou(self, draw_weight_lb: float, arrow_length_in: float) -> float:
        series = self.row_for(draw_weight_lb)
        lengths = [length for length, _ in series]
        if arrow_length_in <= lengths[0]:
            return series[0][1]
        if arrow_length_in >= lengths[-1]:
            return series[-1][1]
        for (l0, s0), (l1, s1) in pairwise(series):
            if l0 <= arrow_length_in <= l1:
                t = (arrow_length_in - l0) / (l1 - l0)
                return s0 + t * (s1 - s0)
        raise ValueError("unreachable: length inside range but no bracketing pair")


#: PLACEHOLDER chart. The *shape* is correct (heavier draw and shorter shaft -> stiffer), but
#: the numbers are illustrative and must be replaced with a real manufacturer chart before any
#: recommendation is treated as advice. See docs/07-open-questions.md and AGENTS.md rule 3.
DEFAULT_SPINE_CHART = SpineChart(
    chart_id="PLACEHOLDER_STANDARD_COMPOUND",
    manufacturer="UNSOURCED PLACEHOLDER — replace before use",
    cam_aggressiveness="moderate",
    rows=(
        (40.0, ((26.0, 700.0), (28.0, 660.0), (30.0, 620.0))),
        (50.0, ((26.0, 600.0), (28.0, 560.0), (30.0, 520.0))),
        (60.0, ((26.0, 500.0), (28.0, 460.0), (30.0, 420.0))),
        (70.0, ((26.0, 400.0), (28.0, 360.0), (30.0, 340.0))),
    ),
    point_mass_assumption_grains=100.0,
    verified=False,
    source="Illustrative placeholder (no manufacturer chart loaded).",
    notes=UNVERIFIED_CONSTANTS[_SPINE_KEY],
)


class SpineCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    draw_weight_lb: float
    arrow_length_in: float
    actual_spine_thou: float
    recommended_spine_thou: float
    delta_thou: float = Field(
        description="actual - recommended. Positive = weaker (more deflection) than recommended. "
        "The registry key `arrow.spine_fit_delta` stores the negated convention; see "
        "`as_registry_value()`."
    )
    verdict: str
    confidence: Confidence
    assumptions: tuple[str, ...] = ()
    verification_step: str = ""

    def as_registry_value(self) -> float:
        """Registry convention: negative = stiffer than recommended."""
        return -self.delta_thou


def check_spine(
    *,
    draw_weight_lb: float,
    arrow_length_in: float,
    actual_spine_thou: float,
    point_mass_grains: float = 100.0,
    chart: SpineChart | None = None,
) -> SpineCheck:
    """Compare a shaft against the chart and say how far off it is — never just "wrong"."""
    chart = chart or DEFAULT_SPINE_CHART
    recommended = chart.recommended_spine_thou(draw_weight_lb, arrow_length_in)
    delta = actual_spine_thou - recommended

    if abs(delta) <= 50.0:
        verdict = "coherent"
    elif abs(delta) <= 150.0:
        verdict = "borderline"
    else:
        verdict = "mismatch"

    assumptions = [
        f"chart {chart.chart_id} ({chart.manufacturer})",
        f"point mass assumption {chart.point_mass_assumption_grains:.0f} gr "
        f"(requested {point_mass_grains:.0f} gr)",
        f"cam profile treated as '{chart.cam_aggressiveness}'",
    ]
    if not chart.verified:
        assumptions.append(
            "CHART IS NOT SOURCED — this comparison is a plausibility check, not tuning advice"
        )

    verification_step = (
        "Verify with a bare-shaft or paper test at the archer's actual distance before "
        "changing anything; a spine chart is a starting point, not a measurement."
    )

    return SpineCheck(
        draw_weight_lb=draw_weight_lb,
        arrow_length_in=arrow_length_in,
        actual_spine_thou=actual_spine_thou,
        recommended_spine_thou=recommended,
        delta_thou=delta,
        verdict=verdict,
        confidence=Confidence.MEASURED if chart.verified else Confidence.UNVERIFIED,
        assumptions=tuple(assumptions),
        verification_step=verification_step,
    )
