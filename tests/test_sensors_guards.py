"""Sensors for standards, safety, load and citations."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from archery_agent.domain.enums import (
    EvidenceLabel,
    EvidenceTier,
    SessionMode,
    StandardOperator,
)
from archery_agent.domain.insight import Claim, EvidenceRef
from archery_agent.domain.standards import (
    Dose,
    PracticeInstruction,
    Standard,
    evaluate_standard,
)
from archery_agent.sensors.citations import (
    validate_claim_strength,
    validate_evidence_coverage,
    validate_evidence_ref,
)
from archery_agent.sensors.load import (
    LoadVerdict,
    acwr,
    monotony_strain,
    ramp_check,
    validate_load_progression,
)
from archery_agent.sensors.safety import (
    screen_discipline,
    screen_message,
    screen_scope_decision,
)
from archery_agent.sensors.standards import (
    validate_instruction,
    validate_standard,
)

# ------------------------------------------------------------------- standards


def test_a_standard_without_a_threshold_is_not_constructible() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="requires a threshold"):
        Standard(
            name="Work on your release",
            metric_key="outcome.group_radius_cm",
            operator=StandardOperator.LTE,
        )


def test_a_standard_with_an_absurd_threshold_is_rejected() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="outside the plausible range"):
        Standard(
            name="Group radius",
            metric_key="outcome.group_radius_cm",
            operator=StandardOperator.LTE,
            threshold=500.0,  # nobody's group is 5 m wide on a 40 cm face
        )


def test_standard_describes_itself_with_a_number_and_a_window() -> None:
    standard = Standard(
        name="Hold band",
        metric_key="cycle.hold_time_s",
        operator=StandardOperator.IN_BAND,
        band_lo=2.0,
        band_hi=4.0,
        window="end",
        n_min=6,
    )
    description = standard.describe()
    assert "2.0" in description and "4.0" in description
    assert "end" in description
    assert "n >= 6" in description


def test_evaluation_with_too_few_arrows_is_not_a_failure() -> None:
    standard = Standard(
        name="Group radius",
        metric_key="outcome.group_radius_cm",
        operator=StandardOperator.LTE,
        threshold=6.0,
        n_min=6,
    )
    evaluation = evaluate_standard(standard, 5.0, n=3)
    assert evaluation.passed is None
    assert not evaluation.evaluable
    assert "not evaluable, not a failure" in evaluation.reason


def test_evaluation_passes_and_fails_deterministically() -> None:
    standard = Standard(
        name="Group radius",
        metric_key="outcome.group_radius_cm",
        operator=StandardOperator.LTE,
        threshold=6.0,
        n_min=6,
    )
    assert evaluate_standard(standard, 5.9, n=6).passed is True
    assert evaluate_standard(standard, 6.1, n=6).passed is False


def test_standard_sensor_warns_about_coin_flip_sample_sizes() -> None:
    standard = Standard(
        name="One-arrow standard",
        metric_key="outcome.group_radius_cm",
        operator=StandardOperator.LTE,
        threshold=6.0,
        n_min=1,
        window="shot",
    )
    result = validate_standard(standard)
    codes = {issue.code for issue in result.issues}
    assert "standard_small_sample" in codes
    assert "standard_without_rationale" in codes


def test_instruction_requires_a_dose() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="dose"):
        PracticeInstruction(
            title="Improve your release",
            metric_key="outcome.group_radius_cm",
            operator=StandardOperator.LTE,
            threshold=6.0,
            window="end",
            n_min=6,
            dose=Dose(),
        )


def test_instruction_requires_a_measurable_criterion() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="inline criterion"):
        PracticeInstruction(title="Do better", dose=Dose(arrows=30))


def test_prescored_metric_on_a_blank_bale_is_refused() -> None:
    instruction = PracticeInstruction(
        title="Blank bale with a score target",
        mode=SessionMode.BLANK_BALE,
        metric_key="outcome.group_radius_cm",
        operator=StandardOperator.LTE,
        threshold=6.0,
        window="end",
        n_min=6,
        dose=Dose(arrows=36, ends=6),
    )
    result = validate_instruction(instruction)
    assert not result.ok
    assert any(issue.code == "scored_metric_on_blank_bale" for issue in result.errors)


def test_a_good_instruction_passes_every_check() -> None:
    instruction = PracticeInstruction(
        title="Hold discipline",
        focus_tag="hold",
        mode=SessionMode.GROUPING,
        distance_m=18.0,
        metric_key="cycle.hold_time_s",
        operator=StandardOperator.IN_BAND,
        band_lo=2.0,
        band_hi=4.0,
        window="end",
        n_min=6,
        dose=Dose(arrows=36, ends=6),
        execution_cue="into the back",
        stop_rule="stop if grip pressure reaches 4",
    )
    result = validate_instruction(instruction)
    assert result.ok, [i.message for i in result.errors]
    assert "success =" in instruction.describe()


# ---------------------------------------------------------------------- safety


@pytest.mark.parametrize(
    "text",
    [
        "I've had numbness in my fingers for a week",
        "I get dizzy when I stand after a long session",
        "my shoulder popped on the last end",
        "I can't sleep and I feel hopeless about competing",
        "I'm cutting weight for the competition next month",
        "should I take ibuprofen before shooting?",
    ],
)
def test_red_flags_route_to_referral(text: str) -> None:
    screen = screen_message(text)
    assert screen.action == "refer"
    assert screen.response
    assert "medical professional" in screen.response or "someone qualified" in screen.response


@pytest.mark.parametrize(
    "text",
    [
        "my shoulder hurts when I draw",
        "the bow arm gets sore after 100 arrows",
        "I ached all week after increasing poundage",
    ],
)
def test_pain_gets_a_clarifying_question_rather_than_a_shrug(text: str) -> None:
    screen = screen_message(text)
    assert screen.action == "clarify"
    assert screen.follow_up_question
    assert "don't assess or treat" in screen.response


def test_ordinary_text_passes_through() -> None:
    assert screen_message("my group opened up at 30 m today").action == "proceed"


def test_scope_screen_catches_other_disciplines() -> None:
    screen = screen_discipline("what clicker should I use on my recurve?")
    assert screen.action == "clarify"
    assert "compound" in screen.response
    decision = screen_scope_decision("should I switch to barebow?")
    assert not decision.in_scope
    assert decision.offered_alternatives


def test_scope_screen_ignores_compound_questions() -> None:
    assert screen_discipline("what hold time should I aim for?").action == "proceed"


# ------------------------------------------------------------------------ load


def test_acwr_needs_a_chronic_window_before_it_speaks() -> None:
    today = date(2026, 10, 7)
    sparse = [(today - timedelta(days=index), 100.0) for index in range(5)]
    result = acwr(sparse, today)
    assert result.verdict is LoadVerdict.INSUFFICIENT_DATA
    assert result.ratio is None
    assert "28 days" in result.message


def test_acwr_bands_are_reported_with_advice() -> None:
    today = date(2026, 10, 7)
    steady = [(today - timedelta(days=index), 100.0) for index in range(28)]
    assert acwr(steady, today).verdict is LoadVerdict.IN_BAND

    spiked = [(today - timedelta(days=index), 100.0) for index in range(7, 28)]
    spiked += [(today - timedelta(days=index), 400.0) for index in range(7)]
    high = acwr(spiked, today)
    assert high.verdict in {LoadVerdict.ELEVATED, LoadVerdict.HIGH}
    assert "caution" in high.message or "lighter week" in high.message


def test_ramp_warns_above_the_guidance() -> None:
    assert ramp_check(105.0, 100.0).verdict is LoadVerdict.IN_BAND
    assert ramp_check(150.0, 100.0).verdict is not LoadVerdict.IN_BAND
    assert ramp_check(50.0, 100.0).verdict is LoadVerdict.LOW


def test_monotony_detects_an_identical_week() -> None:
    flat = monotony_strain([100.0] * 7)
    assert flat.monotony == float("inf")
    assert "maximum monotony" in flat.message
    varied = monotony_strain([200.0, 40.0, 180.0, 30.0, 150.0, 20.0, 0.0])
    assert varied.monotony is not None and varied.monotony < 3.0


def test_pain_blocks_a_load_increase() -> None:
    result = validate_load_progression(
        proposed_weekly_load=1200.0,
        previous_weekly_load=600.0,
        pain_reported=True,
    )
    assert not result.ok
    codes = {issue.code for issue in result.errors}
    assert "load_blocked_pain" in codes


# ------------------------------------------------------------------- citations


def _ref(**overrides: object) -> EvidenceRef:
    payload: dict[str, object] = {
        "source_id": "smith2021",
        "title": "Hold time and score in compound archery",
        "author": "Smith et al.",
        "year": 2021,
        "venue": "Journal of Archery Science",
        "doi": "10.1234/jas.2021.001",
        "tier": EvidenceTier.PEER_REVIEWED,
        "quote": "Longer hold durations were associated with higher scores.",
    }
    payload.update(overrides)
    return EvidenceRef.model_validate(payload)


def test_a_reference_needs_a_way_to_be_checked() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="nobody can check it"):
        EvidenceRef(
            source_id="anon",
            title="Trust me",
            year=2020,
            tier=EvidenceTier.ANECDOTAL,
        )


def test_doi_and_url_shapes_are_validated() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="DOI"):
        _ref(doi="not-a-doi")
    with pytest.raises(ValidationError, match="resolvable"):
        _ref(url="ftp://example.com/paper")


def test_anecdotal_sources_must_show_their_quote() -> None:
    with pytest.raises(ValueError, match="quote"):
        EvidenceRef(
            source_id="forum-post",
            title="Someone on a forum says hold longer",
            year=2019,
            venue="forum",
            tier=EvidenceTier.ANECDOTAL,
        )


def test_claim_stronger_than_its_evidence_is_blocked() -> None:
    """n=40 is enough data, but q=0.4 means the data does not support the claim being made."""
    claim = Claim(
        statement="Grip pressure is driving your spread.",
        n=40,
        q_value=0.4,
        effect_size=0.1,
        evidence_label=EvidenceLabel.SUPPORTED,
    )
    result = validate_claim_strength(claim)
    assert not result.ok
    assert any(issue.code == "claim_stronger_than_evidence" for issue in result.errors)


def test_supported_claim_without_an_effect_size_warns() -> None:
    claim = Claim(
        statement="Hold time is associated with your score.",
        n=72,
        q_value=0.01,
        evidence_label=EvidenceLabel.SUPPORTED,
    )
    result = validate_claim_strength(claim)
    assert result.ok
    assert any(issue.code == "effect_without_size" for issue in result.warnings)


def test_educational_claims_need_a_citation() -> None:
    claim = Claim(
        statement="Research shows that target panic responds to routine work.",
        evidence_label=EvidenceLabel.GENERAL_EDUCATION,
    )
    coverage = validate_evidence_coverage((claim,), ())
    assert not coverage.ok
    assert any(issue.code == "education_without_source" for issue in coverage.errors)


def test_uncited_data_claim_is_flagged_but_a_data_backed_one_is_not() -> None:
    data_claim = Claim(
        statement="Your hold time averaged 2.5 s across 72 shots.",
        n=72,
        evidence_label=EvidenceLabel.PRELIMINARY,
    )
    ref = _ref()
    ok = validate_evidence_coverage((data_claim,), ())
    assert ok.ok, [i.message for i in ok.errors]

    literature_claim = Claim(
        statement="A published study found the same pattern.",
        n=72,
        evidence_refs=("missing-source",),
        evidence_label=EvidenceLabel.PRELIMINARY,
    )
    dangling = validate_evidence_coverage((literature_claim,), (ref,))
    assert not dangling.ok
    assert any(issue.code == "dangling_reference" for issue in dangling.errors)


def test_a_weak_source_is_flagged_even_when_well_formed() -> None:
    result = validate_evidence_ref(
        _ref(tier=EvidenceTier.COACHING_CONSENSUS, quote="", locator="ch. 4")
    )
    codes = {issue.code for issue in result.issues}
    assert "ref_without_quote" in codes

    anecdote = validate_evidence_ref(_ref(tier=EvidenceTier.ANECDOTAL))
    assert any(issue.code == "anecdotal_source" for issue in anecdote.warnings)


def test_sensitive_topics_require_peer_reviewed_sources() -> None:
    from archery_agent.sensors.citations import validate_source_tier_for_topic

    result = validate_source_tier_for_topic(
        _ref(tier=EvidenceTier.MANUFACTURER_DOC), topic="injury"
    )
    assert not result.ok
    assert any(issue.code == "tier_too_low_for_topic" for issue in result.errors)

    ok = validate_source_tier_for_topic(_ref(), topic="injury")
    assert ok.ok
