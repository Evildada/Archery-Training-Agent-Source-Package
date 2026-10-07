"""Simulator behaviour, including the ways it is designed to refuse to answer."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from archery_agent.domain.enums import Confidence
from archery_agent.sim.arrow import (
    ArrowBuild,
    ShotContext,
    balance_point_in,
    evaluate_arrow_setup,
    foc_pct,
    optimize_arrow_setup,
    total_mass_grains,
)
from archery_agent.sim.sights import SightMark, predict_sight_mark
from archery_agent.sim.spine import SpineChart, check_spine
from archery_agent.sim.tune import TuneSymptom, advise_tuning


@pytest.fixture
def build() -> ArrowBuild:
    return ArrowBuild(
        brand="Test",
        model="Arrow",
        shaft_length_in=28.0,
        shaft_mass_grains=180.0,
        insert_mass_grains=15.0,
        point_mass_grains=100.0,
        nock_mass_grains=10.0,
        vane_mass_grains=12.0,
    )


def test_mass_is_summed_from_components_when_nothing_was_weighed(build: ArrowBuild) -> None:
    mass, confidence, notes = total_mass_grains(build)
    assert mass == pytest.approx(317.0)
    assert confidence is Confidence.ESTIMATED
    assert any("weigh a finished arrow" in note.lower() for note in notes)


def test_measured_mass_wins_over_the_catalog_sum(build: ArrowBuild) -> None:
    weighed = build.model_copy(update={"measured_total_mass_grains": 322.5})
    mass, confidence, _ = total_mass_grains(weighed)
    assert mass == pytest.approx(322.5)
    assert confidence is Confidence.MEASURED


def test_balance_point_and_foc_match_hand_calculation(build: ArrowBuild) -> None:
    # moment = 180*14 + 15*28 + 100*28 + 10*0 + 12*1.5 = 5758 ; /317 = 18.164 in
    assert balance_point_in(build) == pytest.approx(18.164, abs=0.01)
    assert foc_pct(build) == pytest.approx(14.87, abs=0.05)


def test_speed_is_refused_without_a_measurement_or_an_ibo_rating(build: ArrowBuild) -> None:
    result = evaluate_arrow_setup(build, ShotContext(draw_weight_lb=55.0, draw_length_in=28.5))
    assert result.speed_fps is None
    assert result.kinetic_energy_ft_lb is None
    assert result.speed_confidence is Confidence.INSUFFICIENT_DATA
    assert any("cannot be estimated" in note for note in result.assumptions)


def test_speed_estimate_is_labelled_and_carries_its_sensitivities(build: ArrowBuild) -> None:
    result = evaluate_arrow_setup(
        build,
        ShotContext(draw_weight_lb=55.0, draw_length_in=28.5, ibo_fps=315.0),
    )
    assert result.speed_fps is not None
    assert result.speed_confidence is Confidence.ESTIMATED
    assert result.kinetic_energy_ft_lb is not None and result.kinetic_energy_ft_lb > 0
    assert any("fps/lb" in note for note in result.assumptions), "sensitivities must be shown"


def test_chronograph_reading_overrides_the_projection(build: ArrowBuild) -> None:
    result = evaluate_arrow_setup(
        build,
        ShotContext(draw_weight_lb=55.0, draw_length_in=28.5, measured_speed_fps=281.0),
    )
    assert result.speed_fps == pytest.approx(281.0)
    assert result.speed_confidence is Confidence.MEASURED


def test_light_arrows_warn_about_dry_fire_risk(build: ArrowBuild) -> None:
    light = build.model_copy(update={"shaft_mass_grains": 120.0, "point_mass_grains": 60.0})
    result = evaluate_arrow_setup(light, ShotContext(draw_weight_lb=70.0, draw_length_in=29.0))
    assert any("gr/lb" in warning for warning in result.warnings)
    assert any("dry-fire" in warning for warning in result.warnings)


def test_optimizer_prefers_in_band_setups(build: ArrowBuild) -> None:
    heavy = build.model_copy(update={"shaft_mass_grains": 260.0})
    context = ShotContext(draw_weight_lb=55.0, draw_length_in=28.5, ibo_fps=315.0)
    ranked = optimize_arrow_setup([heavy, build], context)
    winner = ranked[0]
    assert 5.0 <= winner.grains_per_pound <= 7.0, "the in-band setup should win"
    assert winner.build.shaft_mass_grains == build.shaft_mass_grains


# ------------------------------------------------------------------------- spine


def test_spine_check_reports_direction_and_verdict() -> None:
    weaker = check_spine(draw_weight_lb=50.0, arrow_length_in=28.0, actual_spine_thou=900.0)
    assert weaker.delta_thou > 0
    assert weaker.verdict == "mismatch"
    assert weaker.as_registry_value() < 0, "registry convention: negative = stiffer"


def test_unverified_chart_forces_an_unverified_confidence() -> None:
    result = check_spine(draw_weight_lb=50.0, arrow_length_in=28.0, actual_spine_thou=520.0)
    assert result.confidence is Confidence.UNVERIFIED
    assert any("NOT SOURCED" in note for note in result.assumptions)
    assert result.verification_step, "every recommendation needs a test to confirm it"


def test_a_transposed_chart_is_rejected_at_construction() -> None:
    """A chart that says longer arrows need weaker shafts is corrupt, and must not load."""
    with pytest.raises(ValidationError, match="deflection must not increase"):
        SpineChart(
            chart_id="bad",
            manufacturer="bad",
            rows=((50.0, ((26.0, 500.0), (30.0, 700.0))),),
        )


def test_a_chart_that_gets_heavier_draw_backwards_is_rejected() -> None:
    with pytest.raises(ValidationError, match="heavier draw weight"):
        SpineChart(
            chart_id="transposed",
            manufacturer="bad",
            rows=(
                (40.0, ((26.0, 500.0), (30.0, 460.0))),
                (60.0, ((26.0, 600.0), (30.0, 560.0))),
            ),
        )


# ------------------------------------------------------------------------- sights


def _marks() -> list[SightMark]:
    return [SightMark(distance_m=18.0, mark=100.0), SightMark(distance_m=30.0, mark=140.0)]


def test_sight_mark_interpolates_between_measured_marks() -> None:
    result = predict_sight_mark(_marks(), 24.0)
    assert result.ok
    assert result.predicted_mark == pytest.approx(120.0)
    assert result.confidence is Confidence.INTERPOLATED


def test_sight_mark_refuses_far_extrapolation() -> None:
    result = predict_sight_mark(_marks(), 60.0)
    assert not result.ok
    assert "beyond the nearest measured mark" in result.warning
    assert result.verification_step


def test_sight_mark_extrapolates_a_little_but_says_so() -> None:
    result = predict_sight_mark(_marks(), 36.0)
    assert result.ok
    assert result.confidence is Confidence.ESTIMATED
    assert "outside the measured range" in result.warning


def test_sight_mark_needs_two_marks() -> None:
    result = predict_sight_mark([SightMark(distance_m=18.0, mark=100.0)], 24.0)
    assert not result.ok
    assert "two measured sight marks" in result.warning


def test_duplicate_distances_are_rejected() -> None:
    marks = [SightMark(distance_m=18.0, mark=100.0), SightMark(distance_m=18.0, mark=120.0)]
    result = predict_sight_mark(marks, 24.0)
    assert not result.ok
    assert "same distance" in result.warning


# --------------------------------------------------------------------------- tune


def test_tune_advice_is_blocked_while_execution_dominates() -> None:
    blocked = advise_tuning(TuneSymptom.HORIZONTAL_SPREAD, group_radius_cm=12.0, distance_m=18.0)
    assert not blocked.actionable
    assert "fitting noise" in blocked.blocked_by
    assert blocked.confidence is Confidence.INSUFFICIENT_DATA


def test_tune_advice_needs_enough_arrows() -> None:
    blocked = advise_tuning(TuneSymptom.PAPER_TEAR_RIGHT, arrows_observed=3)
    assert not blocked.actionable
    assert "at least 6" in blocked.blocked_by


def test_tune_advice_is_actionable_with_a_repeatable_pattern() -> None:
    advice = advise_tuning(
        TuneSymptom.PAPER_TEAR_RIGHT, arrows_observed=12, group_radius_cm=3.0, distance_m=18.0
    )
    assert advice.actionable
    assert advice.candidates
    assert advice.verification_protocol.startswith("Change ONE thing")


def test_low_risk_candidates_are_listed_first() -> None:
    advice = advise_tuning(TuneSymptom.PAPER_TEAR_RIGHT, arrows_observed=12)
    assert advice.candidates[0].risk == "low"
    assert any(c.reversible for c in advice.candidates)
