"""The SQLite store must behave *identically* to the in-memory one, and enforce append-only.

The parity tests matter more than they look: the demo and the CLI use different stores, so if the
two ever diverge, the deterministic demo silently stops being evidence about the real product.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from archery_agent.domain.entities import ArrowSetup, Bow, EquipmentSet
from archery_agent.domain.enums import ObservationSource, Reliability
from archery_agent.domain.equipment import record_version
from archery_agent.domain.ledger import ParameterObservation
from archery_agent.store.base import ObservationFilter
from archery_agent.store.memory import InMemoryLedger
from archery_agent.store.sqlite import SqliteStore, append_only_probe


@pytest.fixture
def store(tmp_path: Path) -> SqliteStore:
    with SqliteStore(tmp_path / "archery.db") as opened:
        yield opened


def _observation(key: str = "cycle.hold_time_s", value: float = 2.4, **overrides: object):
    payload: dict[str, object] = {
        "archer_id": "arc_1",
        "key": key,
        "value": value,
        "source": ObservationSource.SELF_REPORTED,
        "reliability": Reliability.LOW,
    }
    payload.update(overrides)
    return ParameterObservation.model_validate(payload)


# ------------------------------------------------------------------ append-only


def test_the_database_itself_refuses_to_rewrite_history(store: SqliteStore) -> None:
    store.append((_observation(),))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store._conn.execute("UPDATE parameter_ledger SET key = 'something.else'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store._conn.execute("DELETE FROM parameter_ledger")


def test_equipment_versions_cannot_be_edited_either(store: SqliteStore) -> None:
    version = record_version(archer_id="arc_1", equipment=_equipment())
    store.append_version(version)
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("UPDATE equipment_version SET version = 99")


def test_doctor_probe_confirms_the_guarantee(store: SqliteStore) -> None:
    """`doctor` runs this on the real database, so the claim cannot rot into a docstring."""
    notes = append_only_probe(store)
    assert "ledger update refused" in notes
    assert any("trigger(s) present" in note for note in notes)
    assert store.counts() == {"parameter_ledger": 0, "equipment_version": 0}, (
        "the probe must roll its own rows back — a diagnostic that pollutes the ledger is a bug"
    )


def test_the_probe_catches_a_database_built_without_triggers(tmp_path: Path) -> None:
    """A database from an older schema must be reported, not silently trusted."""
    path = tmp_path / "old.db"
    with SqliteStore(path) as store:
        # deliberately breaking our own guarantee, to check the probe notices
        store._conn.executescript("DROP TRIGGER parameter_ledger_no_update;")
        with pytest.raises(AssertionError, match="triggers missing"):
            append_only_probe(store)


# --------------------------------------------------------------------- parity


def test_rejections_are_identical_to_the_in_memory_store(store: SqliteStore) -> None:
    """A value outside the registry's plausible range must be refused by both, with a reason."""
    bad = _observation(value=999.0)
    sqlite_batch = store.append((bad,))
    memory_batch = InMemoryLedger().append((bad,))
    assert sqlite_batch.accepted == memory_batch.accepted == ()
    assert sqlite_batch.rejected[0]["key"] == memory_batch.rejected[0]["key"]
    assert sqlite_batch.rejected[0]["reason"] == memory_batch.rejected[0]["reason"]


def test_valid_rows_round_trip(store: SqliteStore) -> None:
    store.append((_observation(),))
    rows = store.series("cycle.hold_time_s", archer_id="arc_1")
    assert len(rows) == 1
    assert rows[0].value == pytest.approx(2.4)
    assert rows[0].reliability is Reliability.LOW


def test_duplicate_appends_do_not_duplicate_rows(store: SqliteStore) -> None:
    row = _observation()
    store.append((row,))
    store.append((row,))
    assert store.size == 1, "the same observation id must not be stored twice"


def test_snapshot_hash_is_stable_and_content_addressed(store: SqliteStore) -> None:
    store.append((_observation(),))
    first = store.snapshot_hash()
    assert first.startswith("sha256:")
    assert store.snapshot_hash() == first, "hashing must not depend on iteration order"
    store.append((_observation(key="mental.arousal_1_10", value=6.0),))
    assert store.snapshot_hash() != first, "new data must change the hash"


def test_filters_work_like_the_in_memory_store(store: SqliteStore) -> None:
    base = datetime(2026, 9, 1, tzinfo=UTC)
    for day in range(3):
        store.append((_observation(observed_at=base + timedelta(days=day)),))
    assert len(store.query(ObservationFilter(keys=("cycle.hold_time_s",)))) == 3
    assert len(store.query(ObservationFilter(since=base + timedelta(days=1)))) == 2
    assert len(store.query(ObservationFilter(limit=1))) == 1
    assert store.query(ObservationFilter(session_id="sess_none")) == ()


# ------------------------------------------------------------------- equipment


def test_versions_survive_a_restart(tmp_path: Path) -> None:
    """The whole reason the CLI uses SQLite: the history must outlive the process."""
    path = tmp_path / "archery.db"
    with SqliteStore(path) as first:
        version = record_version(archer_id="arc_1", equipment=_equipment())
        first.append_version(version)
        version_id = version.version_id

    with SqliteStore(path) as reopened:
        current = reopened.current_version("arc_1")
        assert current is not None
        assert current.version_id == version_id
        assert current.equipment.bow.brand == "Test"


def test_duplicate_version_numbers_are_refused(store: SqliteStore) -> None:
    version = record_version(archer_id="arc_1", equipment=_equipment())
    store.append_version(version)
    with pytest.raises(ValueError, match="already has equipment version"):
        store.append_version(version)


def test_history_keeps_every_version_and_the_deltas(store: SqliteStore) -> None:
    first = record_version(archer_id="arc_1", equipment=_equipment())
    store.append_version(first)
    second = record_version(
        archer_id="arc_1",
        equipment=_equipment(point_mass_grains=125.0),
        history=store.versions("arc_1"),
        reason="heavier point",
    )
    store.append_version(second)

    versions = store.versions("arc_1")
    assert [v.version for v in versions] == [1, 2]
    assert versions[0].equipment.arrow.point_mass_grains == pytest.approx(100.0)
    assert versions[1].changes[0].delta == pytest.approx(25.0)


def test_version_at_answers_about_the_past(store: SqliteStore) -> None:
    june = datetime(2026, 6, 1, tzinfo=UTC)
    august = datetime(2026, 8, 1, tzinfo=UTC)
    v1 = record_version(archer_id="arc_1", equipment=_equipment(), effective_from=june)
    store.append_version(v1)
    v2 = record_version(
        archer_id="arc_1",
        equipment=_equipment(bow_draw_weight_lb=60.0),
        history=store.versions("arc_1"),
        effective_from=august,
    )
    store.append_version(v2)

    assert store.version_at("arc_1", datetime(2026, 7, 1, tzinfo=UTC)).version == 1
    assert store.version_at("arc_1", datetime(2026, 9, 1, tzinfo=UTC)).version == 2


def test_schema_version_is_recorded(store: SqliteStore) -> None:
    """A migratable database must say which schema it is — otherwise migrations guess."""
    assert store.schema_version == 1
    assert store.counts() == {"parameter_ledger": 0, "equipment_version": 0}


def _equipment(*, bow_draw_weight_lb: float = 55.0, **arrow_overrides: object) -> EquipmentSet:
    payload: dict[str, object] = {
        "brand": "Easton",
        "model": "X10",
        "shaft_length_in": 28.5,
        "shaft_mass_grains": 180.0,
        "point_mass_grains": 100.0,
        "insert_mass_grains": 15.0,
        "nock_mass_grains": 10.0,
    }
    payload.update(arrow_overrides)
    return EquipmentSet(
        archer_id="arc_1",
        bow=Bow(
            brand="Test", model="Riser", draw_weight_lb=bow_draw_weight_lb, draw_length_in=28.5
        ),
        arrow=ArrowSetup.model_validate(payload),
    )
