"""The Parameter Ledger — the spine of the whole product.

Tidy long format: one row per observation. Every metric the app ever reasons about is a row
here, which is what makes the original brief's hypothesis testable:

    "A set of parameter can form a regression that maintains stable position."

A regression needs (a) repeated measurements of many parameters, (b) an outcome to regress
against, (c) provenance so that self-reported and measured values are never silently mixed.
This module guarantees all three at the type level.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from archery_agent.domain import parameters as registry
from archery_agent.domain.entities import utcnow
from archery_agent.domain.enums import ObservationSource, ParameterKind, Reliability
from archery_agent.domain.ids import new_id

#: A parameter value is whatever the registry says it is: numeric, boolean, or a label.
ParameterValue = float | int | bool | str


class ParameterObservation(BaseModel):
    """One measured/rated/derived value of one parameter, at one point in time."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    observation_id: str = Field(default_factory=lambda: new_id("observation"))
    archer_id: str
    key: str
    value: ParameterValue
    unit: str | None = None
    source: ObservationSource = ObservationSource.SELF_REPORTED
    reliability: Reliability = Reliability.MEDIUM
    observed_at: datetime = Field(default_factory=utcnow)

    # --- provenance / context (all optional, but the more present the better the analysis)
    session_id: str | None = None
    end_id: str | None = None
    shot_id: str | None = None
    equipment_set_id: str | None = None
    cycle_template_id: str | None = None
    distance_m: Annotated[float, Field(gt=0.0)] | None = None
    target_face_id: str | None = None
    note: str = ""

    @field_validator("key")
    @classmethod
    def _known_key(cls, value: str) -> str:
        registry.get(value)  # raises UnknownParameterError with suggestions
        return value

    @model_validator(mode="after")
    def _value_matches_registry(self) -> ParameterObservation:
        definition = registry.get(self.key)

        if self.unit is not None and definition.unit is not None and self.unit != definition.unit:
            raise ValueError(
                f"{self.key} is registered in {definition.unit!r}; got unit {self.unit!r}. "
                "Units are converted at the boundary (domain/units.py), never relabelled here."
            )
        if definition.unit is not None and self.unit is None:
            object.__setattr__(self, "unit", definition.unit)

        if definition.kind is ParameterKind.BOOLEAN and not isinstance(self.value, bool):
            raise ValueError(f"{self.key} is boolean; got {type(self.value).__name__}")
        if definition.kind in {ParameterKind.RATIO, ParameterKind.INTERVAL} and isinstance(
            self.value, bool
        ):
            raise ValueError(f"{self.key} expects a number; got a boolean")
        if definition.kind in {
            ParameterKind.RATIO,
            ParameterKind.INTERVAL,
            ParameterKind.ORDINAL,
            ParameterKind.COUNT,
        } and not isinstance(self.value, (int, float)):
            raise ValueError(
                f"{self.key} expects a numeric value (kind={definition.kind}); "
                f"got {type(self.value).__name__}"
            )
        if definition.kind is ParameterKind.CATEGORICAL and not isinstance(self.value, str):
            raise ValueError(f"{self.key} expects a category label (str)")

        # A self-reported ordinal is never high reliability, no matter who reports it.
        if (
            definition.kind is ParameterKind.ORDINAL
            and self.source is ObservationSource.SELF_REPORTED
            and self.reliability is Reliability.HIGH
        ):
            raise ValueError(
                f"{self.key}: a self-reported ordinal cannot be reliability=high — "
                "call it medium (repeated self-ratings) or low (one-off estimate)"
            )
        return self

    @property
    def is_numeric(self) -> bool:
        return isinstance(self.value, (int, float)) and not isinstance(self.value, bool)

    def numeric(self) -> float:
        if not self.is_numeric:
            raise TypeError(f"{self.key} holds a non-numeric value ({self.value!r})")
        return float(self.value)


class ObservationBatch(BaseModel):
    """What capture produces and what the ledger accepts or rejects — with reasons."""

    model_config = ConfigDict(extra="forbid")

    accepted: tuple[ParameterObservation, ...] = ()
    rejected: tuple[dict[str, str], ...] = Field(
        default=(), description="[{'key':..., 'reason':...}] — never silently dropped."
    )
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.rejected
