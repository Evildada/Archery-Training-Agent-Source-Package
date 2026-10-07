"""Unit conversions — the single place in the codebase where units are converted.

Convention (AGENTS.md rule 6): units live in field names, and a value is always stored in
the unit its parameter key declares. A mismatch is an error, never a silent conversion.
Conversions happen only at the boundary, via these functions.
"""

from __future__ import annotations

import math

# ------------------------------------------------------------------ constants

IN_TO_CM: float = 2.54
CM_PER_IN: float = 2.54
LB_TO_KG: float = 0.45359237
GRAIN_TO_G: float = 0.06479891
MPS_TO_FPS: float = 3.280839895
FT_LB_TO_J: float = 1.3558179483314004

#: Grains x fps^2 -> ft·lb.  Derived exactly from 2 * 7000 (grains per lb) * 32.17405 (g0).
#: Reference works often print 450_240 (a rounded constant); we use the exact value and
#: flag the difference in docs, because a 0.04 % discrepancy in kinetic energy is
#: defensible but an unexplained one is not.
GRAIN_FPS_TO_FTLB: float = 2 * 7000 * 32.17405

#: Domain constants that still need a rulebook/manufacturer source. Anything listed here is
#: surfaced in tool output as an assumption and flagged in `archery-agent doctor`.
#: Answering docs/07-open-questions.md Q8 clears this list.
UNVERIFIED_CONSTANTS: dict[str, str] = {
    "targets.THREE_SPOT_VERTICAL_40CM.spot_center_offsets_cm": (
        "Spot centre spacing for the 40 cm vertical 3-spot face is not yet sourced from the "
        "governing rulebook (docs/07-open-questions.md Q8). Ring geometry within a spot is "
        "derived and tested; spacing is treated as UNVERIFIED and must not be used for "
        "scoring decisions until confirmed."
    ),
    "sim.spine.DEFAULT_SPINE_CHART": (
        "The shipped spine chart is a placeholder shape, not a manufacturer chart. "
        "Spine recommendations are labelled UNVERIFIED until a sourced chart is loaded."
    ),
}


def in_to_cm(value_in: float) -> float:
    return value_in * IN_TO_CM


def cm_to_in(value_cm: float) -> float:
    return value_cm / IN_TO_CM


def lb_to_kg(value_lb: float) -> float:
    return value_lb * LB_TO_KG


def kg_to_lb(value_kg: float) -> float:
    return value_kg / LB_TO_KG


def grains_to_grams(value_gr: float) -> float:
    return value_gr * GRAIN_TO_G


def fps_to_mps(value_fps: float) -> float:
    return value_fps / MPS_TO_FPS


def mps_to_fps(value_mps: float) -> float:
    return value_mps * MPS_TO_FPS


def kinetic_energy_ft_lb(mass_grains: float, speed_fps: float) -> float:
    """Kinetic energy in ft·lb: ``m * v^2 / 450436.7`` with m in grains and v in ft/s."""
    if mass_grains < 0 or speed_fps < 0:
        raise ValueError("mass and speed must be non-negative")
    return mass_grains * speed_fps * speed_fps / GRAIN_FPS_TO_FTLB


def kinetic_energy_joules(mass_grains: float, speed_fps: float) -> float:
    return energy_ft_lb_to_joules(kinetic_energy_ft_lb(mass_grains, speed_fps))


def energy_ft_lb_to_joules(value_ft_lb: float) -> float:
    return value_ft_lb * FT_LB_TO_J


def joules_to_ft_lb(value_j: float) -> float:
    return value_j / FT_LB_TO_J


def momentum_lb_s(mass_grains: float, speed_fps: float) -> float:
    """Momentum in lb·ft/s — the better predictor of pass-through and penetration than KE."""
    if mass_grains < 0 or speed_fps < 0:
        raise ValueError("mass and speed must be non-negative")
    return (mass_grains / 7000.0 / 32.17405) * speed_fps


def group_radius_cm(offsets_cm: list[tuple[float, float]]) -> float:
    """Mean distance of impact points from the group *centroid* (mm-precision friendly).

    Uses the centroid rather than the point of aim on purpose: this measures precision
    (consistency), not accuracy (sight alignment). Both matter, and mixing them up is one of
    the most common confusions in practice reporting.
    """
    if not offsets_cm:
        raise ValueError("cannot compute a group radius from zero shots")
    cx = sum(x for x, _ in offsets_cm) / len(offsets_cm)
    cy = sum(y for _, y in offsets_cm) / len(offsets_cm)
    return sum(math.dist((x, y), (cx, cy)) for x, y in offsets_cm) / len(offsets_cm)


def group_center_cm(offsets_cm: list[tuple[float, float]]) -> tuple[float, float]:
    if not offsets_cm:
        raise ValueError("cannot compute a group centre from zero shots")
    n = len(offsets_cm)
    return (
        sum(x for x, _ in offsets_cm) / n,
        sum(y for _, y in offsets_cm) / n,
    )
