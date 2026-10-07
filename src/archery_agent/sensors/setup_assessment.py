"""The setup report: what the archer actually gets when they ask "is my setup right?".

The whole design of this module is one rule, applied without exception:

    **A claim nobody can test is not printed.**

So a finding carries three things, not one:

1. the number, with a :class:`~archery_agent.domain.enums.Confidence` label;
2. the *basis* — what it was computed from;
3. when the confidence is weaker than measured, **the one range test that would settle it**.

Anything the system cannot answer yet does not become a hedge in prose. It goes into
:attr:`SetupReport.not_yet_answerable` as an experiment the archer can run — which is a more
useful thing to hand someone than an opinion.

That asymmetry is deliberate: an honest "I do not know, here is how we would find out" is worth
more to an archer than a confident sentence that happens to be wrong, because the second one gets
acted on.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from archery_agent.domain.entities import utcnow
from archery_agent.domain.enums import Confidence
from archery_agent.domain.equipment import EquipmentVersion
from archery_agent.sensors.validators import Issue, Severity, ValidationResult
from archery_agent.sim.arrow import (
    ArrowBuild,
    ShotContext,
    arrow_build_from_setup,
    evaluate_arrow_setup,
    foc_pct,
)
from archery_agent.sim.sights import SightMark, predict_sight_mark
from archery_agent.sim.spine import SpineCheck, check_spine

#: Confidence is ordered by *weakness*, not by "goodness": combining two labels keeps the weakest
#: thing you relied on. A number computed from an estimated input is an estimate, however exact
#: the arithmetic in between.
_WEAKNESS: dict[Confidence, int] = {
    Confidence.MEASURED: 0,
    Confidence.DERIVED: 1,
    Confidence.INTERPOLATED: 2,
    Confidence.ESTIMATED: 3,
    Confidence.UNVERIFIED: 4,
    Confidence.INSUFFICIENT_DATA: 5,
}

#: Labels that may only appear in a finding together with a named confirming test.
NEEDS_A_TEST: frozenset[Confidence] = frozenset(
    {Confidence.ESTIMATED, Confidence.INTERPOLATED, Confidence.UNVERIFIED}
)

#: The canonical confirming tests. Written once and shared, so that two findings settled by the
#: same measurement are reported as one instruction ("weigh a finished arrow") rather than two
#: near-identical ones. An archer at a range with a notebook should get a to-do list, not a
#: transcript.
TEST_WEIGH_ARROW = "Weigh one finished arrow on a grain scale and enter it as the measured mass."
TEST_BALANCE_POINT = (
    "Balance the arrow on a pencil edge and measure from the nock to the balance point: "
    "FOC = (balance point - half the shaft length) / shaft length, as a percentage."
)
TEST_BOW_SCALE = "Read the draw weight on a bow scale at your draw length."
TEST_BARESHAFT = (
    "Bareshaft beside three fletched arrows at the v1 distance: a nock tear on the stiff side "
    "means the shaft is weak for the bow, the other way means it is stiff."
)
TEST_CHRONOGRAPH = (
    "Shoot this exact arrow through a chronograph at your draw length and enter the reading."
)
TEST_SIGHT_MARK = "Shoot one arrow at that distance and record where it lands."


def combine(*labels: Confidence) -> Confidence:
    """The weakest input wins. Used for every derived number in the report."""
    if not labels:
        return Confidence.INSUFFICIENT_DATA
    return max(labels, key=lambda label: _WEAKNESS[label])


class Finding(BaseModel):
    """One labelled statement about the setup."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: str = Field(description="Registry key where one exists, else a report-local name.")
    statement: str
    value: float | None = None
    unit: str = ""
    confidence: Confidence
    basis: str = Field(description="What this was computed from. Never empty.")
    assumptions: tuple[str, ...] = ()
    confirming_test: str = Field(
        default="",
        description="The single range test that would raise this to MEASURED.",
    )

    @property
    def needs_test(self) -> bool:
        return self.confidence in NEEDS_A_TEST

    def line(self) -> str:
        value = (
            "" if self.value is None else f" {self.value:g}{(' ' + self.unit) if self.unit else ''}"
        )
        return f"{self.statement}{value} [{self.confidence.value}]"


class Experiment(BaseModel):
    """A question the system cannot answer yet, and the smallest test that would unlock it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    question: str
    needs: str
    unlocks: str


class SetupReport(BaseModel):
    """The assessment. Deterministic: same inputs, same report, forever."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    archer_id: str
    version_label: str
    generated_at: datetime = Field(default_factory=utcnow)
    findings: tuple[Finding, ...] = ()
    warnings: tuple[str, ...] = ()
    experiments: tuple[Experiment, ...] = ()
    changes_since_previous: str = ""

    @property
    def tests_to_run(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """``(test, subjects the test would settle)``, in report order.

        Grouped by test rather than by finding: one weigh-in fixes mass, FOC and grains per pound,
        and telling the archer that three times over is how a good instruction gets ignored.
        """
        grouped: dict[str, list[str]] = {}
        for finding in self.findings:
            if not finding.needs_test or not finding.confirming_test:
                continue
            grouped.setdefault(finding.confirming_test, []).append(finding.subject)
        return tuple((test, tuple(subjects)) for test, subjects in grouped.items())

    @property
    def measured_findings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.confidence is Confidence.MEASURED)

    def render(self) -> str:
        lines = [f"Setup: {self.version_label}"]
        if self.changes_since_previous:
            lines.append(f"Changed: {self.changes_since_previous}")
        lines.append("")
        for finding in self.findings:
            lines.append(f"  {finding.line()}")
            lines.append(f"      from: {finding.basis}")
        for warning in self.warnings:
            lines.append(f"  WARNING: {warning}")
        tests = self.tests_to_run
        if tests:
            lines.append("")
            estimates = sum(1 for f in self.findings if f.needs_test)
            lines.append(f"{estimates} estimate(s); {len(tests)} measurement(s) would settle them:")
            for test, subjects in tests:
                lines.append(f"  - {test}")
                lines.append(f"      settles: {', '.join(subjects)}")
        if self.experiments:
            lines.append("")
            lines.append("Not answerable yet — and what would answer it:")
            for experiment in self.experiments:
                lines.append(f"  - {experiment.question}")
                lines.append(f"      do: {experiment.needs}")
                lines.append(f"      gives: {experiment.unlocks}")
        return "\n".join(lines)


def _finding(**kwargs: object) -> Finding:
    """Build a finding, refusing to create one that would break the module's contract.

    This is the enforcement point: a future contributor adding a new ESTIMATED line without a
    test fails here, at the moment they write it, not in a report the archer reads six months
    later.
    """
    finding = Finding(**kwargs)  # type: ignore[arg-type]
    if not finding.basis.strip():
        raise ValueError(f"finding {finding.subject!r} has no basis — say what it came from")
    if finding.needs_test and not finding.confirming_test.strip():
        raise ValueError(
            f"finding {finding.subject!r} is {finding.confidence.value} but names no confirming "
            "test. Either supply the test, or do not print the claim."
        )
    return finding


def build_setup_report(
    version: EquipmentVersion,
    *,
    history: Sequence[EquipmentVersion] = (),
    shot: ShotContext | None = None,
    sight_marks: Sequence[SightMark] = (),
    spine_check: SpineCheck | None = None,
) -> SetupReport:
    """Assess one equipment version against the simulator and the archer's own records."""
    equipment = version.equipment
    findings: list[Finding] = []
    warnings: list[str] = []

    arrow = equipment.arrow
    build: ArrowBuild | None = None
    try:
        build = arrow_build_from_setup(arrow)
    except ValueError as exc:
        warnings.append(
            f"arrow is not complete enough to simulate: {exc}. The mass and spine checks below "
            "are unavailable until the shaft mass and length are entered."
        )

    # ---------------------------------------------------------------- mass
    mass = arrow.effective_total_mass_grains()
    if mass is None:
        warnings.append("arrow mass unknown: enter the shaft mass, or weigh a finished arrow.")
    else:
        weighed = arrow.is_weighed
        findings.append(
            _finding(
                subject="arrow.total_mass_grains",
                statement="Finished arrow mass",
                value=round(mass, 1),
                unit="gr",
                confidence=Confidence.MEASURED if weighed else Confidence.ESTIMATED,
                basis=(
                    "the archer weighed a finished arrow"
                    if weighed
                    else "summed from catalog component masses"
                ),
                assumptions=() if weighed else ("catalog masses run 0.5-2 % optimistic",),
                confirming_test="" if weighed else TEST_WEIGH_ARROW,
            )
        )

    # ---------------------------------------------------------------- FOC
    if build is not None:
        mass_label = next(
            (f.confidence for f in findings if f.subject == "arrow.total_mass_grains"),
            Confidence.INSUFFICIENT_DATA,
        )
        findings.append(
            _finding(
                subject="arrow.foc_pct",
                statement="Front-of-centre",
                value=round(foc_pct(build), 1),
                unit="%",
                confidence=combine(mass_label, Confidence.ESTIMATED),
                basis="mass distribution along the shaft, from the entered component masses",
                assumptions=(
                    "the insert sits at the shaft tip and the vanes at 1.5 in from the nock",
                ),
                confirming_test=TEST_BALANCE_POINT,
            )
        )

    # ---------------------------------------------------------------- grains per pound
    draw_weight = equipment.bow.draw_weight_lb
    if mass is not None and draw_weight:
        from archery_agent.sim.arrow import (
            COMMON_MIN_GRAINS_PER_POUND,
            DRY_FIRE_RISK_GRAINS_PER_POUND,
        )

        gr_per_lb = mass / float(draw_weight)
        weight_label = Confidence.ESTIMATED
        findings.append(
            _finding(
                subject="arrow.grains_per_pound",
                statement="Arrow mass per pound of draw weight",
                value=round(gr_per_lb, 2),
                unit="gr/lb",
                confidence=combine(mass_label, weight_label),
                basis=f"{mass:.1f} gr over the entered {float(draw_weight):g} lb draw weight",
                assumptions=(),
                confirming_test=TEST_BOW_SCALE,
            )
        )
        if gr_per_lb < DRY_FIRE_RISK_GRAINS_PER_POUND:
            warnings.append(
                f"{gr_per_lb:.2f} gr/lb is below the common "
                f"~{COMMON_MIN_GRAINS_PER_POUND:g} gr/lb guidance: dry-fire risk and string wear "
                "rise sharply. Check the bow manufacturer's minimum before shooting this "
                "combination."
            )
        elif gr_per_lb > 8.0:
            warnings.append(
                f"{gr_per_lb:.2f} gr/lb is heavy: expect a visibly arced trajectory and wide "
                "sight-mark gaps at longer distances."
            )

    # ---------------------------------------------------------------- spine
    if spine_check is None and arrow.shaft_spine_thou and draw_weight and arrow.shaft_length_in:
        spine_check = check_spine(
            draw_weight_lb=float(draw_weight),
            arrow_length_in=float(arrow.shaft_length_in),
            actual_spine_thou=float(arrow.shaft_spine_thou),
            point_mass_grains=float(arrow.point_mass_grains or 100.0),
        )
    if spine_check is not None:
        findings.append(
            _finding(
                subject="arrow.spine_fit_delta",
                statement=f"Static spine fit ({spine_check.verdict})",
                value=round(spine_check.delta_thou, 1),
                unit="thou vs chart",
                confidence=spine_check.confidence,
                basis=(
                    f"chart {spine_check.assumptions[0] if spine_check.assumptions else 'n/a'}; "
                    "positive means weaker (more deflection) than the chart recommends for this "
                    "draw weight and length"
                ),
                assumptions=spine_check.assumptions,
                confirming_test=spine_check.verification_step or TEST_BARESHAFT,
            )
        )

    # ---------------------------------------------------------------- speed, KE, momentum
    if build is not None and shot is None:
        warnings.append(
            "speed, kinetic energy and momentum are not reported: give the bow's IBO rating or a "
            "chronograph reading. An arrow's speed is never guessed from the bow's draw weight "
            "alone, and a guessed speed would quietly poison everything derived from it."
        )
    if build is not None and shot is not None:
        result = evaluate_arrow_setup(build, shot)
        if result.speed_fps is not None:
            speed_label = result.speed_confidence
            findings.append(
                _finding(
                    subject="arrow.speed_fps",
                    statement="Arrow speed",
                    value=round(result.speed_fps, 1),
                    unit="fps",
                    confidence=speed_label,
                    basis=(
                        "chronograph reading"
                        if speed_label is Confidence.MEASURED
                        else "projected from the bow's IBO rating and the community sensitivities"
                    ),
                    assumptions=result.assumptions,
                    confirming_test="" if speed_label is Confidence.MEASURED else TEST_CHRONOGRAPH,
                )
            )
            # Energy and momentum are computed from speed *and* mass, so they can be weak for
            # either reason. Each names one test: whichever input is weaker, speed first, since
            # kinetic energy scales with the square of it.
            derived_label = combine(speed_label, mass_label)
            if derived_label is Confidence.MEASURED:
                derived_test = ""
            elif speed_label is not Confidence.MEASURED:
                derived_test = TEST_CHRONOGRAPH
            else:
                derived_test = TEST_WEIGH_ARROW
            for subject, statement, value, unit in (
                (
                    "arrow.ke_ftlb",
                    "Kinetic energy",
                    None
                    if result.kinetic_energy_ft_lb is None
                    else round(result.kinetic_energy_ft_lb, 1),
                    "ft·lb",
                ),
                (
                    "arrow.momentum_lb_s",
                    "Momentum",
                    None if result.momentum_lb_s is None else round(result.momentum_lb_s, 3),
                    "lb·ft/s",
                ),
            ):
                if value is None:
                    continue
                findings.append(
                    _finding(
                        subject=subject,
                        statement=statement,
                        value=value,
                        unit=unit,
                        confidence=derived_label,
                        basis=f"computed from {result.total_mass_grains:.1f} gr at "
                        f"{result.speed_fps:.0f} fps",
                        assumptions=(),
                        confirming_test=derived_test,
                    )
                )
        warnings.extend(result.warnings)

    # ---------------------------------------------------------------- sight marks
    if sight_marks:
        prediction = predict_sight_mark(sight_marks, max(m.distance_m for m in sight_marks))
        if prediction.ok:
            findings.append(
                _finding(
                    subject="sight.mark_prediction",
                    statement=f"Predicted sight mark at {prediction.distance_m:g} m",
                    value=(
                        None
                        if prediction.predicted_mark is None
                        else round(prediction.predicted_mark, 2)
                    ),
                    unit="",
                    confidence=prediction.confidence,
                    basis=prediction.method,
                    assumptions=(),
                    confirming_test=prediction.verification_step or TEST_SIGHT_MARK,
                )
            )

    # ---------------------------------------------------------------- what is not known yet
    experiments = _experiments(version, history, spine_check)

    return SetupReport(
        archer_id=version.archer_id,
        version_label=version.label,
        findings=tuple(findings),
        warnings=tuple(warnings),
        experiments=experiments,
        changes_since_previous=version.describe_changes(),
    )


def _experiments(
    version: EquipmentVersion,
    history: Sequence[EquipmentVersion],
    spine_check: SpineCheck | None,
) -> tuple[Experiment, ...]:
    """Questions worth asking that this milestone cannot answer — with the test that would."""
    experiments: list[Experiment] = [
        Experiment(
            question="Is this setup scoring better than the previous one?",
            needs=(
                "At least 30 scored arrows on each setup, at the same distance and target face, "
                "with the equipment version recorded in the ledger (it is, automatically)."
            ),
            unlocks=(
                "A comparison with an effect size instead of a feeling. Below 30 arrows the "
                "system will keep saying 'not enough data', and it will be telling the truth."
            ),
        )
    ]
    if len(history) < 2:
        experiments.append(
            Experiment(
                question="Which of my past setups was the best?",
                needs=(
                    "Record a second equipment version (any change: point mass, spine, "
                    "draw weight)."
                ),
                unlocks="A change-point analysis: scores before and after each change.",
            )
        )
    if spine_check is None or spine_check.confidence is not Confidence.MEASURED:
        experiments.append(
            Experiment(
                question="Is the tune actually right for this bow and arrow?",
                needs=("One paper tear or bareshaft result at 18 m, recorded as a ledger row."),
                unlocks=(
                    "A tune recommendation grounded in this arrow rather than in a chart that is "
                    "explicitly marked unverified."
                ),
            )
        )
    if not version.equipment.arrow.is_weighed:
        experiments.append(
            Experiment(
                question="Is the arrow really the mass the catalogue claims?",
                needs="One finished arrow on a grain scale.",
                unlocks=(
                    "MEASURED mass, FOC and grains per pound, and a real answer about dry-fire "
                    "risk."
                ),
            )
        )
    return tuple(experiments)


def audit_setup_report(report: SetupReport) -> ValidationResult:
    """The sensor for the report's own contract. Runs in CI over the fixtures.

    This is not "does the report look nice" — it is the mechanical version of the promise in
    `docs/06-roadmap.md`: every claim labelled, every estimate testable.
    """
    issues: list[Issue] = []
    for finding in report.findings:
        if not finding.basis.strip():
            issues.append(
                Issue(
                    code="finding_without_basis",
                    severity=Severity.ERROR,
                    message=f"{finding.subject}: a finding must say what it came from",
                    field=finding.subject,
                )
            )
        if finding.needs_test and not finding.confirming_test.strip():
            issues.append(
                Issue(
                    code="untestable_claim",
                    severity=Severity.ERROR,
                    message=(
                        f"{finding.subject} is {finding.confidence.value} but names no confirming "
                        "test — a claim nobody can test must not be printed"
                    ),
                    field=finding.subject,
                    suggestion="Supply the range test, or measure the value instead.",
                )
            )
    for experiment in report.experiments:
        if not experiment.unlocks.strip():
            issues.append(
                Issue(
                    code="experiment_without_payoff",
                    severity=Severity.WARNING,
                    message=f"{experiment.question!r} does not say what it would unlock",
                )
            )
    return ValidationResult(issues=tuple(issues))
