"""SQLite implementation of the ledger and the equipment history.

Two things make this more than "a table with a JSON column":

**Append-only is enforced by the database, not by convention.** Both tables carry triggers that
abort any UPDATE or DELETE. A future contributor who writes a "fix the typo" statement gets a
SQLite error rather than a silent rewrite of history — and the ledger's whole value proposition is
that a value recorded in March still reads the same way in December.

**The write path runs the same sensors as the in-memory store.** `append()` validates through
`validate_parameter_observation` before committing, and returns the rejections rather than raising
them, because the capture flow has to be able to tell the archer *which* number was refused and
why. The two implementations are intentionally interchangeable: `tests/test_store_and_tools.py`
runs the same assertions against both.

Values are stored in typed columns where they are queried (`key`, `observed_at`, `archer_id`) and
as JSON elsewhere. That keeps the common query fast without turning the schema into a mirror of
the Pydantic model — the model stays the source of truth for what a row *is*.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from archery_agent.domain.equipment import EquipmentVersion, latest
from archery_agent.domain.ledger import ObservationBatch, ParameterObservation
from archery_agent.sensors.validators import validate_parameter_observation
from archery_agent.store.base import ObservationFilter

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS parameter_ledger (
    observation_id TEXT PRIMARY KEY,
    archer_id      TEXT NOT NULL,
    key            TEXT NOT NULL,
    observed_at    TEXT NOT NULL,
    session_id     TEXT,
    value_json     TEXT NOT NULL,
    payload_json   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ledger_archer_key_time
    ON parameter_ledger (archer_id, key, observed_at);

CREATE TABLE IF NOT EXISTS equipment_version (
    version_id   TEXT PRIMARY KEY,
    archer_id    TEXT NOT NULL,
    version      INTEGER NOT NULL,
    effective_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE (archer_id, version)
);

CREATE INDEX IF NOT EXISTS idx_equipment_archer_time
    ON equipment_version (archer_id, effective_at);

-- Append-only, enforced where it cannot be bypassed: the records a training log is built on are
-- never edited in place. A correction is a new row with a note (store/base.py).
CREATE TRIGGER IF NOT EXISTS parameter_ledger_no_update
BEFORE UPDATE ON parameter_ledger
BEGIN
    SELECT RAISE(ABORT, 'the parameter ledger is append-only: record a corrected row instead');
END;

CREATE TRIGGER IF NOT EXISTS parameter_ledger_no_delete
BEFORE DELETE ON parameter_ledger
BEGIN
    SELECT RAISE(ABORT, 'the parameter ledger is append-only: history is never deleted');
END;

CREATE TRIGGER IF NOT EXISTS equipment_version_no_update
BEFORE UPDATE ON equipment_version
BEGIN
    SELECT RAISE(ABORT, 'equipment versions are history: record a new version instead');
END;

CREATE TRIGGER IF NOT EXISTS equipment_version_no_delete
BEFORE DELETE ON equipment_version
BEGIN
    SELECT RAISE(ABORT, 'equipment versions are history: they are retired by a new version');
END;
"""


class SqliteStore:
    """Implements :class:`LedgerStore` and :class:`EquipmentStore` over one database file."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if self.path.parent and str(self.path.parent) not in ("", "."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )
        self._conn.commit()

    # ------------------------------------------------------------------ plumbing
    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        cursor = self._conn.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SqliteStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @property
    def schema_version(self) -> int:
        with self._cursor() as cursor:
            cursor.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'")
            row = cursor.fetchone()
        return int(row["value"]) if row else 0

    # ------------------------------------------------------------------- ledger
    def append(self, observations: tuple[ParameterObservation, ...]) -> ObservationBatch:
        accepted: list[ParameterObservation] = []
        rejected: list[dict[str, str]] = []
        warnings: list[str] = []

        for observation in observations:
            result = validate_parameter_observation(observation)
            if not result.ok:
                for issue in result.errors:
                    rejected.append(
                        {
                            "key": observation.key,
                            "value": str(observation.value),
                            "reason": issue.message,
                            "suggestion": issue.suggestion,
                        }
                    )
                continue
            warnings.extend(issue.message for issue in result.warnings)
            accepted.append(observation)

        with self._cursor() as cursor:
            for observation in accepted:
                cursor.execute(
                    "INSERT OR IGNORE INTO parameter_ledger "
                    "(observation_id, archer_id, key, observed_at, session_id, value_json, "
                    " payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        observation.observation_id,
                        observation.archer_id,
                        observation.key,
                        observation.observed_at.isoformat(),
                        observation.session_id,
                        json.dumps(observation.value),
                        observation.model_dump_json(),
                    ),
                )
            self._conn.commit()

        return ObservationBatch(
            accepted=tuple(accepted), rejected=tuple(rejected), warnings=tuple(warnings)
        )

    def query(self, filt: ObservationFilter) -> tuple[ParameterObservation, ...]:
        clauses: list[str] = []
        params: list[Any] = []
        if filt.archer_id is not None:
            clauses.append("archer_id = ?")
            params.append(filt.archer_id)
        if filt.keys:
            clauses.append(f"key IN ({','.join('?' * len(filt.keys))})")
            params.extend(filt.keys)
        if filt.session_id is not None:
            clauses.append("session_id = ?")
            params.append(filt.session_id)
        if filt.since is not None:
            clauses.append("observed_at >= ?")
            params.append(filt.since.isoformat())
        if filt.until is not None:
            clauses.append("observed_at <= ?")
            params.append(filt.until.isoformat())

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order = "ORDER BY observed_at ASC"
        with self._cursor() as cursor:
            cursor.execute(
                f"SELECT payload_json FROM parameter_ledger {where} {order}",
                params,
            )
            rows = [ParameterObservation.model_validate_json(r["payload_json"]) for r in cursor]

        # Filters the SQL schema does not model are applied in Python, on the same objects the
        # in-memory store would return, so the two cannot drift.
        if filt.end_id is not None:
            rows = [r for r in rows if r.end_id == filt.end_id]
        if filt.sources:
            rows = [r for r in rows if r.source in filt.sources]
        if filt.distance_m is not None:
            rows = [r for r in rows if r.distance_m == filt.distance_m]
        if filt.limit is not None:
            rows = rows[-filt.limit :]
        return tuple(rows)

    def series(self, key: str, *, archer_id: str | None = None) -> tuple[ParameterObservation, ...]:
        return self.query(ObservationFilter(keys=(key,), archer_id=archer_id))

    @property
    def size(self) -> int:
        with self._cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM parameter_ledger")
            return int(cursor.fetchone()["n"])

    def snapshot_hash(self) -> str:
        """Stable hash of the current ledger contents — stamped onto every generated insight."""
        digest = hashlib.sha256()
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT observation_id, archer_id, key, value_json, observed_at "
                "FROM parameter_ledger ORDER BY observed_at, observation_id"
            )
            for row in cursor:
                digest.update(
                    f"{row['observation_id']}|{row['archer_id']}|{row['key']}|"
                    f"{row['value_json']}|{row['observed_at']}\n".encode()
                )
        return f"sha256:{digest.hexdigest()[:32]}"

    # ---------------------------------------------------------------- equipment
    def append_version(self, version: EquipmentVersion) -> EquipmentVersion:
        """Record one equipment version. Duplicate (archer, version) is a programming error."""
        try:
            with self._cursor() as cursor:
                cursor.execute(
                    "INSERT INTO equipment_version "
                    "(version_id, archer_id, version, effective_at, payload_json) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        version.version_id,
                        version.archer_id,
                        version.version,
                        version.effective_from.isoformat(),
                        version.model_dump_json(),
                    ),
                )
                self._conn.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                f"{version.archer_id} already has equipment version {version.version}. "
                "Versions are dense and monotonic: ask for the next one via "
                "domain.equipment.record_version rather than inventing a number."
            ) from exc
        return version

    def versions(self, archer_id: str) -> tuple[EquipmentVersion, ...]:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT payload_json FROM equipment_version WHERE archer_id = ? "
                "ORDER BY version ASC, effective_at ASC",
                (archer_id,),
            )
            return tuple(
                EquipmentVersion.model_validate_json(row["payload_json"]) for row in cursor
            )

    def current_version(self, archer_id: str) -> EquipmentVersion | None:
        return latest(self.versions(archer_id))

    def version_at(self, archer_id: str, moment: datetime) -> EquipmentVersion | None:
        from archery_agent.domain.equipment import versions_as_of

        return versions_as_of(self.versions(archer_id), moment)

    # ------------------------------------------------------------------ utility
    def counts(self) -> dict[str, int]:
        """Row counts per table. Used by `doctor` and by the migration tests."""
        with self._cursor() as cursor:
            return {
                name: int(cursor.execute(f"SELECT COUNT(*) AS n FROM {name}").fetchone()["n"])
                for name in ("parameter_ledger", "equipment_version")
            }


#: The triggers that make the two tables append-only. Named here so the probe can check the
#: *schema* rather than trusting that the DDL above still contains them.
APPEND_ONLY_TRIGGERS: tuple[str, ...] = (
    "parameter_ledger_no_update",
    "parameter_ledger_no_delete",
    "equipment_version_no_update",
    "equipment_version_no_delete",
)


def append_only_probe(store: SqliteStore) -> Sequence[str]:
    """Check that history really cannot be rewritten, and report what was tried.

    Two subtleties this function exists to handle, both of which made an earlier version of it
    pass while proving nothing:

    * a ``BEFORE UPDATE`` trigger only fires **per row**, so probing an empty table silently
      succeeds. The probe therefore inserts its own row inside a transaction;
    * the row must not survive the probe, so everything is rolled back — a diagnostic that
      pollutes the archer's ledger would be its own kind of bug.

    The trigger names are checked against ``sqlite_master`` as well, which catches a database
    created by an older schema before the triggers existed.
    """
    notes: list[str] = []

    present = {
        row["name"]
        for row in store._conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")
    }
    missing = sorted(set(APPEND_ONLY_TRIGGERS) - present)
    if missing:
        raise AssertionError(
            f"append-only triggers missing from this database: {missing}. It was created by an "
            "older schema; rebuild it or run the migration before trusting its history."
        )
    notes.append(f"{len(APPEND_ONLY_TRIGGERS)} append-only trigger(s) present")

    started_transaction = not store._conn.in_transaction
    if started_transaction:
        store._conn.execute("BEGIN")
    try:
        store._conn.execute(
            "INSERT INTO parameter_ledger "
            "(observation_id, archer_id, key, observed_at, session_id, value_json, payload_json) "
            "VALUES ('__probe__', '__probe__', 'cycle.hold_time_s', 'now', NULL, '0', '{}')"
        )
        store._conn.execute(
            "INSERT INTO equipment_version "
            "(version_id, archer_id, version, effective_at, payload_json) "
            "VALUES ('__probe__', '__probe__', 999999, 'now', '{}')"
        )
        for statement, expected in (
            ("UPDATE parameter_ledger SET key = 'x'", "ledger update refused"),
            ("DELETE FROM parameter_ledger", "ledger delete refused"),
            ("UPDATE equipment_version SET version = 99", "equipment update refused"),
            ("DELETE FROM equipment_version", "equipment delete refused"),
        ):
            try:
                store._conn.execute(statement)
            except sqlite3.IntegrityError:
                notes.append(expected)
            else:
                raise AssertionError(
                    f"append-only is NOT enforced: {statement!r} was allowed to run"
                )
    finally:
        if started_transaction:
            store._conn.rollback()
    return tuple(notes)
