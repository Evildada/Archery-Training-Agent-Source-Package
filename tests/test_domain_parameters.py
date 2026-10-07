"""The parameter registry is the vocabulary of the system; these tests protect its invariants."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from archery_agent.domain.enums import CaptureCost, ParameterCategory, ParameterKind
from archery_agent.domain.parameters import (
    REGISTRY,
    UNIT_SUFFIXES,
    UnknownParameterError,
    by_category,
    get,
    low_capture_cost,
    validate_registry,
)


def test_registry_is_internally_consistent() -> None:
    validate_registry()


def test_registry_has_substantial_coverage() -> None:
    assert len(REGISTRY) >= 60, "the brief's 'parameters affecting the cycle' need real coverage"
    for category in ParameterCategory:
        assert by_category(category), f"no parameters registered for category {category}"


def test_units_live_in_key_names() -> None:
    """A parameter whose key says one unit and declares another is a bug the tests must catch."""
    for key, definition in REGISTRY.items():
        if definition.unit is None:
            continue
        matching = [unit for suffix, unit in UNIT_SUFFIXES.items() if key.endswith(suffix)]
        assert definition.unit in matching, (
            f"{key} declares {definition.unit} but the key disagrees"
        )


def test_unit_mismatch_is_rejected_at_definition_time() -> None:
    from archery_agent.domain.parameters import ParameterDefinition

    with pytest.raises(ValidationError, match="unit"):
        ParameterDefinition(
            key="cycle.hold_time_s",
            label="Hold time",
            category=ParameterCategory.CYCLE_TIMING,
            unit="min",  # lie: the key says seconds
            kind=ParameterKind.RATIO,
        )


def test_band_metrics_must_declare_a_target_band() -> None:
    from archery_agent.domain.parameters import ParameterDefinition

    with pytest.raises(ValidationError, match="target_band"):
        ParameterDefinition(
            key="cycle.hold_time_s",
            label="Hold time",
            category=ParameterCategory.CYCLE_TIMING,
            unit="s",
            kind=ParameterKind.RATIO,
            better="band",  # type: ignore[arg-type]
        )


def test_ordinals_must_document_their_scale() -> None:
    for definition in REGISTRY.values():
        if definition.kind is ParameterKind.ORDINAL:
            assert definition.scale_anchor, f"{definition.key} has no documented scale"
            assert definition.plausible_range is not None


def test_unknown_key_error_is_actionable() -> None:
    with pytest.raises(UnknownParameterError) as excinfo:
        get("cycle.holdtime_s")
    message = str(excinfo.value)
    assert "registry-versioned" in message
    assert "cycle.hold_time_s" in message, "the error should suggest the near-miss key"


def test_low_capture_cost_subset_is_practical() -> None:
    cheap = {d.key for d in low_capture_cost(CaptureCost.LOW)}
    assert "cycle.hold_time_s" in cheap
    assert "arrow.speed_fps" not in cheap, "a chronograph reading is not a cheap capture"


def test_derived_parameters_are_free() -> None:
    """Anything nobody has to measure must not claim to cost the archer anything."""
    for definition in REGISTRY.values():
        if definition.source_kinds and all(
            source.value == "derived" for source in definition.source_kinds
        ):
            assert definition.capture_cost is CaptureCost.FREE, definition.key


def test_outcome_parameters_exist() -> None:
    """Without dependent variables there is no regression to build (the brief's core belief)."""
    outcomes = by_category(ParameterCategory.OUTCOME)
    assert any(d.key == "outcome.score_mean" for d in outcomes)
    assert any(d.key == "outcome.group_radius_cm" for d in outcomes)
