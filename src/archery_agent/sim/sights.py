"""Sight-mark prediction.

Sight marks are the archer's own measurements, so this is the one estimator in the product
with genuinely high-quality input data. Two rules keep it honest:

* **Interpolation is trustworthy; extrapolation is a guess.** Outside the measured range the
  prediction is capped at a bounded ratio and labelled ESTIMATED with a warning. Beyond that
  the function refuses to answer at all — an invented 70 m sight mark wastes an archer's
  afternoon and erodes trust in every other number.
* **A prediction always ships with the test.** The output tells the archer how to check it
  with one end of arrows.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from itertools import pairwise

from pydantic import BaseModel, ConfigDict, Field

from archery_agent.domain.entities import utcnow
from archery_agent.domain.enums import Confidence

#: Distance ratio beyond which extrapolation is refused outright.
MAX_EXTRAPOLATION_RATIO: float = 1.3


class SightMark(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    distance_m: float = Field(gt=0.0, le=100.0)
    mark: float = Field(description="Sight setting in the sight's own units (e.g. clicks/scale).")
    measured_at: datetime = Field(default_factory=utcnow)
    note: str = ""


class SightMarkPrediction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    distance_m: float
    predicted_mark: float | None = None
    method: str
    confidence: Confidence
    ok: bool
    used_marks: tuple[SightMark, ...] = ()
    warning: str = ""
    verification_step: str = ""


def predict_sight_mark(
    marks: Sequence[SightMark],
    distance_m: float,
    *,
    max_extrapolation_ratio: float = MAX_EXTRAPOLATION_RATIO,
) -> SightMarkPrediction:
    if len(marks) < 2:
        return SightMarkPrediction(
            distance_m=distance_m,
            method="none",
            confidence=Confidence.INSUFFICIENT_DATA,
            ok=False,
            used_marks=tuple(marks),
            warning=(
                "at least two measured sight marks are needed; a single mark cannot distinguish "
                "a flat trajectory from a steep one"
            ),
            verification_step="Record a sight mark at a second distance first.",
        )

    ordered = sorted(marks, key=lambda m: m.distance_m)
    if any(a.distance_m == b.distance_m for a, b in pairwise(ordered)):
        return SightMarkPrediction(
            distance_m=distance_m,
            method="none",
            confidence=Confidence.INSUFFICIENT_DATA,
            ok=False,
            warning="two sight marks share the same distance — pick one before predicting",
        )

    nearest = min(ordered, key=lambda m: abs(m.distance_m - distance_m))
    ratio = max(distance_m, nearest.distance_m) / min(distance_m, nearest.distance_m)
    in_range = ordered[0].distance_m <= distance_m <= ordered[-1].distance_m

    if not in_range and ratio > max_extrapolation_ratio:
        return SightMarkPrediction(
            distance_m=distance_m,
            method="refused",
            confidence=Confidence.INSUFFICIENT_DATA,
            ok=False,
            used_marks=tuple(ordered),
            warning=(
                f"{distance_m:g} m is {ratio:.2f}x beyond the nearest measured mark "
                f"({nearest.distance_m:g} m), past the {max_extrapolation_ratio:.2f}x limit. "
                "Trajectory is non-linear at that range — a prediction here would be fiction."
            ),
            verification_step=(
                f"Shoot 3 arrows at {distance_m:g} m from a safe known setting and record the mark."
            ),
        )

    for lower, upper in pairwise(ordered):
        if lower.distance_m <= distance_m <= upper.distance_m:
            span = upper.distance_m - lower.distance_m
            t = (distance_m - lower.distance_m) / span
            predicted = lower.mark + t * (upper.mark - lower.mark)
            return SightMarkPrediction(
                distance_m=distance_m,
                predicted_mark=predicted,
                method="interpolated",
                confidence=Confidence.INTERPOLATED,
                ok=True,
                used_marks=(lower, upper),
                warning="" if span <= 20.0 else f"marks are {span:g} m apart; add one in between",
                verification_step=(
                    f"Shoot one 3-arrow end at {distance_m:g} m and adjust by the observed group "
                    "centre before scoring."
                ),
            )

    # Extrapolation within the accepted ratio: use the two nearest marks.
    edge = sorted(ordered, key=lambda m: abs(m.distance_m - distance_m))[:2]
    lower, upper = sorted(edge, key=lambda m: m.distance_m)
    span = upper.distance_m - lower.distance_m
    slope = (upper.mark - lower.mark) / span
    predicted = upper.mark + slope * (distance_m - upper.distance_m)
    return SightMarkPrediction(
        distance_m=distance_m,
        predicted_mark=predicted,
        method="extrapolated",
        confidence=Confidence.ESTIMATED,
        ok=True,
        used_marks=(lower, upper),
        warning=(
            f"{distance_m:g} m is outside the measured range "
            f"({ordered[0].distance_m:g}-{ordered[-1].distance_m:g} m); the gap widens "
            "non-linearly, so treat this as a starting point only"
        ),
        verification_step=(
            f"Shoot 3 arrows at {distance_m:g} m from this setting, then correct from the group "
            "centre. Do not score the first end."
        ),
    )
