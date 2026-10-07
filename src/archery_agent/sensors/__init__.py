"""Deterministic sensors — the feedback half of the harness.

Every function here is pure: no IO, no network, no model, no clock beyond an explicit
argument. That is what allows the same checks to run inside the agent loop *and* in CI with
no provider configured (docs/05-sensors-and-evals.md).

Naming convention: ``validate_*`` returns a
:class:`~archery_agent.sensors.validators.ValidationResult`; everything else returns a typed,
deterministic result object.
"""

from __future__ import annotations

from archery_agent.sensors.citations import (
    validate_claim_strength,
    validate_evidence_coverage,
    validate_evidence_ref,
)
from archery_agent.sensors.load import (
    AcwrResult,
    LoadVerdict,
    acwr,
    monotony_strain,
    ramp_check,
    validate_load_progression,
)
from archery_agent.sensors.safety import (
    REFERRAL_TEMPLATE,
    SafetyCategory,
    SafetyScreen,
    screen_discipline,
    screen_message,
)
from archery_agent.sensors.standards import validate_instruction, validate_standard
from archery_agent.sensors.stats import (
    MIN_SESSIONS_FOR_TREND,
    MIN_SHOTS_FOR_EFFECT,
    Q_THRESHOLD,
    EffectEstimate,
    TrendResult,
    claim_label_for,
    effects,
    mad,
    mean,
    ols_trend,
    pearson,
    percentile,
    q_values,
    sample_sd,
    summarise,
    trend_label_for,
)
from archery_agent.sensors.validators import (
    Issue,
    Severity,
    ValidationResult,
    validate_analysis_window,
    validate_parameter_observation,
    validate_record,
)

__all__ = [
    "MIN_SESSIONS_FOR_TREND",
    "MIN_SHOTS_FOR_EFFECT",
    "Q_THRESHOLD",
    "REFERRAL_TEMPLATE",
    "AcwrResult",
    "EffectEstimate",
    "Issue",
    "LoadVerdict",
    "SafetyCategory",
    "SafetyScreen",
    "Severity",
    "TrendResult",
    "ValidationResult",
    "acwr",
    "claim_label_for",
    "effects",
    "mad",
    "mean",
    "monotony_strain",
    "ols_trend",
    "pearson",
    "percentile",
    "q_values",
    "ramp_check",
    "sample_sd",
    "screen_discipline",
    "screen_message",
    "summarise",
    "trend_label_for",
    "validate_analysis_window",
    "validate_claim_strength",
    "validate_evidence_coverage",
    "validate_evidence_ref",
    "validate_instruction",
    "validate_load_progression",
    "validate_parameter_observation",
    "validate_record",
    "validate_standard",
]
