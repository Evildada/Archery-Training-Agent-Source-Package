"""Sensors for evidence: citations, coverage and claim strength.

AGENTS.md rule 3 is "no unsourced factual claim". This module is the enforcement mechanism, and
it is deliberately separate from the prompts: a guideline the model may forget is not a
guarantee, a validation that rejects the insight is.
"""

from __future__ import annotations

from archery_agent.domain.enums import EvidenceLabel, EvidenceTier
from archery_agent.domain.insight import Claim, EvidenceRef
from archery_agent.sensors.stats import Q_THRESHOLD, claim_label_for
from archery_agent.sensors.validators import Issue, Severity, ValidationResult

#: Claims about physiology, injury or psychology must rest on peer-reviewed work.
TIERS_REQUIRED_FOR_SENSITIVE_TOPICS: frozenset[EvidenceTier] = frozenset(
    {EvidenceTier.PEER_REVIEWED}
)

#: Decades matter less in coaching than in medicine, but a 40-year-old biomechanics paper is
#: not a description of modern compound equipment.
STALE_SOURCE_YEARS: int = 25


def validate_evidence_ref(ref: EvidenceRef) -> ValidationResult:
    issues: list[Issue] = []
    if not ref.quote and ref.tier is not EvidenceTier.PEER_REVIEWED:
        issues.append(
            Issue(
                code="ref_without_quote",
                severity=Severity.WARNING,
                message=f"{ref.source_id}: no quote recorded for a {ref.tier.value} source",
                field="quote",
                suggestion=(
                    "Record the passage relied on. It lets a coach check the claim without "
                    "chasing the document, which is the whole point of citing."
                ),
            )
        )
    if ref.tier is EvidenceTier.ANECDOTAL:
        issues.append(
            Issue(
                code="anecdotal_source",
                severity=Severity.WARNING,
                message=f"{ref.source_id} is an anecdotal source",
                field="tier",
                suggestion=(
                    "Anecdotal sources may illustrate, never support. The tier is displayed to "
                    "the archer with the claim."
                ),
            )
        )
    return ValidationResult(issues=tuple(issues))


def validate_claim_strength(claim: Claim) -> ValidationResult:
    """Does the claim's confidence match its evidence? The core honesty check."""
    issues: list[Issue] = []

    expected = claim_label_for(
        n=claim.n,
        q=claim.q_value,
        external=bool(claim.evidence_refs),
    )

    if (
        claim.evidence_label is EvidenceLabel.SUPPORTED
        and claim.n is None
        and not claim.evidence_refs
    ):
        issues.append(
            Issue(
                code="supported_without_evidence",
                severity=Severity.ERROR,
                message=f"claim labelled supported with neither data nor a reference: "
                f"{claim.statement[:80]!r}",
                field="evidence_label",
                suggestion="Downgrade the claim or attach the evidence.",
            )
        )

    if claim.evidence_label is EvidenceLabel.SUPPORTED and expected is not EvidenceLabel.SUPPORTED:
        issues.append(
            Issue(
                code="claim_stronger_than_evidence",
                severity=Severity.ERROR,
                message=(
                    f"claim is labelled SUPPORTED but the data supports at most "
                    f"{expected.value} (n={claim.n}, q={claim.q_value})"
                ),
                field="evidence_label",
                suggestion=(
                    "Use the computed label. This check exists because a confident sentence is "
                    "the easiest thing in the world to generate and the most expensive thing to "
                    "believe."
                ),
            )
        )

    if (
        claim.effect_size is None
        and claim.evidence_label
        in {
            EvidenceLabel.SUPPORTED,
            EvidenceLabel.PRELIMINARY,
        }
        and claim.n is not None
    ):
        issues.append(
            Issue(
                code="effect_without_size",
                severity=Severity.WARNING,
                message="an association claim carries no effect size",
                field="effect_size",
                suggestion=(
                    "Report the effect, not just its significance. 'Statistically detectable' "
                    "and 'worth changing your technique for' are different statements."
                ),
            )
        )

    if (
        claim.q_value is not None
        and claim.q_value >= Q_THRESHOLD
        and claim.evidence_label is EvidenceLabel.SUPPORTED
    ):
        issues.append(
            Issue(
                code="unadjusted_significance",
                severity=Severity.ERROR,
                message=f"q={claim.q_value:.3f} is above the {Q_THRESHOLD} threshold",
                field="q_value",
                suggestion="With many parameters tested, an uncorrected p-value is noise.",
            )
        )

    return ValidationResult(issues=tuple(issues))


def validate_evidence_coverage(
    claims: tuple[Claim, ...],
    refs: tuple[EvidenceRef, ...],
) -> ValidationResult:
    """Every non-derived claim must be traceable — to data or to a citation."""
    issues: list[Issue] = []
    available = {ref.source_id: ref for ref in refs}

    if claims and not refs:
        data_only = all(c.n is not None for c in claims)
        if not data_only:
            issues.append(
                Issue(
                    code="no_evidence_refs",
                    severity=Severity.ERROR,
                    message="insight contains claims that are neither data-backed nor cited",
                    field="evidence_refs",
                    suggestion=(
                        "Attach at least one reference, or restrict the insight to the archer's "
                        "own measured data."
                    ),
                )
            )

    for claim in claims:
        for source_id in claim.evidence_refs:
            if source_id not in available:
                issues.append(
                    Issue(
                        code="dangling_reference",
                        severity=Severity.ERROR,
                        message=f"claim cites {source_id}, which is not attached to the insight",
                        field="evidence_refs",
                    )
                )
        if claim.evidence_label is EvidenceLabel.GENERAL_EDUCATION and not claim.evidence_refs:
            issues.append(
                Issue(
                    code="education_without_source",
                    severity=Severity.ERROR,
                    message=f"general-education claim with no citation: {claim.statement[:60]!r}",
                    field="evidence_refs",
                    suggestion=("Educational content is still a factual claim. Cite it or cut it."),
                )
            )

    return ValidationResult(issues=tuple(issues))


def validate_source_tier_for_topic(ref: EvidenceRef, *, topic: str) -> ValidationResult:
    """Injury / psychology / physiology claims need peer-reviewed sources."""
    issues: list[Issue] = []
    sensitive = {"injury", "psychology", "physiology", "rehabilitation", "pain"}
    if topic.lower() in sensitive and ref.tier not in TIERS_REQUIRED_FOR_SENSITIVE_TOPICS:
        issues.append(
            Issue(
                code="tier_too_low_for_topic",
                severity=Severity.ERROR,
                message=f"{ref.source_id}: {ref.tier.value} is too weak for a {topic} claim",
                field="tier",
                suggestion="Use a peer-reviewed source, or drop the claim.",
            )
        )
    if ref.year < 2000 and topic.lower() in {"equipment", "biomechanics"}:
        issues.append(
            Issue(
                code="stale_equipment_source",
                severity=Severity.WARNING,
                message=f"{ref.source_id} predates modern compound equipment ({ref.year})",
                field="year",
                suggestion="Check whether the finding still applies to current cam systems.",
            )
        )
    return ValidationResult(issues=tuple(issues))
