"""Equipment tools: record history, read history, and assess the current setup.

``equipment.record`` is the only one that writes, it is ``WRITE_DRAFT`` (so it needs explicit
approval), and it writes **two** things: the equipment version, and the registry rows that make
that version visible to the ledger. Forgetting the second would silently disconnect the equipment
history from the statistics — the exact failure the change-point analysis depends on not having.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from archery_agent.domain.entities import ArrowSetup, Bow, EquipmentSet, Release, utcnow
from archery_agent.domain.enums import Confidence, RiskLevel
from archery_agent.domain.equipment import EquipmentVersion, record_version
from archery_agent.sensors.setup_assessment import audit_setup_report, build_setup_report
from archery_agent.sim.arrow import ShotContext
from archery_agent.sim.sights import SightMark
from archery_agent.tools.registry import ToolContext, ToolResult, ToolSpec

# --------------------------------------------------------------------- inputs


class ArrowSetupInput(BaseModel):
    """A complete arrow build. Mirror of :class:`domain.entities.ArrowSetup`, kept flat."""

    model_config = ConfigDict(extra="forbid")

    brand: str = Field(min_length=1)
    model: str = Field(min_length=1)
    shaft_spine_thou: float | None = Field(default=None, gt=0.0)
    shaft_length_in: float | None = Field(default=None, gt=0.0, le=34.0)
    shaft_mass_grains: float | None = Field(default=None, gt=0.0)
    insert_mass_grains: float | None = Field(default=None, ge=0.0)
    point_mass_grains: float | None = Field(default=None, gt=0.0)
    nock_mass_grains: float | None = Field(default=None, ge=0.0)
    measured_total_mass_grains: float | None = Field(default=None, gt=0.0)


class BowInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand: str = Field(min_length=1)
    model: str = Field(min_length=1)
    draw_weight_lb: float | None = Field(default=None, gt=0.0)
    draw_length_in: float | None = Field(default=None, gt=0.0)
    let_off_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    brace_height_in: float | None = Field(default=None, gt=0.0)
    axle_to_axle_in: float | None = Field(default=None, gt=0.0)


class ReleaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release_type: str = "thumb_button"
    brand: str = Field(min_length=1)
    model: str = Field(min_length=1)


class EquipmentRecordInput(BaseModel):
    """Record a new, dated version of the archer's setup."""

    model_config = ConfigDict(extra="forbid")

    archer_id: str
    bow: BowInput
    arrow: ArrowSetupInput
    release: ReleaseInput | None = None
    accessories: dict[str, str] = Field(default_factory=dict)
    effective_from: str = Field(
        default="",
        description="ISO date the setup started being shot. Empty = now. Set it in the past when "
        "typing in a change that already happened.",
    )
    reason: str = Field(default="", max_length=200)


class EquipmentHistoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archer_id: str
    include_changes: bool = True


class EquipmentAssessInput(BaseModel):
    """Assess the current setup. All physics inputs are optional: missing ones are reported."""

    model_config = ConfigDict(extra="forbid")

    archer_id: str
    ibo_fps: float | None = Field(default=None, gt=0.0, le=400.0)
    measured_speed_fps: float | None = Field(default=None, gt=0.0, le=400.0)
    sight_marks: tuple[dict[str, Any], ...] = ()


# ------------------------------------------------------------------- handlers


def _to_equipment_set(payload: EquipmentRecordInput) -> EquipmentSet:
    arrow_payload = payload.arrow.model_dump()
    bow_payload = payload.bow.model_dump()
    release = Release(**payload.release.model_dump()) if payload.release is not None else None
    return EquipmentSet(
        archer_id=payload.archer_id,
        bow=Bow(**bow_payload),
        release=release,
        arrow=ArrowSetup(**arrow_payload),
        accessories=dict(payload.accessories),
    )


def handle_record(payload: BaseModel, ctx: ToolContext) -> ToolResult:
    assert isinstance(payload, EquipmentRecordInput)
    store = ctx.store
    if store is None or not hasattr(store, "append_version"):
        return ToolResult.failure(
            "the configured store does not keep an equipment history; the CLI uses SQLite at "
            "data/archery.db — an in-memory store cannot hold a version history across runs"
        )

    history = store.versions(payload.archer_id)
    equipment = _to_equipment_set(payload)
    effective_from = utcnow()
    if payload.effective_from:
        try:
            from datetime import datetime

            parsed = datetime.fromisoformat(payload.effective_from)
        except ValueError:
            return ToolResult.failure(
                f"effective_from {payload.effective_from!r} is not an ISO date; use YYYY-MM-DD"
            )
        effective_from = parsed if parsed.tzinfo else parsed.replace(tzinfo=utcnow().tzinfo)

    version = record_version(
        archer_id=payload.archer_id,
        equipment=equipment,
        history=history,
        effective_from=effective_from,
        reason=payload.reason,
    )
    store.append_version(version)

    ledger = store.append(version.ledger_observations())
    warnings = list(ledger.warnings)
    if ledger.rejected:
        warnings.append(
            f"{len(ledger.rejected)} ledger row(s) rejected: "
            + "; ".join(f"{r.get('key')}: {r.get('reason')}" for r in ledger.rejected)
        )

    return ToolResult.success(
        {
            "version_id": version.version_id,
            "version": version.version,
            "label": version.label,
            "changes": [change.describe() for change in version.changes],
            "ledger_rows": len(ledger.accepted),
            "summary": f"recorded {version.label}: {version.describe_changes()}",
        },
        confidence=Confidence.MEASURED,
        assumptions=(
            "the equipment rows were written to the ledger so later analysis can see which setup "
            "produced which arrows",
        ),
        warnings=tuple(warnings),
        snapshot_hash=ctx.store.snapshot_hash(),
    )


def handle_history(payload: BaseModel, ctx: ToolContext) -> ToolResult:
    assert isinstance(payload, EquipmentHistoryInput)
    store = ctx.store
    if store is None or not hasattr(store, "versions"):
        return ToolResult.failure("no equipment history available in this store")
    versions: tuple[EquipmentVersion, ...] = store.versions(payload.archer_id)
    if not versions:
        return ToolResult.success(
            {"versions": [], "summary": "no equipment recorded yet for this archer"},
            confidence=Confidence.INSUFFICIENT_DATA,
            warnings=("nothing to analyse until a setup is recorded",),
        )
    return ToolResult.success(
        {
            "versions": [
                {
                    "version": version.version,
                    "label": version.label,
                    "effective_from": version.effective_from.isoformat(),
                    "reason": version.reason,
                    "changes": [c.describe() for c in version.changes]
                    if payload.include_changes
                    else [],
                }
                for version in versions
            ],
            "current": versions[-1].label,
            "summary": f"{len(versions)} equipment version(s); current is {versions[-1].label}",
        },
        confidence=Confidence.MEASURED,
        snapshot_hash=ctx.store.snapshot_hash(),
    )


def handle_assess(payload: BaseModel, ctx: ToolContext) -> ToolResult:
    assert isinstance(payload, EquipmentAssessInput)
    store = ctx.store
    if store is None or not hasattr(store, "current_version"):
        return ToolResult.failure("no equipment history available in this store")
    version = store.current_version(payload.archer_id)
    if version is None:
        return ToolResult.failure(
            "no equipment recorded for this archer yet — ask for the bow and arrow build first, "
            "then assess. Guessing a setup from a description is how a report becomes fiction."
        )

    # A ShotContext needs both a draw weight and a draw length; without them the speed tools
    # cannot run at all, and the report says so rather than substituting a guess.
    shot = None
    bow = version.equipment.bow
    if (
        (payload.ibo_fps or payload.measured_speed_fps)
        and bow.draw_weight_lb
        and bow.draw_length_in
    ):
        shot = ShotContext(
            draw_weight_lb=float(bow.draw_weight_lb),
            draw_length_in=float(bow.draw_length_in),
            ibo_fps=payload.ibo_fps,
            measured_speed_fps=payload.measured_speed_fps,
        )

    try:
        marks = tuple(SightMark(**mark) for mark in payload.sight_marks)
    except Exception as exc:
        return ToolResult.failure(
            f"sight marks were not understood ({exc}). Each needs distance_m and mark."
        )

    report = build_setup_report(
        version, history=store.versions(payload.archer_id), shot=shot, sight_marks=marks
    )
    audit = audit_setup_report(report)
    if not audit.ok:
        # The report's own contract failed. That is a bug in this harness, and returning the
        # report anyway would leak an unlabelled claim to the archer.
        return ToolResult.failure(
            "the setup report failed its own audit; refusing to return it",
            warnings=tuple(issue.message for issue in audit.errors),
        )

    return ToolResult.success(
        {
            "version_label": report.version_label,
            "findings": [
                {
                    "subject": finding.subject,
                    "statement": finding.statement,
                    "value": finding.value,
                    "unit": finding.unit,
                    "confidence": finding.confidence.value,
                    "basis": finding.basis,
                    "confirming_test": finding.confirming_test,
                }
                for finding in report.findings
            ],
            "changes_since_previous": report.changes_since_previous,
            "experiments": [experiment.model_dump() for experiment in report.experiments],
            "rendered": report.render(),
            "summary": (
                f"{len(report.findings)} labelled finding(s) for {report.version_label}; "
                f"{len(report.tests_to_run)} range test(s) would settle the "
                f"{sum(1 for f in report.findings if f.needs_test)} estimate(s)"
            ),
        },
        # The *report* is estimated because most of its lines are; every line carries its own
        # label, and the rendered text is the deliverable the archer reads.
        confidence=Confidence.ESTIMATED,
        assumptions=(
            "each finding carries its own confidence label and basis; a finding whose confidence "
            "is weaker than measured names the range test that would settle it",
        ),
        warnings=report.warnings,
        snapshot_hash=ctx.store.snapshot_hash(),
    )


SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="equipment.record",
        summary="Record a new dated version of the bow/release/arrow build (append-only).",
        risk=RiskLevel.WRITE_DRAFT,
        input_model=EquipmentRecordInput,
        handler=handle_record,
        tags=("equipment", "capture"),
        output_hint="version_id, version, changes[], ledger_rows",
    ),
    ToolSpec(
        name="equipment.history",
        summary="Every equipment version this archer has recorded, oldest first.",
        risk=RiskLevel.READ,
        input_model=EquipmentHistoryInput,
        handler=handle_history,
        tags=("equipment",),
        output_hint="versions[] with the change list for each",
    ),
    ToolSpec(
        name="equipment.assess",
        summary=(
            "Assess the current setup: labelled findings, each estimate naming the range test "
            "that would settle it."
        ),
        risk=RiskLevel.READ,
        input_model=EquipmentAssessInput,
        handler=handle_assess,
        tags=("equipment", "report"),
        output_hint="findings[] with confidence + confirming_test, plus the rendered report",
    ),
)
