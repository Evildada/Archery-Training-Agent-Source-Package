"""Equipment as a *history*, not a state.

This module exists because of one sentence in the roadmap (`docs/06-roadmap.md`, M1):

    changing a module, a point weight or a draw length is an **event**, because the S5
    regression needs the change-point, not just the current state.

Two consequences that are easy to get wrong and expensive to fix later:

* **nothing is overwritten.** Recording a new build appends a version; the previous version stays
  exactly as it was. A query for "what was he shooting in June?" must return June's answer, even
  after the bow has been through four more setups.
* **the change is data too.** When version 3 supersedes version 2, the *delta* is computed and
  stored with the version. That delta is the change-point a later analysis regresses against, and
  recomputing it from two snapshots is the kind of thing that silently drifts when a field is
  renamed. So it is computed once, at write time, by one function (`diff_equipment`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from archery_agent.domain.entities import (
    ArrowSetup,
    Bow,
    DomainRecord,
    EquipmentSet,
    Release,
    utcnow,
)
from archery_agent.domain.enums import ObservationSource, Reliability
from archery_agent.domain.ids import new_id
from archery_agent.domain.ledger import ParameterObservation

#: Registry parameters an equipment version publishes into the ledger. Anything not listed here
#: stays a property of the version record and is *not* written to the ledger — a smaller,
#: deliberate set keeps the ledger's parameter rows meaningful instead of a dump of the bow spec.
PUBLISHED_KEYS: tuple[str, ...] = (
    "bow.draw_weight_lb",
    "bow.let_off_pct",
    "bow.brace_height_in",
    "bow.axle_to_axle_in",
    "arrow.total_mass_grains",
    "arrow.point_mass_grains",
    "arrow.shaft_length_in",
    "arrow.static_spine_thou",
    "arrow.foc_pct",
    "arrow.ke_ftlb",
)


class EquipmentChange(BaseModel):
    """One field that differs between two versions. Signed where numeric."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str = Field(description="Dotted path, e.g. 'arrow.point_mass_grains'.")
    old_value: str | None = None
    new_value: str | None = None
    delta: float | None = Field(
        default=None,
        description="new - old, when both parse as numbers. Signed, so direction is not lost.",
    )
    note: str = ""

    def describe(self) -> str:
        arrow = f"{self.old_value} -> {self.new_value}"
        if self.delta is not None and self.delta != 0.0:
            return f"{self.field}: {arrow} ({self.delta:+.2f})"
        return f"{self.field}: {arrow}"


#: Row identities are not equipment facts. Two versions of "the same arrow with a heavier point"
#: must not read as "you replaced your arrow", so the ids never enter the delta.
_IDENTITY_FIELDS: frozenset[str] = frozenset(
    {"arrow_id", "bow_id", "release_id", "equipment_set_id", "version_id"}
)


def _flatten(prefix: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten a model dump to ``dotted.path -> value``, skipping None, empties and row ids."""
    flat: dict[str, Any] = {}
    for key, value in payload.items():
        if key in _IDENTITY_FIELDS:
            continue
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, Mapping):
            flat.update(_flatten(path, value))
        elif value is None or value == {} or value == []:
            continue
        else:
            flat[path] = value
    return flat


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def diff_equipment(
    previous: EquipmentVersion | None, current: EquipmentVersion
) -> tuple[EquipmentChange, ...]:
    """Every difference between two versions, in a stable field order.

    ``previous is None`` returns **no changes at all**: a first setup has no predecessor to
    differ from, and inventing a delta against nothing would put sixteen fake "changes" at the
    top of the archer's report. The snapshot itself already says what the setup was.
    """
    if previous is None:
        return ()
    before = _flatten("", previous.equipment.comparable_dump())
    after = _flatten("", current.equipment.comparable_dump())

    changes: list[EquipmentChange] = []
    for field in sorted(set(before) | set(after)):
        old, new = before.get(field), after.get(field)
        if old == new:
            continue
        old_num, new_num = _as_number(old), _as_number(new)
        changes.append(
            EquipmentChange(
                field=field,
                old_value=None if old is None else str(old),
                new_value=None if new is None else str(new),
                delta=(new_num - old_num) if old_num is not None and new_num is not None else None,
            )
        )
    return tuple(changes)


class EquipmentSnapshot(DomainRecord):
    """The bow/release/arrow triple, comparable across versions.

    A thin wrapper rather than three loose fields so that :func:`_flatten` has exactly one shape
    to walk, and so that adding a component later (a rest, a scope) is a field here plus a
    registry key — not a change to the diff algorithm.
    """

    bow: Bow
    release: Release | None = None
    arrow: ArrowSetup
    accessories: dict[str, str] = Field(default_factory=dict)

    def comparable_dump(self) -> dict[str, Any]:
        """Stable, diff-friendly dump. Accessory keys are sorted so diffs are reproducible."""
        return {
            "bow": self.bow.model_dump(exclude={"bow_type"}, exclude_none=True),
            "release": self.release.model_dump(exclude_none=True) if self.release else {},
            "arrow": self.arrow.model_dump(exclude_none=True),
            "accessories": dict(sorted(self.accessories.items())),
        }

    @classmethod
    def from_set(cls, equipment: EquipmentSet) -> EquipmentSnapshot:
        return cls(
            bow=equipment.bow,
            release=equipment.release,
            arrow=equipment.arrow,
            accessories=equipment.accessories,
        )


class EquipmentVersion(DomainRecord):
    """One append-only, dated state of an archer's equipment."""

    version_id: str = Field(default_factory=lambda: new_id("equipment"))
    archer_id: str
    version: int = Field(ge=1, description="1 for the first recorded setup, then 2, 3, ...")
    equipment: EquipmentSnapshot
    effective_from: datetime = Field(
        default_factory=utcnow,
        description="When this setup started being shot. Not always when it was typed in.",
    )
    recorded_at: datetime = Field(default_factory=utcnow)
    reason: str = Field(
        default="",
        description="Why it changed. Free text, but the report shows it, so 'no idea' is an "
        "acceptable and useful answer.",
    )
    changes: tuple[EquipmentChange, ...] = ()
    supersedes: str | None = None
    notes: str = ""

    @property
    def label(self) -> str:
        bow = f"{self.equipment.bow.brand} {self.equipment.bow.model}".strip()
        return f"v{self.version} ({bow}, from {self.effective_from.date().isoformat()})"

    def describe_changes(self) -> str:
        if not self.changes:
            return "first recorded setup"
        return "; ".join(change.describe() for change in self.changes)

    def ledger_observations(
        self,
        *,
        reliability: Reliability = Reliability.MEDIUM,
        source: ObservationSource = ObservationSource.SELF_REPORTED,
    ) -> tuple[ParameterObservation, ...]:
        """The version's facts, as ledger rows.

        This is what lets the S5 regression see *which setup produced which arrows*: every row
        carries ``equipment_set_id``, so a change-point is visible in the ledger itself and not
        only in the equipment tables.
        """
        candidates: dict[str, float | None] = {
            "bow.draw_weight_lb": self.equipment.bow.draw_weight_lb,
            "bow.let_off_pct": self.equipment.bow.let_off_pct,
            "bow.brace_height_in": self.equipment.bow.brace_height_in,
            "bow.axle_to_axle_in": self.equipment.bow.axle_to_axle_in,
            "arrow.total_mass_grains": self.equipment.arrow.effective_total_mass_grains(),
            "arrow.point_mass_grains": self.equipment.arrow.point_mass_grains,
            "arrow.shaft_length_in": self.equipment.arrow.shaft_length_in,
            "arrow.static_spine_thou": self.equipment.arrow.shaft_spine_thou,
        }

        rows: list[ParameterObservation] = []
        for key in PUBLISHED_KEYS:
            value = candidates.get(key)
            if value is None:
                continue
            rows.append(
                ParameterObservation(
                    archer_id=self.archer_id,
                    key=key,
                    value=float(value),
                    source=source,
                    reliability=reliability,
                    observed_at=self.effective_from,
                    equipment_set_id=self.version_id,
                    note=f"equipment v{self.version}: {self.reason or 'no reason recorded'}",
                )
            )
        return tuple(rows)


def next_version(history: Sequence[EquipmentVersion]) -> int:
    """Version numbers are dense and monotonic: 1, 2, 3, ...  Never a date, never a guess."""
    return max((version.version for version in history), default=0) + 1


def latest(history: Iterable[EquipmentVersion]) -> EquipmentVersion | None:
    """The current setup: highest version number, tie-broken by effective date."""
    versions = list(history)
    if not versions:
        return None
    return max(versions, key=lambda v: (v.version, v.effective_from))


def record_version(
    *,
    archer_id: str,
    equipment: EquipmentSet,
    history: Sequence[EquipmentVersion] = (),
    effective_from: datetime | None = None,
    reason: str = "",
) -> EquipmentVersion:
    """Build the next version and compute its delta. Pure — the caller decides where to store it."""
    previous = latest(history)
    draft = EquipmentVersion(
        archer_id=archer_id,
        version=next_version(history),
        equipment=EquipmentSnapshot.from_set(equipment),
        effective_from=effective_from or utcnow(),
        reason=reason,
        supersedes=previous.version_id if previous else None,
    )
    changes = diff_equipment(previous, draft)
    return draft.model_copy(update={"changes": changes})


def versions_as_of(
    history: Sequence[EquipmentVersion], moment: datetime
) -> EquipmentVersion | None:
    """What was on the bow at ``moment``. The question a coach actually asks."""
    eligible = [version for version in history if version.effective_from <= moment]
    if not eligible:
        return None
    return max(eligible, key=lambda v: (v.effective_from, v.version))
