"""Closed sets used across the domain.

If a value could plausibly be one of several known options, it is an enum here — never a
free string. Free strings in a training log become data corruption the first time someone
writes "Hinge " with a trailing space.
"""

from __future__ import annotations

from enum import StrEnum


class BowType(StrEnum):
    """v1 is compound-only by design decision (AGENTS.md rule 1)."""

    COMPOUND = "compound"

    @classmethod
    def _missing_(cls, value: object) -> BowType:
        raise ValueError(
            "this system models compound bows only (v1 scope). "
            f"Got {value!r}. Recurve, barebow and traditional are out of scope by design — "
            "see docs/00-product-brief.md."
        )


class SessionMode(StrEnum):
    BLANK_BALE = "blank_bale"
    GROUPING = "grouping"
    SCORING = "scoring"
    COMPETITION_SIM = "competition_sim"
    DISTANCE_MOVE = "distance_move"
    SHOT_EXECUTION_VOLUME = "shot_execution_volume"
    GYM = "gym"
    MIXED = "mixed"


class ParameterCategory(StrEnum):
    ANTHROPOMETRIC = "anthropometric"
    BOW_SETUP = "bow_setup"
    RELEASE = "release"
    ARROW = "arrow"
    CYCLE_TIMING = "cycle_timing"
    CYCLE_TENSION = "cycle_tension"
    AIM = "aim"
    MENTAL = "mental"
    OUTCOME = "outcome"
    LOAD = "load"
    ENVIRONMENT = "environment"
    ADHERENCE = "adherence"


class ParameterKind(StrEnum):
    RATIO = "ratio"
    INTERVAL = "interval"
    ORDINAL = "ordinal"
    CATEGORICAL = "categorical"
    COUNT = "count"
    BOOLEAN = "boolean"


class BetterDirection(StrEnum):
    HIGHER = "higher"
    LOWER = "lower"
    BAND = "band"
    NONE = "none"


class CaptureCost(StrEnum):
    FREE = "free"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ObservationSource(StrEnum):
    SELF_REPORTED = "self_reported"
    COACH_RATED = "coach_rated"
    SENSOR = "sensor"
    DERIVED = "derived"
    IMPORTED = "imported"


class Reliability(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class StandardOperator(StrEnum):
    LTE = "lte"
    GTE = "gte"
    IN_BAND = "in_band"
    EQUALS_BAND = "equals_band"


class EvidenceTier(StrEnum):
    PEER_REVIEWED = "peer_reviewed"
    COACHING_CONSENSUS = "coaching_consensus"
    MANUFACTURER_DOC = "manufacturer_doc"
    ANECDOTAL = "anecdotal"


class EvidenceLabel(StrEnum):
    """How strongly the archer's *own data* supports a claim."""

    SUPPORTED = "supported"
    PRELIMINARY = "preliminary"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    GENERAL_EDUCATION = "general_education"


class InsightKind(StrEnum):
    OBSERVATION = "observation"
    RECOMMENDATION = "recommendation"
    PLAN = "plan"
    EDUCATION = "education"
    CAPTURE_SUMMARY = "capture_summary"


class Confidence(StrEnum):
    """How a *number* was obtained. Required on every tool result (docs/04 §10)."""

    MEASURED = "measured"
    DERIVED = "derived"
    ESTIMATED = "estimated"
    INTERPOLATED = "interpolated"
    UNVERIFIED = "unverified"
    INSUFFICIENT_DATA = "insufficient_data"


class RiskLevel(StrEnum):
    READ = "read"
    WRITE_DRAFT = "write_draft"
    WRITE = "write"
    PUBLISH = "publish"
    DENY = "deny"
