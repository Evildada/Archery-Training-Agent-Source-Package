"""The setup report's contract, tested as a contract.

`docs/06-roadmap.md` M1 promises two things:

1. every claim is labelled;
2. every estimate names the one range test that would resolve it.

Both are mechanical, so both are tested mechanically. The tests deliberately include a *measured*
setup: a report that only ever passes on estimated data would not prove the labelling works, it
would prove everything gets the same label.
"""

from __future__ import annotations

import pytest

from archery_agent.domain.entities import ArrowSetup, Bow, EquipmentSet, Release
from archery_agent.domain.enums import Confidence
from archery_agent.domain.equipment import record_version
from archery_agent.sensors.setup_assessment import (
    NEEDS_A_TEST,
    Finding,
    audit_setup_report,
    build_setup_report,
    combine,
)
from archery_agent.sim.arrow import ShotContext
from archery_agent.sim.sights import SightMark


def _version(**arrow_overrides: object):
    bow = Bow(
        brand="Test", model="Riser", draw_weight_lb=55.0, let_off_pct=80.0, draw_length_in=28.5
    )
    payload: dict[str, object] = {
        "brand": "Easton",
        "model": "X10",
        "shaft_spine_thou": 340.0,
        "shaft_length_in": 28.5,
        "shaft_mass_grains": 180.0,
        "point_mass_grains": 100.0,
        "insert_mass_grains": 15.0,
        "nock_mass_grains": 10.0,
    }
    payload.update(arrow_overrides)
    equipment = EquipmentSet(
        archer_id="arc_1",
        bow=bow,
        release=Release(release_type="thumb_button", brand="T", model="R"),
        arrow=ArrowSetup.model_validate(payload),
    )
    return record_version(archer_id="arc_1", equipment=equipment)


# --------------------------------------------------------------- the honesty contract


def test_every_estimate_names_a_test() -> None:
    report = build_setup_report(
        _version(), shot=ShotContext(draw_weight_lb=55.0, draw_length_in=28.5, ibo_fps=315.0)
    )
    for finding in report.findings:
        assert finding.basis, f"{finding.subject} has no basis"
        if finding.confidence in NEEDS_A_TEST:
            assert finding.confirming_test, (
                f"{finding.subject} is {finding.confidence} with no test"
            )


def test_the_report_passes_its_own_audit() -> None:
    report = build_setup_report(
        _version(), shot=ShotContext(draw_weight_lb=55.0, draw_length_in=28.5, ibo_fps=315.0)
    )
    audit = audit_setup_report(report)
    assert audit.ok, [issue.message for issue in audit.errors]


def test_a_finding_without_a_test_cannot_be_constructed() -> None:
    """The rule is enforced where a finding is made, not only where it is reviewed."""
    from archery_agent.sensors.setup_assessment import _finding

    with pytest.raises(ValueError, match="no confirming test"):
        _finding(
            subject="arrow.speed_fps",
            statement="Arrow speed",
            value=300.0,
            unit="fps",
            confidence=Confidence.ESTIMATED,
            basis="IBO projection",
        )


def test_a_finding_without_a_basis_cannot_be_constructed() -> None:
    from archery_agent.sensors.setup_assessment import _finding

    with pytest.raises(ValueError, match="no basis"):
        _finding(
            subject="arrow.speed_fps",
            statement="Arrow speed",
            value=300.0,
            confidence=Confidence.MEASURED,
            basis="",
        )


def test_the_audit_catches_an_untestable_claim_that_got_through() -> None:
    """Belt and braces: the sensor must fail a report built by hand, not just bless good ones."""
    report = build_setup_report(_version())
    sneaky = report.model_copy(
        update={
            "findings": (
                Finding(
                    subject="arrow.speed_fps",
                    statement="Arrow speed",
                    value=999.0,
                    confidence=Confidence.ESTIMATED,
                    basis="a hunch",
                ),
            )
        }
    )
    audit = audit_setup_report(sneaky)
    assert not audit.ok
    assert any(issue.code == "untestable_claim" for issue in audit.errors)


# ------------------------------------------------------------------- the labels differ


def test_a_weighed_arrow_is_labelled_measured_and_needs_no_test() -> None:
    report = build_setup_report(_version(measured_total_mass_grains=312.0))
    mass = next(f for f in report.findings if f.subject == "arrow.total_mass_grains")
    assert mass.confidence is Confidence.MEASURED
    assert mass.confirming_test == ""
    assert mass.value == pytest.approx(312.0)


def test_an_unweighed_arrow_is_labelled_estimated_and_names_the_scale() -> None:
    report = build_setup_report(_version())
    mass = next(f for f in report.findings if f.subject == "arrow.total_mass_grains")
    assert mass.confidence is Confidence.ESTIMATED
    assert "grain scale" in mass.confirming_test


def test_the_chart_based_spine_verdict_is_not_dressed_up_as_a_measurement() -> None:
    """The default spine chart is a flagged placeholder; the report must not sound certain."""
    report = build_setup_report(_version())
    spine = next(f for f in report.findings if f.subject == "arrow.spine_fit_delta")
    assert spine.confidence in {Confidence.UNVERIFIED, Confidence.ESTIMATED}
    assert spine.confirming_test


def test_no_speed_is_a_statement_about_missing_data_not_a_guess() -> None:
    """Without an IBO rating or a chronograph there must be no speed finding at all."""
    report = build_setup_report(_version())
    assert not [f for f in report.findings if f.subject == "arrow.speed_fps"]
    assert not [f for f in report.findings if f.subject == "arrow.ke_ftlb"]
    assert any("not reported" in w and "IBO" in w for w in report.warnings), (
        "the report must say what is missing and what to supply, not silently omit the section"
    )


def test_a_chronograph_reading_makes_speed_measured() -> None:
    report = build_setup_report(
        _version(),
        shot=ShotContext(draw_weight_lb=55.0, draw_length_in=28.5, measured_speed_fps=291.0),
    )
    speed = next(f for f in report.findings if f.subject == "arrow.speed_fps")
    assert speed.confidence is Confidence.MEASURED
    assert speed.value == pytest.approx(291.0)


def test_confidence_propagates_from_the_weakest_input() -> None:
    assert combine(Confidence.MEASURED, Confidence.ESTIMATED) is Confidence.ESTIMATED
    assert combine(Confidence.MEASURED, Confidence.MEASURED) is Confidence.MEASURED
    assert combine(Confidence.DERIVED, Confidence.UNVERIFIED) is Confidence.UNVERIFIED


def test_derived_energy_is_as_weak_as_its_weakest_input() -> None:
    """A chronograph does not make kinetic energy measured — the mass has to be weighed too."""
    estimated_speed = build_setup_report(
        _version(), shot=ShotContext(draw_weight_lb=55.0, draw_length_in=28.5, ibo_fps=315.0)
    )
    ke = next(f for f in estimated_speed.findings if f.subject == "arrow.ke_ftlb")
    assert ke.confidence in NEEDS_A_TEST

    measured_speed_only = build_setup_report(
        _version(),
        shot=ShotContext(draw_weight_lb=55.0, draw_length_in=28.5, measured_speed_fps=291.0),
    )
    ke_half = next(f for f in measured_speed_only.findings if f.subject == "arrow.ke_ftlb")
    assert ke_half.confidence is Confidence.ESTIMATED, "the arrow was still never weighed"
    assert "grain scale" in ke_half.confirming_test, "so the mass is what needs measuring next"

    both_measured = build_setup_report(
        _version(measured_total_mass_grains=312.0),
        shot=ShotContext(draw_weight_lb=55.0, draw_length_in=28.5, measured_speed_fps=291.0),
    )
    ke_both = next(f for f in both_measured.findings if f.subject == "arrow.ke_ftlb")
    assert ke_both.confidence is Confidence.MEASURED
    assert ke_both.confirming_test == ""


# ------------------------------------------------------------------- usable output


def test_identical_tests_are_reported_once() -> None:
    """One weigh-in settles mass, FOC and grains per pound. Say it once."""
    report = build_setup_report(_version())
    tests = report.tests_to_run
    assert len(tests) == len({test for test, _ in tests})
    weigh = next(subjects for test, subjects in tests if "grain scale" in test)
    assert "arrow.total_mass_grains" in weigh


def test_render_shows_the_label_and_the_test_for_every_line() -> None:
    rendered = build_setup_report(
        _version(), shot=ShotContext(draw_weight_lb=55.0, draw_length_in=28.5, ibo_fps=315.0)
    ).render()
    assert "[estimated]" in rendered
    assert "grain scale" in rendered
    assert "Not answerable yet" in rendered


def test_experiments_say_what_they_would_unlock() -> None:
    report = build_setup_report(_version())
    for experiment in report.experiments:
        assert experiment.needs.strip()
        assert experiment.unlocks.strip()
    questions = " ".join(e.question for e in report.experiments)
    assert "scoring better" in questions, "the question the archer actually has must be listed"


def test_a_second_version_unlocks_the_comparison_experiment() -> None:
    first = _version()
    second = _version(point_mass_grains=125.0)
    second = second.model_copy(update={"version": 2})
    report = build_setup_report(second, history=[first, second])
    assert not any("Which of my past setups" in e.question for e in report.experiments)


def test_sight_marks_produce_an_interpolation_not_a_promise() -> None:
    marks = (
        SightMark(distance_m=18.0, mark=100.0),
        SightMark(distance_m=30.0, mark=140.0),
    )
    report = build_setup_report(_version(), sight_marks=marks)
    finding = next(f for f in report.findings if f.subject == "sight.mark_prediction")
    assert finding.confidence is Confidence.INTERPOLATED
    assert finding.confirming_test


def test_the_report_refuses_to_invent_a_setup() -> None:
    """An incomplete arrow must produce a warning, not a fabricated mass."""
    version = _version(shaft_mass_grains=None, shaft_length_in=None)
    report = build_setup_report(version)
    assert any("not complete enough" in w for w in report.warnings)
    assert not [f for f in report.findings if f.subject == "arrow.foc_pct"]
