"""The domain layer: pure types, units, the parameter registry and target geometry.

Rules for this package (enforced by `.importlinter`):

* stdlib + pydantic only — no IO, no database, no HTTP, no model SDK;
* no import of any layer above `domain`;
* every persisted or tool-boundary type is a pydantic model with ``extra="forbid"``;
* units live in field names (``draw_weight_lb``), never in a bare field name.
"""

from __future__ import annotations

from archery_agent.domain.enums import (
    BetterDirection,
    BowType,
    CaptureCost,
    EvidenceTier,
    InsightKind,
    ObservationSource,
    ParameterCategory,
    ParameterKind,
    Reliability,
    SessionMode,
    StandardOperator,
)
from archery_agent.domain.units import (
    CM_PER_IN,
    FT_LB_TO_J,
    GRAIN_TO_G,
    IN_TO_CM,
    LB_TO_KG,
    MPS_TO_FPS,
    UNVERIFIED_CONSTANTS,
    cm_to_in,
    energy_ft_lb_to_joules,
    fps_to_mps,
    grains_to_grams,
    in_to_cm,
    joules_to_ft_lb,
    kg_to_lb,
    lb_to_kg,
    mps_to_fps,
)

__all__ = [
    "CM_PER_IN",
    "FT_LB_TO_J",
    "GRAIN_TO_G",
    "IN_TO_CM",
    "LB_TO_KG",
    "MPS_TO_FPS",
    "UNVERIFIED_CONSTANTS",
    "BetterDirection",
    "BowType",
    "CaptureCost",
    "EvidenceTier",
    "InsightKind",
    "ObservationSource",
    "ParameterCategory",
    "ParameterKind",
    "Reliability",
    "SessionMode",
    "StandardOperator",
    "cm_to_in",
    "energy_ft_lb_to_joules",
    "fps_to_mps",
    "grains_to_grams",
    "in_to_cm",
    "joules_to_ft_lb",
    "kg_to_lb",
    "lb_to_kg",
    "mps_to_fps",
]
