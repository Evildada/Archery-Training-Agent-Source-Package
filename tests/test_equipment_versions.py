"""Equipment history: append-only, dated, and honest about what changed.

The property under test is *not* "the code works" — it is "a coach can still ask what was on the
bow in June". That question is only answerable if nothing is ever overwritten.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from archery_agent.domain.entities import ArrowSetup, Bow, EquipmentSet, Release
from archery_agent.domain.equipment import (
    EquipmentVersion,
    diff_equipment,
    next_version,
    record_version,
    versions_as_of,
)


def _bow(**overrides: object) -> Bow:
    payload: dict[str, object] = {
        "brand": "Test",
        "model": "Riser",
        "draw_weight_lb": 55.0,
        "let_off_pct": 80.0,
        "draw_length_in": 28.5,
    }
    payload.update(overrides)
    return Bow.model_validate(payload)


def _arrow(**overrides: object) -> ArrowSetup:
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
    payload.update(overrides)
    return ArrowSetup.model_validate(payload)


def _setup(bow: Bow | None = None, arrow: ArrowSetup | None = None) -> EquipmentSet:
    return EquipmentSet(archer_id="arc_1", bow=bow or _bow(), arrow=arrow or _arrow(), release=None)


# ------------------------------------------------------------------- versioning


def test_first_version_has_no_changes_to_report() -> None:
    """A first setup did not 'change' from anything, and the report must not pretend it did."""
    version = record_version(archer_id="arc_1", equipment=_setup(), reason="initial")
    assert version.version == 1
    assert version.changes == ()
    assert version.supersedes is None
    assert version.describe_changes() == "first recorded setup"


def test_a_change_produces_a_signed_delta() -> None:
    first = record_version(archer_id="arc_1", equipment=_setup())
    second = record_version(
        archer_id="arc_1",
        equipment=_setup(arrow=_arrow(point_mass_grains=125.0)),
        history=[first],
        reason="heavier point",
    )
    assert second.version == 2
    assert second.supersedes == first.version_id
    assert len(second.changes) == 1
    change = second.changes[0]
    assert change.field == "arrow.point_mass_grains"
    assert change.delta == pytest.approx(25.0)
    assert "25.00" in change.describe()


def test_the_previous_version_is_untouched() -> None:
    """The whole point. A later change must not rewrite an earlier record."""
    first = record_version(archer_id="arc_1", equipment=_setup())
    record_version(
        archer_id="arc_1",
        equipment=_setup(bow=_bow(draw_weight_lb=60.0)),
        history=[first],
    )
    assert first.equipment.bow.draw_weight_lb == 55.0
    assert first.changes == ()


def test_row_ids_never_appear_in_a_change_list() -> None:
    """Two versions of the same arrow with a heavier point is not 'you replaced your arrow'."""
    first = record_version(archer_id="arc_1", equipment=_setup())
    second = record_version(archer_id="arc_1", equipment=_setup(), history=[first])
    assert second.changes == (), "identical equipment must produce an empty change list, not ids"


def test_dropping_a_component_reads_as_a_change() -> None:
    first = record_version(
        archer_id="arc_1", equipment=_setup(arrow=_arrow(point_mass_grains=125.0))
    )
    second = record_version(
        archer_id="arc_1", equipment=_setup(arrow=_arrow(point_mass_grains=100.0)), history=[first]
    )
    change = second.changes[0]
    assert change.delta == pytest.approx(-25.0)
    assert change.new_value == "100.0"


def test_versions_are_dense_and_monotonic() -> None:
    versions: list[EquipmentVersion] = []
    for weight in (50.0, 55.0, 60.0):
        versions.append(
            record_version(
                archer_id="arc_1",
                equipment=_setup(bow=_bow(draw_weight_lb=weight)),
                history=versions,
            )
        )
    assert [version.version for version in versions] == [1, 2, 3]
    assert next_version(versions) == 4


def test_diff_of_nothing_is_empty_even_for_a_full_build() -> None:
    assert diff_equipment(None, record_version(archer_id="arc_1", equipment=_setup())) == ()


def test_a_release_swing_is_recorded_like_any_other_change() -> None:
    first = record_version(archer_id="arc_1", equipment=_setup())
    with_release = _setup()
    with_release = with_release.model_copy(
        update={"release": Release(release_type="hinge", brand="Test", model="H")}
    )
    second = record_version(archer_id="arc_1", equipment=with_release, history=[first])
    assert any(change.field == "release.release_type" for change in second.changes)


# ----------------------------------------------------------------- historical query


def test_the_past_stays_answerable() -> None:
    """`versions_as_of` is the question a coach actually asks: 'what was he shooting in June?'"""
    june = datetime(2026, 6, 1, tzinfo=UTC)
    august = datetime(2026, 8, 1, tzinfo=UTC)

    v1 = record_version(
        archer_id="arc_1", equipment=_setup(), effective_from=june, reason="season start"
    )
    v2 = record_version(
        archer_id="arc_1",
        equipment=_setup(bow=_bow(draw_weight_lb=60.0)),
        history=[v1],
        effective_from=august,
        reason="heavier limbs",
    )

    assert versions_as_of([v1, v2], datetime(2026, 7, 15, tzinfo=UTC)).version == 1
    assert versions_as_of([v1, v2], datetime(2026, 9, 1, tzinfo=UTC)).version == 2
    assert versions_as_of([v1, v2], datetime(2026, 5, 1, tzinfo=UTC)) is None


def test_effective_date_can_be_in_the_past() -> None:
    """Typing in a change that already happened must not corrupt the history's timeline."""
    march = datetime(2026, 3, 1, tzinfo=UTC)
    version = record_version(archer_id="arc_1", equipment=_setup(), effective_from=march)
    assert version.effective_from == march
    assert version.recorded_at > march, "recorded_at is when it was typed; effective_from is when"


def test_future_dated_version_does_not_preempt_the_present() -> None:
    now = datetime(2026, 10, 8, tzinfo=UTC)
    v1 = record_version(archer_id="arc_1", equipment=_setup(), effective_from=now)
    v2 = record_version(
        archer_id="arc_1",
        equipment=_setup(bow=_bow(draw_weight_lb=60.0)),
        history=[v1],
        effective_from=now + timedelta(days=30),
    )
    assert versions_as_of([v1, v2], now).version == 1


# ------------------------------------------------------------------ the ledger bridge


def test_versions_publish_to_the_ledger_with_their_own_id() -> None:
    """Without this the statistics cannot see which setup produced which arrows."""
    version = record_version(archer_id="arc_1", equipment=_setup())
    rows = version.ledger_observations()
    keys = {row.key for row in rows}
    assert "arrow.total_mass_grains" in keys
    assert "bow.draw_weight_lb" in keys
    assert all(row.equipment_set_id == version.version_id for row in rows)
    assert all(row.archer_id == "arc_1" for row in rows)


def test_measured_mass_wins_over_the_component_sum() -> None:
    version = record_version(
        archer_id="arc_1",
        equipment=_setup(arrow=_arrow(measured_total_mass_grains=312.5)),
    )
    mass_row = next(
        row for row in version.ledger_observations() if row.key == "arrow.total_mass_grains"
    )
    assert float(mass_row.value) == pytest.approx(312.5)


def test_ledger_rows_carry_the_effective_date_not_the_type_in_date() -> None:
    march = datetime(2026, 3, 1, tzinfo=UTC)
    version = record_version(archer_id="arc_1", equipment=_setup(), effective_from=march)
    assert all(row.observed_at == march for row in version.ledger_observations())


def test_unweighed_arrow_is_not_claimed_as_weighed() -> None:
    version = record_version(archer_id="arc_1", equipment=_setup())
    assert version.equipment.arrow.is_weighed is False
    assert version.equipment.arrow.effective_total_mass_grains() == pytest.approx(305.0)

    weighed = record_version(
        archer_id="arc_1",
        equipment=_setup(arrow=_arrow(measured_total_mass_grains=310.0)),
    )
    assert weighed.equipment.arrow.is_weighed is True
