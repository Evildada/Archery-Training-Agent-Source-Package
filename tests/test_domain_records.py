"""Domain record validation: the typo guards that protect the ledger from bad entries."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from archery_agent.domain.entities import (
    Archer,
    ArrowSetup,
    Environment,
    Session,
    Shot,
    canonical_compound_template,
)
from archery_agent.domain.enums import ObservationSource, Reliability, SessionMode
from archery_agent.domain.ledger import ParameterObservation


def test_compound_only_scope_is_enforced_by_the_type() -> None:
    with pytest.raises(ValidationError) as excinfo:
        Archer(display_name="Test", bow_type="recurve")  # type: ignore[arg-type]
    assert "compound" in str(excinfo.value).lower()


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValidationError, match="naive"):
        Session(
            archer_id="arc_1",
            mode=SessionMode.SCORING,
            distance_m=18.0,
            target_face_id="WA_40CM_3SPOT_V",
            started_at=datetime(2026, 1, 1, 12, 0),  # no tzinfo
        )


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Archer(display_name="Test", favourite_colour="blue")  # type: ignore[call-arg]


def test_scored_session_cannot_use_a_blank_bale() -> None:
    with pytest.raises(ValidationError, match="blank-bale"):
        Session(
            archer_id="arc_1",
            mode=SessionMode.SCORING,
            distance_m=18.0,
            target_face_id="BLANK_BALE",
        )


def test_half_recorded_shot_position_is_rejected() -> None:
    with pytest.raises(ValidationError, match="both horizontal and vertical"):
        Shot(end_id="end_1", index=1, ring=10, horizontal_offset_cm=1.2)


def test_shot_score_value_handles_x_and_miss() -> None:
    assert Shot(end_id="end_1", index=1, ring=10, is_x=True).score_value == 10
    assert Shot(end_id="end_1", index=1, is_miss=True).score_value == 0
    assert Shot(end_id="end_1", index=1).score_value == 0  # unscored


def test_measured_mass_must_exceed_shaft_mass() -> None:
    with pytest.raises(ValidationError, match="cannot be less than shaft mass"):
        ArrowSetup(
            brand="X",
            model="Y",
            shaft_mass_grains=200.0,
            measured_total_mass_grains=150.0,
        )


def test_environment_ranges_are_physical() -> None:
    with pytest.raises(ValidationError):
        Environment(temperature_c=200.0)


# ------------------------------------------------------------------- ledger rows


def test_observation_inherits_the_registry_unit() -> None:
    observation = ParameterObservation(archer_id="arc_1", key="cycle.hold_time_s", value=3.1)
    assert observation.unit == "s"


def test_observation_rejects_a_wrong_unit() -> None:
    with pytest.raises(ValidationError, match="registered in 's'"):
        ParameterObservation(archer_id="arc_1", key="cycle.hold_time_s", value=3.1, unit="min")


def test_observation_rejects_an_unknown_parameter_with_suggestions() -> None:
    with pytest.raises(KeyError, match=r"cycle\.hold_time_s"):
        ParameterObservation(archer_id="arc_1", key="cycle.hold.time", value=3.1)


def test_observation_type_matches_the_registry_kind() -> None:
    with pytest.raises(ValidationError, match="boolean"):
        ParameterObservation(archer_id="arc_1", key="mental.target_panic_flag", value=3.0)
    with pytest.raises(ValidationError, match="numeric"):
        ParameterObservation(archer_id="arc_1", key="cycle.hold_time_s", value="long")


def test_self_reported_ordinal_cannot_claim_high_reliability() -> None:
    with pytest.raises(ValidationError, match="reliability=high"):
        ParameterObservation(
            archer_id="arc_1",
            key="tension.back_tension_1_5",
            value=4.0,
            source=ObservationSource.SELF_REPORTED,
            reliability=Reliability.HIGH,
        )


def test_outcome_rows_require_context() -> None:
    """A group size without a distance and a face is not a measurement, it is a number."""
    from archery_agent.sensors.validators import validate_parameter_observation

    row = ParameterObservation(
        archer_id="arc_1",
        key="outcome.group_radius_cm",
        value=6.2,
        source=ObservationSource.DERIVED,
    )
    result = validate_parameter_observation(row)
    assert not result.ok
    assert {issue.code for issue in result.errors} == {
        "outcome_without_distance",
        "outcome_without_face",
    }


# --------------------------------------------------------------------- template


def test_canonical_template_covers_the_whole_cycle_in_order() -> None:
    template = canonical_compound_template()
    phases = template.ordered_phases
    assert len(phases) == 7
    assert [p.order for p in phases] == list(range(1, 8))
    assert phases[0].phase_key == "routine"
    assert phases[-1].phase_key == "follow_through"
    for phase in phases:
        assert phase.definition, f"{phase.phase_key} has no definition to teach from"


def test_template_rejects_parameters_that_are_not_registered() -> None:
    from archery_agent.domain.entities import CyclePhase

    with pytest.raises(KeyError, match="registry"):
        CyclePhase(
            phase_key="draw",
            order=1,
            name="Draw",
            definition="Draw the bow.",
            observe_params=("cycle.draw_speed",),
        )
