"""Deterministic physics and estimators — pure functions, no IO, no policy.

This layer answers *"what do the numbers say?"*; :mod:`archery_agent.sensors` answers
*"is this defensible?"*. Keeping them apart is what stops a scientific guardrail from
mutating into a scoring heuristic (docs/01-harness-architecture.md).

Every result carries ``assumptions`` and a ``confidence`` label. A function in this layer
that cannot state its assumptions must return ``Confidence.UNVERIFIED`` — never a silent
number (docs/04 §10).
"""

from __future__ import annotations

from archery_agent.sim.arrow import (
    ArrowBuild,
    ArrowSetupResult,
    ShotContext,
    SpeedModelParams,
    balance_point_in,
    estimate_speed_fps,
    foc_pct,
    optimize_arrow_setup,
    total_mass_grains,
)
from archery_agent.sim.sights import SightMark, SightMarkPrediction, predict_sight_mark
from archery_agent.sim.spine import (
    DEFAULT_SPINE_CHART,
    SpineChart,
    SpineCheck,
    check_spine,
)
from archery_agent.sim.tune import (
    TuneCandidate,
    TuneSymptom,
    TuningAdvice,
    advise_tuning,
)

__all__ = [
    "DEFAULT_SPINE_CHART",
    "ArrowBuild",
    "ArrowSetupResult",
    "ShotContext",
    "SightMark",
    "SightMarkPrediction",
    "SpeedModelParams",
    "SpineChart",
    "SpineCheck",
    "TuneCandidate",
    "TuneSymptom",
    "TuningAdvice",
    "advise_tuning",
    "balance_point_in",
    "check_spine",
    "estimate_speed_fps",
    "foc_pct",
    "optimize_arrow_setup",
    "predict_sight_mark",
    "total_mass_grains",
]
