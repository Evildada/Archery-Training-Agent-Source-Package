"""Statistical sensors: the gates that decide how confident the system is allowed to sound."""

from __future__ import annotations

import random

import pytest
from pydantic import ValidationError

from archery_agent.domain.enums import EvidenceLabel
from archery_agent.domain.insight import Claim
from archery_agent.sensors.stats import (
    MIN_SHOTS_FOR_EFFECT,
    Q_THRESHOLD,
    align_pairs,
    claim_label_for,
    effects,
    mad,
    mean,
    median,
    ols_trend,
    outliers_mad,
    pearson,
    percentile,
    q_values,
    sample_sd,
    summarise,
    trend_label_for,
)


def test_descriptives_against_hand_values() -> None:
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    assert mean(values) == pytest.approx(5.0)
    assert sample_sd(values) == pytest.approx(2.13809, abs=1e-5)
    assert median(values) == pytest.approx(4.5)
    assert percentile(values, 0.0) == 2.0
    assert percentile(values, 100.0) == 9.0
    assert mad([1.0, 1.0, 1.0, 1.0]) == 0.0


def test_descriptives_reject_degenerate_input() -> None:
    with pytest.raises(ValueError):
        mean([])
    with pytest.raises(ValueError):
        sample_sd([1.0])


def test_summary_reports_n_and_spread() -> None:
    summary = summarise([1.0, 2.0, 3.0, 4.0], unit="s")
    assert summary.n == 4
    assert summary.mean == pytest.approx(2.5)
    assert "s" in summary.describe()


def test_pearson_recovers_a_planted_relationship() -> None:
    rng = random.Random(11)
    x = [rng.gauss(0, 1) for _ in range(60)]
    y = [2.0 * value + rng.gauss(0, 0.4) for value in x]
    result = pearson(x, y)
    assert result.r is not None and result.r > 0.9
    assert result.p is not None and result.p < 0.001
    assert result.ci_low is not None and result.ci_low < result.r < result.ci_high  # type: ignore[operator]


def test_pearson_refuses_zero_variance() -> None:
    result = pearson([1.0] * 10, [1.0, 2.0] * 5)
    assert result.r is None
    assert "zero variance" in result.caveats[0]


def test_pearson_requires_paired_lengths() -> None:
    with pytest.raises(ValueError, match="same length"):
        pearson([1.0, 2.0], [1.0])


def test_benjamini_hochberg_matches_worked_example() -> None:
    adjusted = q_values([0.01, 0.04, 0.2, 0.5])
    assert adjusted == pytest.approx((0.04, 0.08, 0.266667, 0.5), abs=1e-5)


def test_q_values_preserve_order() -> None:
    adjusted = q_values([0.5, 0.01, 0.2, 0.04])
    assert adjusted[1] < adjusted[3] < adjusted[2] < adjusted[0]


def test_claim_labels_follow_the_documented_mapping() -> None:
    assert claim_label_for(n=None, q=None, external=True) is EvidenceLabel.GENERAL_EDUCATION
    assert claim_label_for(n=10, q=0.001) is EvidenceLabel.INSUFFICIENT_EVIDENCE
    assert claim_label_for(n=10, q=0.001, external=True) is EvidenceLabel.PRELIMINARY
    # a null result with enough data is a non-finding, not a weak signal
    assert claim_label_for(n=60, q=0.9) is EvidenceLabel.INSUFFICIENT_EVIDENCE
    assert claim_label_for(n=60, q=Q_THRESHOLD - 0.001) is EvidenceLabel.SUPPORTED


def test_trend_labels_are_stricter_than_shot_labels() -> None:
    assert trend_label_for(n_sessions=4, q=0.001) is EvidenceLabel.INSUFFICIENT_EVIDENCE
    assert trend_label_for(n_sessions=6, q=0.001) is EvidenceLabel.PRELIMINARY
    assert trend_label_for(n_sessions=11, q=0.001) is EvidenceLabel.SUPPORTED


def test_ols_trend_recovers_a_perfect_line() -> None:
    trend = ols_trend([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0])
    assert trend.slope_per_session == pytest.approx(1.0)
    assert trend.r2 == pytest.approx(1.0)
    assert trend.label is EvidenceLabel.SUPPORTED


def test_ols_trend_refuses_too_few_sessions() -> None:
    trend = ols_trend([5.0, 6.0])
    assert trend.slope_per_session is None
    assert trend.label is EvidenceLabel.INSUFFICIENT_EVIDENCE
    assert "minimum" in trend.caveats[0]


def test_effects_flags_undersampled_parameters_instead_of_dropping_them() -> None:
    outcome = {f"s{i}": 7.0 + i * 0.1 for i in range(40)}
    sparse = {f"s{i}": 3.0 for i in range(5)}
    dense = {f"s{i}": float(i % 7) for i in range(40)}
    estimates = effects(
        outcome_key="outcome.score_mean",
        outcome_by_unit=outcome,
        candidates={"cycle.hold_time_s": sparse, "tension.grip_pressure_1_5": dense},
        min_n=MIN_SHOTS_FOR_EFFECT,
    )
    labels = {e.parameter_key: e.label for e in estimates}
    assert labels["cycle.hold_time_s"] is EvidenceLabel.INSUFFICIENT_EVIDENCE
    sparse_estimate = next(e for e in estimates if e.parameter_key == "cycle.hold_time_s")
    assert "more paired observations" in sparse_estimate.caveats[0]
    assert labels["tension.grip_pressure_1_5"] is not None


def test_effects_pairs_each_candidate_independently() -> None:
    outcome = {f"s{i}": float(i) for i in range(40)}
    partial = {f"s{i}": float(i) for i in range(10, 40)}  # only 30 shared units
    estimates = effects(
        outcome_key="outcome.score_mean",
        outcome_by_unit=outcome,
        candidates={"cycle.hold_time_s": partial},
        min_n=30,
    )
    assert estimates[0].n == 30, "pairing must use only shared units, and must not fail"


def test_effects_surface_a_decoy_as_unsupported() -> None:
    rng = random.Random(3)
    outcome = {f"s{i}": rng.gauss(0, 1) for i in range(60)}
    real = {key: outcome[key] + rng.gauss(0, 0.3) for key in outcome}
    decoy = {key: rng.gauss(0, 1) for key in outcome}
    estimates = effects(
        outcome_key="outcome.score_mean",
        outcome_by_unit=outcome,
        candidates={"cycle.hold_time_s": real, "tension.grip_pressure_1_5": decoy},
        min_n=30,
    )
    by_key = {e.parameter_key: e for e in estimates}
    assert by_key["cycle.hold_time_s"].r is not None
    assert by_key["cycle.hold_time_s"].r > 0.8  # type: ignore[operator]
    assert by_key["cycle.hold_time_s"].label is EvidenceLabel.SUPPORTED
    assert by_key["tension.grip_pressure_1_5"].label is not EvidenceLabel.SUPPORTED
    assert by_key["cycle.hold_time_s"].q is not None


def test_align_pairs_uses_only_shared_units() -> None:
    outcome = {"a": 1.0, "b": 2.0, "c": 3.0}
    candidate = {"b": 20.0, "c": 30.0, "d": 40.0}
    series, outcomes = align_pairs(outcome, candidate)
    assert series == [20.0, 30.0]
    assert outcomes == [2.0, 3.0]


def test_outlier_detection_is_relative_to_the_archer() -> None:
    steady = [6.0, 6.1, 5.9, 6.0, 6.2, 5.8, 6.1, 40.0]
    flags = outliers_mad(steady)
    assert flags[-1] is True
    assert sum(flags) == 1
    assert all(flag is False for flag in outliers_mad([5.0, 5.0, 5.0]))


def test_supported_claim_requires_n_and_corrected_significance() -> None:
    with pytest.raises(ValidationError, match="cannot support a SUPPORTED claim"):
        Claim(
            statement="Hold time drives score.",
            n=12,
            q_value=0.01,
            evidence_label=EvidenceLabel.SUPPORTED,
        )
