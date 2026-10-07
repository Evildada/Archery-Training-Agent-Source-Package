"""Tune advisor: symptom -> ranked, reversible candidate adjustments.

The failure mode this module exists to prevent: an archer sees a right-hand tear and starts
turning screws, when the tear is a release-timing artefact that changes every end. So the
advisor refuses to rank hardware before it has seen evidence that the *archer* is repeatable:

* fewer than 6 arrows in the observed group -> the advice is "shoot a scored end first";
* group radius wide relative to what tuning can influence -> the advice is form work first.

Every candidate carries a cost and a risk, and the output always carries a verification
protocol, because a tuning change that is not re-tested is indistinguishable from a coincidence.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from archery_agent.domain.enums import Confidence

#: If the group radius exceeds this fraction of the distance, the spread is dominated by
#: execution variation rather than by a systematic tune fault. 0.4 % of distance is a 7.2 cm
#: radius (14 cm group) at 18 m and a 20 cm radius at 50 m — generous, because the cost of
#: chasing hardware when the archer is the variable is a lot higher than the cost of one more
#: grouping session.
GROUP_RADIUS_NOISE_FRACTION: float = 0.004
MIN_ARROWS_FOR_TUNING: int = 6


class TuneSymptom(StrEnum):
    PAPER_TEAR_RIGHT = "paper_tear_right"
    PAPER_TEAR_LEFT = "paper_tear_left"
    PAPER_TEAR_HIGH = "paper_tear_high"
    PAPER_TEAR_LOW = "paper_tear_low"
    GROUP_RIGHT = "group_right"
    GROUP_LEFT = "group_left"
    GROUP_HIGH = "group_high"
    GROUP_LOW = "group_low"
    VERTICAL_SPREAD = "vertical_spread"
    HORIZONTAL_SPREAD = "horizontal_spread"
    NOCK_HIGH = "nock_high"
    NOCK_LOW = "nock_low"


class TuneCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    adjustment: str
    expected_effect: str
    cost: str = Field(description="free | cheap | costs_arrows | irreversible")
    risk: str = Field(description="low | medium | high")
    reversible: bool = True
    notes: str = ""


_TABLE: dict[TuneSymptom, tuple[TuneCandidate, ...]] = {
    TuneSymptom.PAPER_TEAR_RIGHT: (
        TuneCandidate(
            adjustment="Move the rest slightly left",
            expected_effect="nock point tracks back toward centre",
            cost="free",
            risk="low",
        ),
        TuneCandidate(
            adjustment="Reduce arrow spine stiffness (weaker shaft or heavier point)",
            expected_effect="more dynamic flex, moves the tear left",
            cost="costs_arrows",
            risk="medium",
        ),
        TuneCandidate(
            adjustment="Check cam timing and nock travel first",
            expected_effect="removes a common non-tune cause of a horizontal tear",
            cost="free",
            risk="low",
            notes="Do this before any arrow change; out-of-sync cams mimic a spine problem.",
        ),
    ),
    TuneSymptom.PAPER_TEAR_LEFT: (
        TuneCandidate(
            adjustment="Move the rest slightly right",
            expected_effect="moves the tear toward centre",
            cost="free",
            risk="low",
        ),
        TuneCandidate(
            adjustment="Stiffer shaft or lighter point",
            expected_effect="less dynamic flex, moves the tear right",
            cost="costs_arrows",
            risk="medium",
        ),
    ),
    TuneSymptom.PAPER_TEAR_HIGH: (
        TuneCandidate(
            adjustment="Lower the nock point in small steps",
            expected_effect="moves the tear down",
            cost="cheap",
            risk="low",
        ),
        TuneCandidate(
            adjustment="Check arrow nock fit on the string",
            expected_effect="a tight nock mimics a high tear",
            cost="cheap",
            risk="low",
        ),
    ),
    TuneSymptom.PAPER_TEAR_LOW: (
        TuneCandidate(
            adjustment="Raise the nock point in small steps",
            expected_effect="moves the tear up",
            cost="cheap",
            risk="low",
        ),
    ),
    TuneSymptom.GROUP_RIGHT: (
        TuneCandidate(
            adjustment="Move the sight right",
            expected_effect="moves the group to the centre",
            cost="free",
            risk="low",
            notes="Check first that the *group* is right, not the sight mark drifted.",
        ),
        TuneCandidate(
            adjustment="Review bow-hand grip pressure",
            expected_effect="over-grip torques the bow and pushes groups horizontally",
            cost="free",
            risk="low",
        ),
    ),
    TuneSymptom.GROUP_LEFT: (
        TuneCandidate(
            adjustment="Move the sight left",
            expected_effect="moves the group to the centre",
            cost="free",
            risk="low",
        ),
        TuneCandidate(
            adjustment="Review release-hand tension and anchor position",
            expected_effect="a drifting anchor moves the group left",
            cost="free",
            risk="low",
        ),
    ),
    TuneSymptom.GROUP_HIGH: (
        TuneCandidate(
            adjustment="Move the sight down",
            expected_effect="lowers the group",
            cost="free",
            risk="low",
        ),
    ),
    TuneSymptom.GROUP_LOW: (
        TuneCandidate(
            adjustment="Move the sight up",
            expected_effect="raises the group",
            cost="free",
            risk="low",
            notes="A sudden low group at a familiar distance is often fatigue, not the sight.",
        ),
    ),
    TuneSymptom.VERTICAL_SPREAD: (
        TuneCandidate(
            adjustment="Check nock point height and cam sync",
            expected_effect="removes systematic vertical spread",
            cost="free",
            risk="low",
        ),
        TuneCandidate(
            adjustment="Hold time consistency work",
            expected_effect="vertical spread commonly tracks hold-time variation",
            cost="free",
            risk="low",
            notes="A form candidate in hardware clothing — log hold time for a session first.",
        ),
    ),
    TuneSymptom.HORIZONTAL_SPREAD: (
        TuneCandidate(
            adjustment="Check grip pressure consistency and shoulder line",
            expected_effect="horizontal spread usually tracks grip/torque variation",
            cost="free",
            risk="low",
        ),
        TuneCandidate(
            adjustment="Check rest centreshot and fletching clearance",
            expected_effect="contact can throw arrows laterally",
            cost="cheap",
            risk="low",
        ),
    ),
    TuneSymptom.NOCK_HIGH: (
        TuneCandidate(
            adjustment="Lower nock point / check D-loop height",
            expected_effect="levels nock travel",
            cost="cheap",
            risk="low",
        ),
    ),
    TuneSymptom.NOCK_LOW: (
        TuneCandidate(
            adjustment="Raise nock point / check D-loop height",
            expected_effect="levels nock travel",
            cost="cheap",
            risk="low",
        ),
    ),
}


class TuningAdvice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    symptom: TuneSymptom
    candidates: tuple[TuneCandidate, ...] = ()
    blocked_by: str = ""
    confidence: Confidence = Confidence.ESTIMATED
    verification_protocol: str = ""
    assumptions: tuple[str, ...] = ()

    @property
    def actionable(self) -> bool:
        return not self.blocked_by and bool(self.candidates)


def advise_tuning(
    symptom: TuneSymptom,
    *,
    arrows_observed: int | None = None,
    group_radius_cm: float | None = None,
    distance_m: float | None = None,
) -> TuningAdvice:
    """Rank hardware candidates — but only once the archer's execution looks repeatable."""
    if arrows_observed is not None and arrows_observed < MIN_ARROWS_FOR_TUNING:
        return TuningAdvice(
            symptom=symptom,
            blocked_by=(
                f"only {arrows_observed} arrows observed — a tune decision needs at least "
                f"{MIN_ARROWS_FOR_TUNING} so that one stray arrow cannot define the setup"
            ),
            confidence=Confidence.INSUFFICIENT_DATA,
            verification_protocol="Shoot a scored 6-arrow end, then re-observe the symptom.",
        )

    if (
        group_radius_cm is not None
        and distance_m is not None
        and group_radius_cm > GROUP_RADIUS_NOISE_FRACTION * distance_m * 100.0
    ):
        return TuningAdvice(
            symptom=symptom,
            blocked_by=(
                f"group radius {group_radius_cm:.1f} cm at {distance_m:g} m is dominated by "
                "execution variation, not by a systematic tune fault. Adjusting hardware now "
                "would be fitting noise."
            ),
            confidence=Confidence.INSUFFICIENT_DATA,
            verification_protocol=(
                "Run three sessions of grouping work on the parameter the symptom suggests "
                "(grip, anchor, hold), then re-measure. Tune only against a repeatable pattern."
            ),
        )

    return TuningAdvice(
        symptom=symptom,
        candidates=_TABLE[symptom],
        confidence=Confidence.ESTIMATED,
        verification_protocol=(
            "Change ONE thing. Shoot at least 6 arrows (preferably 12) and record the new group "
            "centre. If the symptom does not move in the predicted direction, revert before "
            "trying the next candidate."
        ),
        assumptions=(
            "the bow is otherwise within the manufacturer's published specification",
            "arrows in the group share the same shaft, length and point mass",
        ),
    )
