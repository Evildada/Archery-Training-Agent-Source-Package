"""Load-management sensors: acute:chronic ratio, ramp rate, monotony and strain.

These are the numbers that stop a training planner from being a wish-list generator. They are
*caution* signals, not verdicts — the vocabulary here is deliberately advisory, because the
evidence base for universal load thresholds is weaker than the confidence with which they are
usually quoted (docs/07-open-questions.md Q11).

Archery-specific note: `draw_volume_lb_reps` (sum of draw weight x repetitions) is a better
load unit than arrow count, because a 70 lb bow and a 45 lb bow produce very different tissue
loads for the same arrow count. Arrow count remains the fallback when poundage is unknown, and
the result says which unit it used.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from archery_agent.domain.enums import EvidenceLabel
from archery_agent.sensors.validators import Issue, Severity, ValidationResult

ACUTE_DAYS: int = 7
CHRONIC_DAYS: int = 28
ACWR_LOW: float = 0.8
ACWR_HIGH: float = 1.3
ACWR_VERY_HIGH: float = 1.5
MAX_WEEKLY_RAMP_PCT: float = 10.0


class LoadVerdict(StrEnum):
    INSUFFICIENT_DATA = "insufficient_data"
    LOW = "low"
    IN_BAND = "in_band"
    ELEVATED = "elevated"
    HIGH = "high"


class AcwrResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    acute_load: float = Field(ge=0.0)
    chronic_load: float = Field(ge=0.0)
    ratio: float | None = None
    verdict: LoadVerdict
    days_of_data: int = Field(ge=0)
    unit: str = "arrows"
    message: str = ""
    label: EvidenceLabel = EvidenceLabel.INSUFFICIENT_EVIDENCE


def acwr(
    daily_loads: Sequence[tuple[date, float]],
    as_of: date,
    *,
    unit: str = "arrows",
    use_ewma: bool = False,
) -> AcwrResult:
    """Acute (7-day) : chronic (28-day mean week) workload ratio.

    ``use_ewma=False`` uses the classic rolling means. The EWMA variant is exposed because the
    rolling version is sensitive to a single big session dropping out of the window; when the
    two disagree, that disagreement is itself the interesting signal.
    """
    by_day: dict[date, float] = {}
    for day, value in daily_loads:
        by_day[day] = by_day.get(day, 0.0) + float(value)

    first_day = min(by_day) if by_day else as_of
    days_of_data = (as_of - first_day).days + 1

    values = [by_day.get(as_of - timedelta(days=offset), 0.0) for offset in range(CHRONIC_DAYS)]
    acute = sum(values[:ACUTE_DAYS])
    chronic_week_mean = sum(values) / (CHRONIC_DAYS / ACUTE_DAYS)

    if days_of_data < CHRONIC_DAYS or chronic_week_mean <= 0.0:
        return AcwrResult(
            acute_load=acute,
            chronic_load=chronic_week_mean,
            ratio=None,
            verdict=LoadVerdict.INSUFFICIENT_DATA,
            days_of_data=days_of_data,
            unit=unit,
            message=(
                f"need {CHRONIC_DAYS} days of history to compute a chronic load "
                f"({days_of_data} available)"
            ),
        )

    if use_ewma:
        alpha_acute = 2.0 / (ACUTE_DAYS + 1)
        alpha_chronic = 2.0 / (CHRONIC_DAYS + 1)
        ewma_a = ewma_c = values[-1]
        for value in reversed(values):
            ewma_a = alpha_acute * value + (1 - alpha_acute) * ewma_a
            ewma_c = alpha_chronic * value + (1 - alpha_chronic) * ewma_c
        acute_eff, chronic_eff = ewma_a * ACUTE_DAYS, ewma_c * ACUTE_DAYS
        ratio = acute_eff / chronic_eff if chronic_eff > 0 else None
        acute, chronic_week_mean = acute_eff, chronic_eff
    else:
        ratio = acute / chronic_week_mean

    assert ratio is not None
    if ratio < ACWR_LOW:
        verdict = LoadVerdict.LOW
        message = (
            f"ratio {ratio:.2f} — below the {ACWR_LOW}-{ACWR_HIGH} band. Undertraining is a "
            "signal too: detraining costs skill, and gaps are usually a scheduling problem."
        )
    elif ratio <= ACWR_HIGH:
        verdict = LoadVerdict.IN_BAND
        message = f"ratio {ratio:.2f} — inside the {ACWR_LOW}-{ACWR_HIGH} band."
    elif ratio <= ACWR_VERY_HIGH:
        verdict = LoadVerdict.ELEVATED
        message = (
            f"ratio {ratio:.2f} — above the band. This is a caution, not a prohibition: "
            "prefer keeping the volume and reducing intensity, or hold volume flat next week."
        )
    else:
        verdict = LoadVerdict.HIGH
        message = (
            f"ratio {ratio:.2f} — well above the band. Plan a lighter week; if the archer "
            "reports pain or soreness >= 4/5, route to the referral path instead of programming."
        )

    return AcwrResult(
        acute_load=acute,
        chronic_load=chronic_week_mean,
        ratio=ratio,
        verdict=verdict,
        days_of_data=days_of_data,
        unit=unit,
        message=message,
        label=EvidenceLabel.PRELIMINARY,
    )


class RampResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    current_load: float
    previous_load: float
    change_pct: float | None
    verdict: LoadVerdict
    message: str = ""


def ramp_check(
    current_load: float,
    previous_load: float,
    *,
    max_ramp_pct: float = MAX_WEEKLY_RAMP_PCT,
) -> RampResult:
    """Week-over-week load change against the common +10 % guidance."""
    if previous_load <= 0:
        return RampResult(
            current_load=current_load,
            previous_load=previous_load,
            change_pct=None,
            verdict=LoadVerdict.INSUFFICIENT_DATA,
            message="no previous week to compare against",
        )
    change = (current_load - previous_load) / previous_load * 100.0
    if change > max_ramp_pct:
        verdict = LoadVerdict.HIGH if change > max_ramp_pct * 2 else LoadVerdict.ELEVATED
        message = (
            f"+{change:.0f} % week over week (guidance: <= +{max_ramp_pct:.0f} %). "
            "Propose the same plan spread over more sessions, or hold one week flat."
        )
    elif change < -20.0:
        verdict = LoadVerdict.LOW
        message = (
            f"{change:.0f} % week over week. A sharp drop is fine after a competition, but "
            "record the reason so the planner does not read it as drift."
        )
    else:
        verdict = LoadVerdict.IN_BAND
        message = f"{change:+.0f} % week over week — inside guidance."
    return RampResult(
        current_load=current_load,
        previous_load=previous_load,
        change_pct=change,
        verdict=verdict,
        message=message,
    )


class MonotonyResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    monotony: float | None = None
    strain: float | None = None
    weekly_load: float = 0.0
    message: str = ""


def monotony_strain(daily_loads: Sequence[float], *, window: int = 7) -> MonotonyResult:
    """Training monotony (mean/sd within the week) and strain (weekly load x monotony).

    Interpretation for archery: a week of *identical* days scores higher monotony than a week
    mixing heavy and light days at the same total volume. That is a scheduling insight, which is
    exactly what the planner needs and what a volume-only view cannot see.
    """
    values = [float(v) for v in daily_loads[:window]]
    if len(values) < 2 or sum(values) <= 0:
        return MonotonyResult(message="not enough data in the window")
    mu = sum(values) / len(values)
    variance = sum((v - mu) ** 2 for v in values) / (len(values) - 1)
    sd = variance**0.5
    if sd <= 0:
        return MonotonyResult(
            monotony=float("inf") if mu > 0 else None,
            strain=float("inf") if mu > 0 else None,
            weekly_load=sum(values),
            message="identical load every day — maximum monotony, which is the pattern to break",
        )
    monotony = mu / sd
    return MonotonyResult(
        monotony=monotony,
        strain=sum(values) * monotony,
        weekly_load=sum(values),
        message=(
            f"monotony {monotony:.1f} — "
            + ("high; vary the days within the week" if monotony > 2.0 else "reasonable spread")
        ),
    )


def validate_load_progression(
    *,
    proposed_weekly_load: float,
    previous_weekly_load: float,
    acwr_result: AcwrResult | None = None,
    reported_soreness_1_5: float | None = None,
    pain_reported: bool = False,
) -> ValidationResult:
    """Gate a proposed plan block. Soreness and pain outrank any load calculation."""
    issues: list[Issue] = []

    if pain_reported:
        issues.append(
            Issue(
                code="load_blocked_pain",
                severity=Severity.ERROR,
                message="a plan block cannot be approved while pain is reported",
                field="previous_weekly_load",
                suggestion=(
                    "Route to the safety referral path. Programming around an active pain report "
                    "is exactly the advice this system must never give."
                ),
            )
        )

    if reported_soreness_1_5 is not None and reported_soreness_1_5 >= 4.0:
        issues.append(
            Issue(
                code="load_blocked_soreness",
                severity=Severity.WARNING,
                message=f"soreness {reported_soreness_1_5:.0f}/5 reported before this block",
                field="reported_soreness_1_5",
                suggestion=(
                    "Hold volume flat or reduce it, and ask what changed (new poundage, new "
                    "arrow mass, a longer session)."
                ),
            )
        )

    ramp = ramp_check(proposed_weekly_load, previous_weekly_load)
    if ramp.verdict in {LoadVerdict.ELEVATED, LoadVerdict.HIGH}:
        issues.append(
            Issue(
                code="load_ramp",
                severity=Severity.WARNING,
                message=ramp.message,
                field="proposed_weekly_load",
                suggestion="Spread the increase across two weeks rather than one.",
            )
        )

    if acwr_result is not None and acwr_result.verdict in {LoadVerdict.ELEVATED, LoadVerdict.HIGH}:
        issues.append(
            Issue(
                code="load_acwr",
                severity=Severity.WARNING,
                message=acwr_result.message,
                field="acwr",
                suggestion=(
                    "The plan is still approvable — but it should be presented as a load increase "
                    "with a reason, not as a default."
                ),
            )
        )

    return ValidationResult(issues=tuple(issues))
