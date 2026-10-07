"""Statistics with the guardrails built in.

This is the module that decides whether the agent is allowed to sound confident. It is
deliberately boring, deterministic and dependency-free: no scipy, no numpy, no random seed to
forget. The brief's central belief —

    "A set of parameter can form a regression that maintains stable position"

— only produces *useful* insight if the regression cannot be fooled by six arrows and a
coincidence. So:

* :func:`effects` refuses to rank a parameter with fewer than 30 shots;
* p-values are corrected across the family of parameters tested (Benjamini-Hochberg);
* the mapping to a user-facing confidence label is a pure function
  (:func:`claim_label_for`), not a judgement call made by a language model.

Implementation notes: p-values use the Student-t distribution via the regularised incomplete
beta function (continued-fraction expansion), so no SciPy dependency is required. Pearson
confidence intervals use the Fisher z-transform.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from itertools import pairwise

from pydantic import BaseModel, ConfigDict, Field

from archery_agent.domain.enums import EvidenceLabel
from archery_agent.sensors.validators import (
    MIN_SESSIONS_FOR_TREND,
    MIN_SHOTS_FOR_EFFECT,
)

#: Family-wise threshold after multiple-comparison correction (docs/05 §2).
Q_THRESHOLD: float = 0.10

#: Modified z-score cut-off for the anomaly sensor (Iglewicz-Hoban convention).
MAD_OUTLIER_K: float = 3.5


# ------------------------------------------------------------------ descriptives


def mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("mean of an empty sequence is undefined")
    return sum(values) / len(values)


def sample_sd(values: Sequence[float]) -> float:
    n = len(values)
    if n < 2:
        raise ValueError("sample standard deviation needs at least 2 observations")
    mu = mean(values)
    return math.sqrt(sum((v - mu) ** 2 for v in values) / (n - 1))


def median(values: Sequence[float]) -> float:
    return percentile(values, 50.0)


def percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile (the 'inclusive' method, matching common practice)."""
    if not values:
        raise ValueError("percentile of an empty sequence is undefined")
    if not 0.0 <= q <= 100.0:
        raise ValueError("q must be in 0..100")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (q / 100.0) * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    fraction = rank - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def mad(values: Sequence[float]) -> float:
    """Median absolute deviation — robust spread, used by the anomaly sensor."""
    med = median(values)
    return median([abs(v - med) for v in values])


class Summary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    n: int = Field(ge=0)
    mean: float | None = None
    sd: float | None = None
    median: float | None = None
    mad: float | None = None
    p10: float | None = None
    p90: float | None = None
    unit: str | None = None

    def describe(self) -> str:
        if self.n == 0 or self.mean is None:
            return "no data"
        unit = f" {self.unit}" if self.unit else ""
        sd = f" ± {self.sd:.2f}" if self.sd is not None else ""
        return f"{self.mean:.2f}{sd}{unit} (n={self.n})"


def summarise(values: Sequence[float], *, unit: str | None = None) -> Summary:
    if not values:
        return Summary(n=0, unit=unit)
    return Summary(
        n=len(values),
        mean=mean(values),
        sd=sample_sd(values) if len(values) > 1 else None,
        median=median(values),
        mad=mad(values) if len(values) > 1 else None,
        p10=percentile(values, 10.0),
        p90=percentile(values, 90.0),
        unit=unit,
    )


def outliers_mad(values: Sequence[float], k: float = MAD_OUTLIER_K) -> tuple[bool, ...]:
    """Which observations are unusual *for this archer*. Absence of spread -> no outliers."""
    if len(values) < 4:
        return tuple(False for _ in values)
    med = median(values)
    spread = mad(values)
    if spread == 0.0:
        return tuple(v != med for v in values)
    return tuple(abs(0.6745 * (v - med) / spread) > k for v in values)


# ------------------------------------------------------- t distribution helpers


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Lentz's method)."""
    tiny = 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-12:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta function I_x(a, b)."""
    if not 0.0 <= x <= 1.0:
        raise ValueError("x must be in 0..1")
    if x in (0.0, 1.0):
        return x
    log_term = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log(1.0 - x)
    )
    term = math.exp(log_term)
    if x < (a + 1.0) / (a + b + 2.0):
        return term * _betacf(a, b, x) / a
    return 1.0 - term * _betacf(b, a, 1.0 - x) / b


def student_t_sf(t: float, df: float) -> float:
    """Upper-tail probability P(T > t) for Student's t with ``df`` degrees of freedom."""
    if df <= 0:
        raise ValueError("degrees of freedom must be positive")
    x = df / (df + t * t)
    tail = 0.5 * _betai(df / 2.0, 0.5, x)
    return tail if t > 0 else 1.0 - tail


def two_sided_p(t: float, df: float) -> float:
    return 2.0 * student_t_sf(abs(t), df)


# ------------------------------------------------------------------- inference


class CorrelationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    n: int = Field(ge=0)
    r: float | None = None
    p: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    caveats: tuple[str, ...] = ()


def pearson(x: Sequence[float], y: Sequence[float]) -> CorrelationResult:
    """Pearson correlation with a Fisher-z confidence interval."""
    if len(x) != len(y):
        raise ValueError(f"x and y must be the same length ({len(x)} vs {len(y)})")
    n = len(x)
    if n < 3:
        return CorrelationResult(n=n, caveats=("fewer than 3 paired observations",))
    mx, my = mean(x), mean(y)
    sxx = sum((v - mx) ** 2 for v in x)
    syy = sum((v - my) ** 2 for v in y)
    if sxx == 0.0 or syy == 0.0:
        return CorrelationResult(
            n=n,
            caveats=("one of the series has zero variance — no correlation is computable",),
        )
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    r = sxy / math.sqrt(sxx * syy)
    r = max(min(r, 1.0), -1.0)
    df = n - 2
    t = r * math.sqrt(df / max(1e-12, 1.0 - r * r))
    p = two_sided_p(t, df)

    ci_low = ci_high = None
    if n > 3:
        z = math.atanh(max(min(r, 0.999999), -0.999999))
        se = 1.0 / math.sqrt(n - 3)
        ci_low = math.tanh(z - 1.959964 * se)
        ci_high = math.tanh(z + 1.959964 * se)

    caveats: list[str] = []
    if n < MIN_SHOTS_FOR_EFFECT:
        caveats.append(
            f"n={n} is below the {MIN_SHOTS_FOR_EFFECT}-shot threshold for a supported effect"
        )
    caveats.append("correlation is not causation: a third variable can produce this pattern")
    return CorrelationResult(n=n, r=r, p=p, ci_low=ci_low, ci_high=ci_high, caveats=tuple(caveats))


class TrendResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    n: int = Field(ge=0)
    slope_per_session: float | None = None
    intercept: float | None = None
    r2: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    p: float | None = None
    label: EvidenceLabel = EvidenceLabel.INSUFFICIENT_EVIDENCE
    caveats: tuple[str, ...] = ()

    def describe(self, unit: str = "") -> str:
        if self.slope_per_session is None:
            return "no trend computable"
        direction = "up" if self.slope_per_session > 0 else "down"
        suffix = f" {unit}" if unit else ""
        return (
            f"{direction} {abs(self.slope_per_session):.3f}{suffix}/session over {self.n} sessions"
            f" ({self.label.value})"
        )


def trend_label_for(*, n_sessions: int, q: float | None) -> EvidenceLabel:
    """Confidence label for a *trend across sessions*.

    Deliberately stricter than the shot-level gate: ten sessions is the point at which a
    personal training log can start asserting a direction, because session-level noise
    (sleep, equipment, weather, mood) dominates over far more sessions than shot-level noise
    does. Below that, a slope is a description of what happened, not a claim about progress.
    """
    if n_sessions < MIN_SESSIONS_FOR_TREND:
        return EvidenceLabel.INSUFFICIENT_EVIDENCE
    if n_sessions < 2 * MIN_SESSIONS_FOR_TREND or q is None or q >= Q_THRESHOLD:
        return EvidenceLabel.PRELIMINARY
    return EvidenceLabel.SUPPORTED


def ols_trend(values: Sequence[float], *, unit: str = "") -> TrendResult:
    """Least-squares trend of a parameter across consecutive sessions.

    ``x`` is session order (0, 1, 2, ...), which is the honest axis for a personal training log:
    what matters is *direction and rate per session*, not a calendar-day artefact of gaps.
    """
    n = len(values)
    if n < MIN_SESSIONS_FOR_TREND:
        return TrendResult(
            n=n,
            label=EvidenceLabel.INSUFFICIENT_EVIDENCE,
            caveats=(
                f"{n} sessions is below the {MIN_SESSIONS_FOR_TREND}-session minimum for a trend",
            ),
        )
    xs = [float(i) for i in range(n)]
    mx, my = mean(xs), mean(values)
    sxx = sum((v - mx) ** 2 for v in xs)
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, values, strict=True))
    slope = sxy / sxx
    intercept = my - slope * mx
    residuals = [b - (intercept + slope * a) for a, b in zip(xs, values, strict=True)]
    sse = sum(r * r for r in residuals)
    sst = sum((b - my) ** 2 for b in values)
    r2 = 1.0 - sse / sst if sst > 0 else 0.0

    df = n - 2
    se_slope = math.sqrt(sse / df / sxx) if sse > 0 else 0.0
    if se_slope > 0:
        t = slope / se_slope
        p = two_sided_p(t, df)
        t_crit = 1.959964 if df > 60 else _t_crit_975(df)
        ci_low = slope - t_crit * se_slope
        ci_high = slope + t_crit * se_slope
    else:
        p = 0.0 if slope != 0 else 1.0
        ci_low = ci_high = slope

    label = trend_label_for(n_sessions=n, q=p)
    caveats: list[str] = [
        "a trend line through few sessions is a description, not a forecast",
    ]
    if unit:
        caveats.append(f"slope unit: {unit} per session")
    return TrendResult(
        n=n,
        slope_per_session=slope,
        intercept=intercept,
        r2=r2,
        ci_low=ci_low,
        ci_high=ci_high,
        p=p,
        label=label,
        caveats=tuple(caveats),
    )


def _t_crit_975(df: float) -> float:
    """Approximate two-sided 95 % critical value (conservative for small df)."""
    lookup = {
        1: 12.706,
        2: 4.303,
        3: 3.182,
        4: 2.776,
        5: 2.571,
        6: 2.447,
        7: 2.365,
        8: 2.306,
        9: 2.262,
        10: 2.228,
        12: 2.179,
        15: 2.131,
        20: 2.086,
        30: 2.042,
        40: 2.021,
        50: 2.009,
        60: 2.000,
    }
    keys = sorted(lookup)
    if df <= keys[0]:
        return lookup[keys[0]]
    for earlier, later in pairwise(keys):
        if earlier <= df <= later:
            t = (df - earlier) / (later - earlier)
            return lookup[earlier] + t * (lookup[later] - lookup[earlier])
    return 1.959964


def q_values(p_values: Sequence[float]) -> tuple[float, ...]:
    """Benjamini-Hochberg adjusted p-values, order-preserving."""
    m = len(p_values)
    if m == 0:
        return ()
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [0.0] * m
    previous = 1.0
    for rank, index in enumerate(reversed(order), start=1):
        k = m - rank + 1
        value = min(previous, p_values[index] * m / k)
        adjusted[index] = value
        previous = value
    return tuple(min(1.0, max(0.0, v)) for v in adjusted)


def claim_label_for(
    *, n: int | None, q: float | None = None, external: bool = False
) -> EvidenceLabel:
    """The single mapping from evidence to user-facing confidence. Do not bypass it.

    The mapping, and the reasoning behind each branch:

    * **no own data, but a citation** -> ``GENERAL_EDUCATION``: it is the source's claim, not
      the archer's.
    * **below the shot threshold** -> ``INSUFFICIENT_EVIDENCE`` with an explicit "need N more
      shots" caveat. Never silently dropped, because silence reads as agreement.
    * **enough data but q >= 0.10** -> ``INSUFFICIENT_EVIDENCE``, *not* ``PRELIMINARY``. This is
      the important one: at n >= 30 a non-significant result is a **null finding**, and dressing
      it up as "preliminary signal" is exactly how a training log starts telling stories. The
      confidence interval is reported alongside so the reader can see how tightly null it is.
    * **enough data and q < 0.10** -> ``SUPPORTED``.
    * **external support plus weak own data** -> ``PRELIMINARY``: the honest label for "the
      literature says this, your own log cannot yet confirm it".
    """
    if external and n is None:
        return EvidenceLabel.GENERAL_EDUCATION
    if n is None or n < MIN_SHOTS_FOR_EFFECT:
        if external:
            return EvidenceLabel.PRELIMINARY
        return EvidenceLabel.INSUFFICIENT_EVIDENCE
    if q is None or q >= Q_THRESHOLD:
        return EvidenceLabel.INSUFFICIENT_EVIDENCE
    return EvidenceLabel.SUPPORTED


class EffectEstimate(BaseModel):
    """One candidate parameter's relationship to an outcome, with its label."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parameter_key: str
    outcome_key: str
    n: int = Field(ge=0)
    r: float | None = None
    p: float | None = None
    q: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    label: EvidenceLabel = EvidenceLabel.INSUFFICIENT_EVIDENCE
    caveats: tuple[str, ...] = ()

    def describe(self) -> str:
        if self.r is None:
            return f"{self.parameter_key}: {self.label.value} (n={self.n})"
        ci = (
            f" [95 % CI {self.ci_low:.2f}, {self.ci_high:.2f}]"
            if self.ci_low is not None and self.ci_high is not None
            else ""
        )
        q = f", q={self.q:.3f}" if self.q is not None else ""
        return (
            f"{self.parameter_key} vs {self.outcome_key}: r={self.r:+.2f}{ci}"
            f"{q}, n={self.n} — {self.label.value}"
        )


def align_pairs(
    outcome_by_unit: Mapping[str, float],
    candidate_by_unit: Mapping[str, float],
) -> tuple[list[float], list[float]]:
    """Pair a candidate and the outcome on shared unit keys (shot id or session id).

    Pairing is done here, in the sensor layer, rather than by the caller: a mis-aligned
    regression is the classic silent bug in this kind of system, and it is exactly the sort of
    thing that must have one implementation instead of three.
    """
    shared = sorted(set(outcome_by_unit) & set(candidate_by_unit))
    return (
        [candidate_by_unit[u] for u in shared],
        [outcome_by_unit[u] for u in shared],
    )


def effects(
    *,
    outcome_key: str,
    outcome_by_unit: Mapping[str, float],
    candidates: Mapping[str, Mapping[str, float]],
    min_n: int = MIN_SHOTS_FOR_EFFECT,
) -> tuple[EffectEstimate, ...]:
    """Rank candidate parameters by their association with an outcome.

    Each candidate is paired independently against the outcome on shared unit keys, so a sparse
    parameter does not shrink the sample for every other parameter (which would be a subtle way
    to lose most of the data).

    Parameters with too few paired observations are returned as INSUFFICIENT_EVIDENCE rather
    than dropped: the archer should see *"we cannot tell yet, we need 12 more shots"*, not
    silence, which reads as "nothing to see here".
    """
    if not candidates:
        return ()

    ranks: list[EffectEstimate] = []
    testable: list[tuple[str, CorrelationResult]] = []

    for key, candidate_by_unit in candidates.items():
        series, outcome_values = align_pairs(outcome_by_unit, candidate_by_unit)
        pair_count = len(series)
        if pair_count < min_n:
            ranks.append(
                EffectEstimate(
                    parameter_key=key,
                    outcome_key=outcome_key,
                    n=pair_count,
                    label=EvidenceLabel.INSUFFICIENT_EVIDENCE,
                    caveats=(
                        f"needs {min_n - pair_count} more paired observations before this can be "
                        "tested",
                    ),
                )
            )
            continue
        testable.append((key, pearson(series, outcome_values)))

    if testable:
        p_values = [c.p or 1.0 for _, c in testable]
        adjusted = q_values(p_values)
        for (key, correlation), q in zip(testable, adjusted, strict=True):
            label = claim_label_for(n=correlation.n, q=q)
            ranks.append(
                EffectEstimate(
                    parameter_key=key,
                    outcome_key=outcome_key,
                    n=correlation.n,
                    r=correlation.r,
                    p=correlation.p,
                    q=q,
                    ci_low=correlation.ci_low,
                    ci_high=correlation.ci_high,
                    label=label,
                    caveats=correlation.caveats,
                )
            )

    def sort_key(estimate: EffectEstimate) -> tuple[int, float]:
        strength = abs(estimate.r) if estimate.r is not None else -1.0
        return (
            0 if estimate.label in {EvidenceLabel.SUPPORTED, EvidenceLabel.PRELIMINARY} else 1,
            -strength,
        )

    return tuple(sorted(ranks, key=sort_key))
