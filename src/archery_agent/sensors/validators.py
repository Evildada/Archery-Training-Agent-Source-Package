"""T0/T1 sensors: structural and plausibility validation.

The distinction matters when a write is rejected:

* **T0 (structural)** — "this is not a valid record" (pydantic already handled the shape).
* **T1 (plausibility)** — "this is shaped right but almost certainly a typo".

Both produce *actionable* messages. A validation failure that says only "invalid" teaches the
archer nothing and teaches the agent nothing either.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from archery_agent.domain import parameters as registry
from archery_agent.domain.entities import offsets_required
from archery_agent.domain.enums import ObservationSource, ParameterKind, SessionMode
from archery_agent.domain.ledger import ParameterObservation

#: Sample-size thresholds, referenced by the stats gates and by the docs (AGENTS.md rule 5).
MIN_SESSIONS_FOR_TREND: int = 5
MIN_SHOTS_FOR_END_STATS: int = 3
MIN_SHOTS_FOR_EFFECT: int = 30


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Issue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    severity: Severity
    message: str
    field: str | None = None
    suggestion: str = ""


class ValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    issues: tuple[Issue, ...] = ()

    @property
    def ok(self) -> bool:
        return not any(i.severity is Severity.ERROR for i in self.issues)

    @property
    def errors(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.severity is Severity.WARNING)

    def summary(self) -> str:
        if not self.issues:
            return "ok"
        parts = []
        for level in (Severity.ERROR, Severity.WARNING, Severity.INFO):
            count = sum(1 for i in self.issues if i.severity is level)
            if count:
                parts.append(f"{count} {level.value}")
        return ", ".join(parts)

    def raise_if_invalid(self) -> None:
        if not self.ok:
            detail = "\n  - ".join(f"[{i.code}] {i.message}" for i in self.errors)
            raise ValueError(f"record failed validation:\n  - {detail}")


def _issue(
    code: str,
    severity: Severity,
    message: str,
    *,
    field: str | None = None,
    suggestion: str = "",
) -> Issue:
    return Issue(code=code, severity=severity, message=message, field=field, suggestion=suggestion)


def validate_parameter_observation(observation: ParameterObservation) -> ValidationResult:
    """Plausibility checks for one ledger row. This is the typo guard."""
    definition = registry.get(observation.key)
    issues: list[Issue] = []

    if definition.plausible_range is not None and observation.is_numeric:
        value = observation.numeric()
        lo, hi = definition.plausible_range
        if math.isnan(value) or math.isinf(value):
            issues.append(
                _issue(
                    "param_not_finite",
                    Severity.ERROR,
                    f"{observation.key}: value must be finite, got {value}",
                    field=observation.key,
                    suggestion="Re-enter the measured value; NaN/Inf means the capture tool broke.",
                )
            )
        elif not (lo <= value <= hi):
            issues.append(
                _issue(
                    "param_out_of_range",
                    Severity.ERROR,
                    f"{observation.key}: {value:g} {definition.unit or ''} is outside the "
                    f"plausible range {lo:g}-{hi:g}. "
                    f"('{definition.label}')",
                    field=observation.key,
                    suggestion=(
                        "Check the units and the decimal point. If the value is genuinely correct, "
                        "the registry's plausible_range needs a reviewed update — do not force "
                        "the write."
                    ),
                )
            )

    if definition.kind is ParameterKind.ORDINAL and observation.is_numeric:
        value = observation.numeric()
        if not float(value).is_integer():
            issues.append(
                _issue(
                    "ordinal_not_integer",
                    Severity.WARNING,
                    f"{observation.key}: ordinal ratings should be whole numbers, got {value:g}",
                    field=observation.key,
                    suggestion=(
                        "Averaging intermediate ratings hides the pattern; use whole numbers."
                    ),
                )
            )

    if (
        observation.source is ObservationSource.SELF_REPORTED
        and observation.reliability.value == "high"
    ):
        issues.append(
            _issue(
                "self_report_high_reliability",
                Severity.WARNING,
                f"{observation.key}: self-reported value marked high reliability",
                field="reliability",
                suggestion=(
                    "Self-reports are low (one-off estimate) or medium (repeated rating). "
                    "Reserve high for measured values."
                ),
            )
        )

    if definition.category.value == "outcome":
        if observation.distance_m is None:
            issues.append(
                _issue(
                    "outcome_without_distance",
                    Severity.ERROR,
                    f"{observation.key}: outcome parameters require a distance",
                    field="distance_m",
                    suggestion="Group size and score are not comparable across distances.",
                )
            )
        if observation.target_face_id is None:
            issues.append(
                _issue(
                    "outcome_without_face",
                    Severity.ERROR,
                    f"{observation.key}: outcome parameters require a target face",
                    field="target_face_id",
                    suggestion=(
                        "A 6 cm group on a 3-spot and on a 122 cm face are different events."
                    ),
                )
            )

    if observation.key == "arrow.speed_fps" and observation.source is ObservationSource.DERIVED:
        issues.append(
            _issue(
                "derived_speed",
                Severity.WARNING,
                "arrow.speed_fps is derived rather than measured",
                field=observation.key,
                suggestion=(
                    "Derived speed can support descriptions, never a SUPPORTED claim "
                    "(see sensors.stats.claim_label_for)."
                ),
            )
        )

    return ValidationResult(issues=tuple(issues))


def validate_record(
    record: BaseModel, *, context: dict[str, object] | None = None
) -> ValidationResult:
    """T0/T1 validation for any domain record.

    Pydantic has already enforced types and enums by the time a record exists, so this
    function focuses on the *cross-record* rules that a single model cannot see.
    """
    issues: list[Issue] = []
    name = type(record).__name__

    if name == "End":
        distance = getattr(record, "distance_m", None)
        face = getattr(record, "target_face_id", None)
        if distance is not None and face is not None:
            from archery_agent.domain.targets import get_face, max_range_m

            try:
                spec = get_face(str(face))
            except ValueError as exc:
                issues.append(
                    _issue("unknown_face", Severity.ERROR, str(exc), field="target_face_id")
                )
            else:
                bound = max_range_m(spec.face_id)
                if bound is not None and float(distance) > bound:
                    issues.append(
                        _issue(
                            "distance_beyond_face",
                            Severity.WARNING,
                            f"{spec.face_id} at {float(distance):g} m is beyond the face's usual "
                            f"range ({bound:g} m)",
                            field="distance_m",
                            suggestion="Confirm the distance and the face before analysis.",
                        )
                    )

    if name == "Session":
        planned = getattr(record, "planned_arrow_count", None)
        actual = getattr(record, "arrow_count", None)
        mode = getattr(record, "mode", None)
        if (
            planned is not None
            and actual is not None
            and int(actual) > int(planned) * 2
            and int(planned) > 0
        ):
            issues.append(
                _issue(
                    "volume_double_plan",
                    Severity.WARNING,
                    f"{int(actual)} arrows logged against a plan of {int(planned)}",
                    field="arrow_count",
                    suggestion="Either the plan was revised mid-session (record why) or a typo.",
                )
            )
        if mode is not None and mode.value == "blank_bale":
            issues.append(
                _issue(
                    "blank_bale_no_scoring",
                    Severity.INFO,
                    "blank-bale sessions carry no scores by design",
                    suggestion="Outcome parameters will be absent; analyse timing/tension instead.",
                )
            )

    if context and context.get("equipment_set_retired_before_session"):
        issues.append(
            _issue(
                "retired_equipment_reference",
                Severity.ERROR,
                "session references an equipment set retired before it started",
                field="equipment_set_id",
                suggestion=(
                    "Equipment changes are events with effective dates; pick the set that was "
                    "actually in use."
                ),
            )
        )

    return ValidationResult(issues=tuple(issues))


def validate_offsets_for_mode(
    mode: SessionMode,
    shots: Sequence[object],
) -> ValidationResult:
    """Q7: a mode that needs offsets, entered without any, is a warning — not a rejection.

    Rejecting the data would punish the archer for a range-day compromise and lose the session;
    the report simply cannot say anything about group shape, and it must say so out loud.
    """
    if not offsets_required(mode):
        return ValidationResult()
    offset_shots = [
        shot
        for shot in shots
        if getattr(shot, "horizontal_offset_cm", None) is not None
        and getattr(shot, "vertical_offset_cm", None) is not None
    ]
    if not shots or offset_shots:
        return ValidationResult()
    return ValidationResult(
        issues=(
            Issue(
                code="offsets_missing_for_mode",
                severity=Severity.WARNING,
                message=(
                    f"{mode.value}: {len(shots)} arrows recorded with scores but no (x, y) "
                    "positions"
                ),
                suggestion=(
                    "Group shape, centre drift and aim-float work are unavailable from this "
                    "session; if you want group analysis next time, tap the arrow positions."
                ),
            ),
        ),
    )


def validate_analysis_window(
    *,
    n_shots: int,
    n_sessions: int = 0,
    purpose: str = "trend",
) -> ValidationResult:
    """Refuse to analyse noise. Warnings here become INSUFFICIENT_EVIDENCE labels downstream."""
    issues: list[Issue] = []

    if purpose == "effect" and n_shots < MIN_SHOTS_FOR_EFFECT:
        issues.append(
            _issue(
                "insufficient_shots_for_effect",
                Severity.ERROR,
                f"{n_shots} shots is below the {MIN_SHOTS_FOR_EFFECT}-shot minimum for an "
                "effect estimate",
                suggestion=(
                    "Report the observation without a causal claim, and keep collecting. "
                    "This is a designed refusal, not a limitation to work around."
                ),
            )
        )

    if purpose == "trend" and n_sessions and n_sessions < MIN_SESSIONS_FOR_TREND:
        issues.append(
            _issue(
                "insufficient_sessions_for_trend",
                Severity.ERROR,
                f"{n_sessions} sessions is below the {MIN_SESSIONS_FOR_TREND}-session minimum "
                "for a trend",
                suggestion="Report the individual sessions; a line through 2 points is a story.",
            )
        )

    if purpose in {"end_stats", "shot_stats"} and n_shots < MIN_SHOTS_FOR_END_STATS:
        issues.append(
            _issue(
                "insufficient_shots_for_stats",
                Severity.ERROR,
                f"{n_shots} shots is below the {MIN_SHOTS_FOR_END_STATS}-shot minimum for group "
                "statistics",
                suggestion=(
                    "Group radius from 2 arrows is not a measurement of precision — it is a "
                    "description of two arrows."
                ),
            )
        )
    return ValidationResult(issues=tuple(issues))
