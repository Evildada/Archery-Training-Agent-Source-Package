"""Archer, equipment, cycle template and session entities.

Every model here is persisted, so every model forbids extra fields: a typo in a training log
is not a warning, it is corrupted data that will silently bias a regression six months later.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from archery_agent.domain.enums import AccountRole, BowType, SessionMode
from archery_agent.domain.ids import new_id

# --------------------------------------------------------------------- base


class DomainRecord(BaseModel):
    """Base for anything persisted: no unknown fields, no naive datetimes."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    @field_validator("*", mode="after")
    @classmethod
    def _aware_utc(cls, value: object) -> object:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise ValueError(
                    "naive datetimes are not allowed — store timezone-aware UTC (AGENTS.md rule 5)"
                )
            return value.astimezone(UTC)
        return value


def utcnow() -> datetime:
    return datetime.now(UTC)


Percent = Annotated[float, Field(ge=0.0, le=100.0)]
Ordinal15 = Annotated[float, Field(ge=1.0, le=5.0)]
Ordinal110 = Annotated[float, Field(ge=1.0, le=10.0)]
Positive = Annotated[float, Field(gt=0.0)]


# ------------------------------------------------------------------- archer


class Archer(DomainRecord):
    """Identity. Deliberately thin: only what changes behaviour or protects the archer."""

    archer_id: str = Field(default_factory=lambda: new_id("archer"))
    display_name: str = Field(min_length=1, max_length=60)
    birth_year: int | None = Field(
        default=None,
        ge=1900,
        le=2100,
        description="Year only — never a full date of birth (minors are a primary user group).",
    )
    handedness: Literal["RH", "LH"] = "RH"
    dominant_eye: Literal["right", "left"] | None = None
    bow_type: BowType = BowType.COMPOUND
    guardian_consent: bool = Field(
        default=False,
        description="Required before any record leaves the device for an archer under 18.",
    )
    roles: frozenset[AccountRole] = Field(
        default=frozenset({AccountRole.ARCHER}),
        description="Capabilities this account holds. A coach who also shoots has both.",
    )
    #: Set when this archer is coached by someone else *inside* the system. A person who coaches
    #: only themselves leaves this None and still keeps COACH in ``roles`` — that is the Q1
    #: answer ("the coach is also an archer") expressed as data rather than as two accounts.
    coach_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _roles_are_explicit(self) -> Archer:
        if not self.roles:
            raise ValueError(
                "an account with no roles cannot read or write anything; declare at least one "
                "of ARCHER, COACH, GUARDIAN"
            )
        if AccountRole.ARCHER not in self.roles and AccountRole.COACH not in self.roles:
            raise ValueError("a guardian-only account is a viewer of an archer, not an archer")
        return self

    @property
    def is_coach(self) -> bool:
        return AccountRole.COACH in self.roles

    @property
    def is_minor(self) -> bool:
        if self.birth_year is None:
            return False
        return (utcnow().year - self.birth_year) < 18


class ShooterProfile(DomainRecord):
    """The slow-changing half of the parameter set: *who this archer is, technically*.

    Edits here are **events**, not overwrites (docs/03 §2): the S5 regression needs the date
    of a technique change as a change-point, so `ProfileChange` records wrap these edits.
    """

    profile_id: str = Field(default_factory=lambda: new_id("archer"))
    archer_id: str
    draw_length_in: Positive | None = None
    draw_weight_lb: Positive | None = None
    let_off_pct: Percent | None = None
    anchor_type: Literal["release_hand_behind_jaw", "valley_wall", "nose_on_string", "custom"] = (
        "release_hand_behind_jaw"
    )
    release_type: Literal["hinge", "thumb_button", "caliper", "resistance"] = "thumb_button"
    aiming_style: Literal["scope_ring", "pin_float", "hybrid"] = "scope_ring"
    hold_strategy: Literal["expansion_through_wall", "timed_hold", "surprise_break"] = (
        "expansion_through_wall"
    )
    cycle_template_id: str | None = None
    equipment_set_id: str | None = None
    updated_at: datetime = Field(default_factory=utcnow)


class ProfileChange(DomainRecord):
    """An append-only note that a profile field changed, with an effective date."""

    change_id: str = Field(default_factory=lambda: new_id("archer"))
    archer_id: str
    field: str
    old_value: str | None = None
    new_value: str | None = None
    effective_at: datetime = Field(default_factory=utcnow)
    reason: str = ""


# ----------------------------------------------------------------- equipment


class Bow(DomainRecord):
    bow_id: str = Field(default_factory=lambda: new_id("bow"))
    bow_type: BowType = BowType.COMPOUND
    brand: str = Field(min_length=1, max_length=60)
    model: str = Field(min_length=1, max_length=60)
    cam_system: str | None = None
    axle_to_axle_in: Positive | None = None
    brace_height_in: Positive | None = None
    draw_weight_lb: Positive | None = None
    let_off_pct: Percent | None = None
    draw_length_in: Positive | None = None
    bow_mass_oz: Positive | None = None


class Release(DomainRecord):
    release_id: str = Field(default_factory=lambda: new_id("release"))
    release_type: Literal["hinge", "thumb_button", "caliper", "resistance"]
    brand: str = Field(min_length=1, max_length=60)
    model: str = Field(min_length=1, max_length=60)
    sear_travel_1_5: Ordinal15 | None = None


class ArrowSetup(DomainRecord):
    arrow_id: str = Field(default_factory=lambda: new_id("arrow"))
    brand: str = Field(min_length=1, max_length=60)
    model: str = Field(min_length=1, max_length=60)
    shaft_spine_thou: Positive | None = Field(
        default=None, description="Static spine deflection in thousandths of an inch."
    )
    shaft_length_in: Positive | None = None
    shaft_mass_grains: Positive | None = None
    insert_mass_grains: Annotated[float, Field(ge=0.0)] | None = None
    point_mass_grains: Positive | None = None
    nock_mass_grains: Annotated[float, Field(ge=0.0)] | None = None
    fletching_type: Literal["vanes_2in", "vanes_2_5in", "vanes_3in", "feathers", "other"] | None = (
        None
    )
    fletching_count: int | None = Field(default=None, ge=2, le=4)
    fletching_angle_deg: Annotated[float, Field(ge=0.0, le=15.0)] | None = None
    measured_total_mass_grains: Positive | None = Field(
        default=None,
        description="Weigh a finished arrow. Catalog masses are optimistic; this is the "
        "value the simulator must prefer when both exist.",
    )

    @model_validator(mode="after")
    def _component_masses_consistent(self) -> ArrowSetup:
        if (
            self.measured_total_mass_grains is not None
            and self.shaft_mass_grains is not None
            and self.measured_total_mass_grains < self.shaft_mass_grains
        ):
            raise ValueError(
                "measured total mass cannot be less than shaft mass — one of the two is wrong"
            )
        return self

    @property
    def component_mass_grains(self) -> float | None:
        """Sum of the entered components, or None when the shaft mass is unknown."""
        if self.shaft_mass_grains is None:
            return None
        return float(self.shaft_mass_grains) + sum(
            float(value or 0.0)
            for value in (
                self.insert_mass_grains,
                self.point_mass_grains,
                self.nock_mass_grains,
            )
        )

    @property
    def is_weighed(self) -> bool:
        """True when somebody actually put the arrow on a scale."""
        return self.measured_total_mass_grains is not None

    def effective_total_mass_grains(self) -> float | None:
        """Measured mass if it exists, else the summed components, else nothing.

        The report labels these two cases differently (MEASURED vs ESTIMATED) and names a
        different confirming test for each, so the caller must not collapse them here.
        """
        if self.measured_total_mass_grains is not None:
            return float(self.measured_total_mass_grains)
        return self.component_mass_grains


class EquipmentSet(DomainRecord):
    """A versioned snapshot. Sessions point at a set, and sets are retired, never edited."""

    equipment_set_id: str = Field(default_factory=lambda: new_id("equipment"))
    archer_id: str
    bow: Bow
    release: Release | None = None
    arrow: ArrowSetup
    accessories: dict[str, str] = Field(
        default_factory=dict,
        description="sight / scope / peep / rest / stabiliser — free-form brand+model notes.",
    )
    active_from: datetime = Field(default_factory=utcnow)
    retired_at: datetime | None = None
    notes: str = ""


# -------------------------------------------------------------- cycle template


class CyclePhase(DomainRecord):
    """One phase of the shooting cycle. The shared vocabulary between coaches and students."""

    phase_key: Literal[
        "routine",
        "nock_raise",
        "draw",
        "hold_anchor",
        "aim_expand",
        "release",
        "follow_through",
    ]
    order: int = Field(ge=1, le=12)
    name: str = Field(min_length=1, max_length=60)
    definition: str = Field(min_length=1, description="What the archer should be doing.")
    cue: str = Field(default="", description="Short in-shot cue, one or two words.")
    target_window: str = Field(
        default="",
        description="Human-readable intent, e.g. 'hold 2-4 s'. Numeric standards live in "
        "Standard records so they can be evaluated, not just read.",
    )
    observe_params: tuple[str, ...] = ()
    common_faults: tuple[str, ...] = ()

    @field_validator("observe_params")
    @classmethod
    def _known_params(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        from archery_agent.domain import parameters as registry

        for key in value:
            registry.get(key)  # raises UnknownParameterError with suggestions
        return value


CANONICAL_PHASE_ORDER: tuple[str, ...] = (
    "routine",
    "nock_raise",
    "draw",
    "hold_anchor",
    "aim_expand",
    "release",
    "follow_through",
)


class CycleTemplate(DomainRecord):
    """Immutable once published. A coach's method, expressed so it can be taught and checked."""

    template_id: str = Field(default_factory=lambda: new_id("template"))
    version: int = Field(default=1, ge=1)
    name: str = Field(min_length=1, max_length=80)
    author: Literal["archer", "coach", "system", "imported"] = "archer"
    author_id: str | None = None
    phases: tuple[CyclePhase, ...] = ()
    published_at: datetime | None = None
    supersedes: str | None = None
    notes: str = ""

    @model_validator(mode="after")
    def _phases_are_complete_and_ordered(self) -> CycleTemplate:
        if not self.phases:
            return self
        orders = [p.order for p in self.phases]
        if len(set(orders)) != len(orders):
            raise ValueError("cycle phases must have unique order values")
        keys = [p.phase_key for p in self.phases]
        if len(set(keys)) != len(keys):
            raise ValueError(f"duplicate phase keys in template: {keys}")
        return self

    @property
    def ordered_phases(self) -> tuple[CyclePhase, ...]:
        return tuple(sorted(self.phases, key=lambda p: p.order))


def canonical_compound_template(**overrides: object) -> CycleTemplate:
    """The neutral, system-authored baseline every archer starts from.

    Coach templates are expected to *differ* from this; that difference is the coach's method
    (docs/00-product-brief.md, usage note 2). This is the reference the app compares against,
    not a claim about the one true technique.
    """
    phases = (
        CyclePhase(
            phase_key="routine",
            order=1,
            name="Pre-shot routine",
            definition="Stance set, feet square to the line, breathing, shot plan fixed before the "
            "bow comes up.",
            cue="plan first",
            target_window="same plan, every arrow",
            observe_params=("mental.routine_adherence_pct", "mental.arousal_1_10"),
            common_faults=("no plan", "step count drifts", "start after the timer"),
        ),
        CyclePhase(
            phase_key="nock_raise",
            order=2,
            name="Nock and raise",
            definition="Nock, hook up, bow hand set with relaxed grip, bow raised to target.",
            cue="soft hand",
            observe_params=("tension.grip_pressure_1_5", "cycle.nock_to_release_s"),
            common_faults=("death grip", "rushing the nock", "elbow high"),
        ),
        CyclePhase(
            phase_key="draw",
            order=3,
            name="Draw",
            definition="Continuous draw to the wall, elbow travelling behind the arrow line, "
            "no stalling at peak weight.",
            cue="one motion",
            observe_params=("cycle.draw_time_s", "tension.draw_smoothness_1_5"),
            common_faults=("stall before the wall", "jerky draw", "shoulder-driven draw"),
        ),
        CyclePhase(
            phase_key="hold_anchor",
            order=4,
            name="Anchor and transfer",
            definition="Settle into the wall, weight transferred into the back, anchor contact "
            "established and maintained.",
            cue="into the back",
            observe_params=(
                "cycle.hold_time_s",
                "tension.back_tension_1_5",
                "tension.anchor_pressure_1_5",
            ),
            common_faults=("floating anchor", "holding on the front", "creeping"),
        ),
        CyclePhase(
            phase_key="aim_expand",
            order=5,
            name="Aim and expand",
            definition="Aim settles, float accepted, continuous expansion while aiming.",
            cue="keep pulling",
            observe_params=(
                "cycle.aim_time_s",
                "aim.aim_float_radius_cm",
                "cycle.expansion_time_s",
            ),
            common_faults=("aiming too long", "chasing the X", "stopping the expansion"),
        ),
        CyclePhase(
            phase_key="release",
            order=6,
            name="Release",
            definition="Release activated by continued expansion, not by a decision to fire.",
            cue="let it go",
            observe_params=("release.thumb_pressure_1_5", "release.punch_tendency_1_5"),
            common_faults=("punching", "anticipating", "collapsing"),
        ),
        CyclePhase(
            phase_key="follow_through",
            order=7,
            name="Follow-through",
            definition="Stay still and stay in the shot until the arrow lands; bow hand relaxed "
            "through the drop.",
            cue="stay in it",
            observe_params=("cycle.follow_through_s", "tension.wrist_relaxation_1_5"),
            common_faults=("peeking", "dropping the bow arm", "walking to the target early"),
        ),
    )
    payload: dict[str, object] = {
        "name": "Canonical compound cycle (system baseline)",
        "author": "system",
        "phases": phases,
    }
    payload.update(overrides)
    return CycleTemplate.model_validate(payload)


# -------------------------------------------------------------------- session


class Environment(DomainRecord):
    indoor_outdoor: Literal["indoor", "outdoor"] = "indoor"
    wind_speed_mps: Annotated[float, Field(ge=0.0, le=30.0)] | None = None
    wind_direction_deg: Annotated[float, Field(ge=0.0, le=360.0)] | None = None
    temperature_c: Annotated[float, Field(ge=-20.0, le=50.0)] | None = None
    humidity_pct: Percent | None = None


class Session(DomainRecord):
    session_id: str = Field(default_factory=lambda: new_id("session"))
    archer_id: str
    started_at: datetime = Field(default_factory=utcnow)
    mode: SessionMode
    distance_m: Positive
    target_face_id: str
    equipment_set_id: str | None = None
    cycle_template_id: str | None = None
    planned_arrow_count: int | None = Field(default=None, ge=0, le=1000)
    arrow_count: int = Field(default=0, ge=0, le=1000)
    duration_min: Annotated[float, Field(ge=0.0, le=600.0)] | None = None
    focus_tags: tuple[str, ...] = ()
    rpe_1_10: Ordinal110 | None = None
    sleep_hours: Annotated[float, Field(ge=0.0, le=16.0)] | None = None
    readiness_1_10: Ordinal110 | None = None
    environment: Environment = Field(default_factory=Environment)
    coach_note: str = ""
    archer_note: str = ""

    @model_validator(mode="after")
    def _scored_modes_need_a_face(self) -> Session:
        if self.mode is SessionMode.SCORING and self.target_face_id == "BLANK_BALE":
            raise ValueError("mode='scoring' cannot use the blank-bale face — nothing to score")
        return self


class End(DomainRecord):
    """A group of arrows shot as one unit. The natural scoring/analysis granularity."""

    end_id: str = Field(default_factory=lambda: new_id("end"))
    session_id: str
    index: int = Field(ge=1, le=60)
    distance_m: Positive
    target_face_id: str
    arrows_planned: int = Field(default=6, ge=1, le=12)
    notes: str = ""


#: Q7 (docs/07-open-questions.md, answered 2026-10-08): store **both** ring and offset — and ask
#: for offsets only in the modes where the offset *is* the signal. A scoring or competition entry
#: stays fast; a grouping session is worthless without the group's shape.
OFFSETS_REQUIRED_MODES: frozenset[SessionMode] = frozenset(
    {SessionMode.GROUPING, SessionMode.SHOT_EXECUTION_VOLUME}
)
OFFSETS_OPTIONAL_MODES: frozenset[SessionMode] = frozenset(
    {SessionMode.SCORING, SessionMode.COMPETITION_SIM, SessionMode.DISTANCE_MOVE, SessionMode.MIXED}
)


def offsets_required(mode: SessionMode) -> bool:
    """Whether this mode should ask the archer for a per-arrow (x, y) position."""
    return mode in OFFSETS_REQUIRED_MODES


class Shot(DomainRecord):
    """One arrow. Offsets are stored even when the ring is known: a 10 with 3 cm of drift is
    not the same shot as a 10 dead centre, and that difference is the signal (Q7)."""

    shot_id: str = Field(default_factory=lambda: new_id("shot"))
    end_id: str
    index: int = Field(ge=1, le=12)
    ring: int | None = Field(default=None, ge=1, le=10, description="None = unscored (blank bale)")
    is_x: bool = False
    is_miss: bool = False
    horizontal_offset_cm: float | None = Field(default=None, ge=-200.0, le=200.0)
    vertical_offset_cm: float | None = Field(default=None, ge=-200.0, le=200.0)
    shot_at: datetime | None = None
    note: str = ""

    @model_validator(mode="after")
    def _coherent_scoring(self) -> Shot:
        if self.is_miss and self.ring is not None:
            raise ValueError("a miss cannot also have a ring")
        if self.is_x and self.ring not in (10, None):
            raise ValueError("is_x=True is only valid on a 10 (or unscored data entry)")
        if (self.horizontal_offset_cm is None) != (self.vertical_offset_cm is None):
            raise ValueError(
                "provide both horizontal and vertical offsets, or neither — a half-recorded "
                "position cannot be used for group analysis"
            )
        return self

    @property
    def score_value(self) -> int:
        """Score for aggregation: X counts as 10, a miss as 0."""
        if self.is_miss:
            return 0
        return self.ring or 0


class EndStats(DomainRecord):
    """Derived per-end summary. Computed in pure functions, never by the model."""

    end_id: str
    arrows: int = Field(ge=0)
    scored_arrows: int = Field(ge=0)
    score_total: int = Field(ge=0)
    score_mean: float | None = None
    x_count: int = Field(ge=0)
    misses: int = Field(ge=0)
    group_radius_cm: float | None = None
    group_center_x_cm: float | None = None
    group_center_y_cm: float | None = None
