"""Command line interface.

M0 commands are diagnostic rather than conversational on purpose: before a model is attached, the
useful thing to check is whether the *harness* is sound — registry, sensors, architecture,
simulator, and one full deterministic turn.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

from archery_agent import __version__
from archery_agent.agents import SPECS, Dispatcher, NullRunner
from archery_agent.domain.enums import ParameterCategory, RiskLevel
from archery_agent.domain.ids import new_id
from archery_agent.domain.parameters import (
    CORE_PARAMETERS,
    REGISTRY,
    by_category,
    low_capture_cost,
    validate_registry,
)
from archery_agent.domain.units import UNVERIFIED_CONSTANTS
from archery_agent.interfaces.demo import DEMO_ARCHER_ID, DemoPlanner, seed_demo_ledger
from archery_agent.runtime.events import EventLog
from archery_agent.runtime.loop import CoachingLoop
from archery_agent.sim.arrow import ArrowBuild, ShotContext, evaluate_arrow_setup
from archery_agent.store.knowledge_base import KnowledgeBase
from archery_agent.store.memory import InMemoryLedger
from archery_agent.store.sqlite import SqliteStore, append_only_probe
from archery_agent.tools.builtin import SUBAGENT_TOOLS, build_registry
from archery_agent.tools.registry import ToolContext, ToolRegistry


def _cmd_version(_: argparse.Namespace) -> int:
    print(f"archery-agent {__version__}")
    return 0


def _cmd_params(args: argparse.Namespace) -> int:
    definitions = list(REGISTRY.values())
    if args.category:
        definitions = list(by_category(ParameterCategory(args.category)))
    if args.low_cost:
        cheap = {d.key for d in low_capture_cost()}
        definitions = [d for d in definitions if d.key in cheap]
    if args.core:
        definitions = [d for d in definitions if d.key in CORE_PARAMETERS]
        print(
            "the mandatory capture set (Q5): eleven keys covering ten concepts. Everything else "
            "stays registered and can be promoted later.\n"
        )

    print(f"{len(definitions)} parameter(s) registered\n")
    header = f"{'key':38} {'unit':8} {'better':7} {'cost':7} label"
    print(header)
    print("-" * len(header))
    for definition in sorted(definitions, key=lambda d: d.key):
        print(
            f"{definition.key:38} {definition.unit or '-':8} {definition.better.value:7} "
            f"{definition.capture_cost.value:7} {definition.label}"
        )
    if not args.brief:
        print("\nnotes:")
        for definition in sorted(definitions, key=lambda d: d.key):
            if definition.notes:
                print(f"- {definition.key}: {definition.notes}")
    return 0


def _open_store(args: argparse.Namespace) -> SqliteStore:
    """The CLI always uses the real database: an equipment history has to survive a restart."""
    return SqliteStore(Path(args.db))


def _equipment_context(store: SqliteStore, archer_id: str) -> ToolContext:
    return ToolContext(run_id=new_id("run"), archer_id=archer_id, store=store)


def _cmd_equipment(args: argparse.Namespace) -> int:
    from archery_agent.tools.impl import equipment_tools

    action = args.action
    with _open_store(args) as store:
        ctx = _equipment_context(store, args.archer)

        if action == "record":
            bow: dict[str, object] = {"brand": args.bow_brand, "model": args.bow_model}
            arrow: dict[str, object] = {"brand": args.arrow_brand, "model": args.arrow_model}
            for field, value in (
                ("draw_weight_lb", args.draw_weight),
                ("draw_length_in", args.draw_length),
                ("let_off_pct", args.let_off),
                ("brace_height_in", args.brace_height),
                ("axle_to_axle_in", args.ata),
            ):
                if value is not None:
                    bow[field] = value
            for field, value in (
                ("shaft_spine_thou", args.spine),
                ("shaft_length_in", args.length),
                ("shaft_mass_grains", args.shaft_mass),
                ("point_mass_grains", args.point_mass),
                ("insert_mass_grains", args.insert_mass),
                ("nock_mass_grains", args.nock_mass),
                ("measured_total_mass_grains", args.measured_mass),
            ):
                if value is not None:
                    arrow[field] = value

            payload = {
                "archer_id": args.archer,
                "bow": bow,
                "arrow": arrow,
                "reason": args.reason,
                "effective_from": args.effective_from or "",
            }
            result = equipment_tools.handle_record(
                equipment_tools.EquipmentRecordInput.model_validate(payload), ctx
            )
            print(result.context_block(char_budget=100_000))
            return 0 if result.ok else 1

        if action == "history":
            result = equipment_tools.handle_history(
                equipment_tools.EquipmentHistoryInput(archer_id=args.archer), ctx
            )
            if not result.ok:
                print(result.context_block(char_budget=100_000))
                return 1
            # ToolResult.data is a JSON-ish union by design (registry.py); the CLI is the one
            # place that knows the shape this tool promises.
            data = cast(dict[str, Any], result.data)
            versions = cast(list[dict[str, Any]], data["versions"])
            if not versions:
                print(f"no equipment recorded for {args.archer}")
                return 0
            for entry in versions:
                print(f"v{entry['version']}  {entry['label']}")
                print(f"     from {entry['effective_from'][:10]}  reason: {entry['reason'] or '-'}")
                for change in entry["changes"]:
                    print(f"     - {change}")
            return 0

        result = equipment_tools.handle_assess(
            equipment_tools.EquipmentAssessInput(
                archer_id=args.archer, ibo_fps=args.ibo, measured_speed_fps=args.speed
            ),
            ctx,
        )
        if not result.ok:
            print(result.context_block(char_budget=100_000))
            print(
                "\nNothing to assess yet. Record the setup first:\n"
                "  archery-agent equipment record --archer arc_1 --bow-brand ... "
                "--bow-model ... --arrow-brand ... --arrow-model ... --spine 340",
                file=sys.stderr,
            )
            return 1
        print(cast(dict[str, Any], result.data)["rendered"])
        return 0


def _cmd_simulate(args: argparse.Namespace) -> int:
    build = ArrowBuild(
        brand=args.brand,
        model=args.model,
        shaft_length_in=args.length,
        shaft_mass_grains=args.shaft_mass,
        insert_mass_grains=args.insert_mass,
        point_mass_grains=args.point_mass,
        nock_mass_grains=args.nock_mass,
        vane_mass_grains=args.vane_mass,
        measured_total_mass_grains=args.measured_mass,
        static_spine_thou=args.spine,
    )
    result = evaluate_arrow_setup(
        build,
        ShotContext(
            draw_weight_lb=args.draw_weight,
            draw_length_in=args.draw_length,
            ibo_fps=args.ibo,
            measured_speed_fps=args.speed,
        ),
    )
    print(result.summary())
    print(f"grains per pound: {result.grains_per_pound:.2f} gr/lb")
    if result.speed_fps is None:
        print("speed: not available (supply --ibo or --speed)")
    print("\nassumptions:")
    for assumption in result.assumptions:
        print(f"- {assumption}")
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    registry = build_registry()
    store = InMemoryLedger()
    seed = seed_demo_ledger(store, archer_id=DEMO_ARCHER_ID, sessions=args.sessions)

    events = EventLog(Path(args.events) if args.events else None)
    loop = CoachingLoop(
        registry=registry,
        planner=DemoPlanner(DEMO_ARCHER_ID),
        store=store,
        event_log=events,
        auto_summary_keys=("cycle.hold_time_s", "tension.grip_pressure_1_5"),
        auto_summary_window_days=90,
    )
    result = loop.run_turn(
        "Why did my group open up at 18 m, and what should I work on this week?",
        archer_id=DEMO_ARCHER_ID,
        profile_text="compound, 18 m indoor, 3-spot face, 55 lb, right-handed",
    )

    print("=" * 78)
    print("DETERMINISTIC DEMO — no model, no network")
    print("=" * 78)
    print(f"seeded ledger: {seed.accepted} rows accepted, {seed.rejected} rejected")
    print(f"sessions: {seed.sessions}, shots: {seed.shots}")
    print("ground truth planted in the synthetic data:")
    for key, truth in seed.ground_truth.items():
        print(f"  - {key}: {truth}")
    print()
    print(f"turn action : {result.action}")
    print(f"run id      : {result.run_id}")
    print(
        f"budget use  : {result.usage.steps} steps, {result.usage.tool_calls} tool calls, "
        f"{result.usage.tokens} tokens"
    )
    print(f"context     : {result.context_audit}")
    print("tool calls  :")
    for observation in result.observations:
        status = "ok" if observation.result.ok else "FAILED"
        print(f"  - {observation.tool_name} [{status}, {observation.result.confidence.value}]")
    if result.gate is not None:
        print(f"answer gate : {'passed' if result.gate.passed else 'BLOCKED'}")
        for failure in result.gate.failures:
            print(f"  ! {failure}")
    print("-" * 78)
    print(result.answer)
    print("-" * 78)
    print(f"events      : {json.dumps(result.event_counts, sort_keys=True)}")
    if args.events:
        print(f"event log   : {args.events}")
    if args.verbose:
        print("\nfull observation payloads:")
        for observation in result.observations:
            print(f"\n[{observation.tool_name}]")
            print(json.dumps(observation.result.data, indent=2, default=str))
    return 0


def _agent_contract_report(tool_registry: ToolRegistry) -> str:
    """Resolve every subagent's action space, or explain what is inconsistent about it."""
    dispatcher = Dispatcher(runner=NullRunner())
    for name in SPECS:
        dispatcher.tools_for(name)  # raises if a contract names a tool that does not exist

    writers = {"capture", "orchestrator"}
    offenders = sorted(
        name
        for name, spec in SPECS.items()
        if name not in writers
        and any(tool_registry.get(tool).risk is not RiskLevel.READ for tool in spec.allowed_tools)
    )
    if offenders:
        raise ValueError(f"non-writer subagents hold write tools: {offenders}")
    return f"{len(SPECS)} subagents; action spaces resolve; only capture/orchestrator holds a write"


def _setup_report_probe() -> str:
    """Build one setup report and audit it — the M1 promise checked on every `doctor` run."""
    from archery_agent.domain.entities import ArrowSetup, Bow, EquipmentSet
    from archery_agent.domain.equipment import record_version
    from archery_agent.sensors.setup_assessment import audit_setup_report, build_setup_report
    from archery_agent.sim.arrow import ShotContext

    version = record_version(
        archer_id="arc_doctor",
        equipment=EquipmentSet(
            archer_id="arc_doctor",
            bow=Bow(brand="Doctor", model="Probe", draw_weight_lb=55.0, draw_length_in=28.5),
            arrow=ArrowSetup(
                brand="Doctor",
                model="Probe",
                shaft_length_in=28.5,
                shaft_mass_grains=180.0,
                point_mass_grains=100.0,
            ),
        ),
    )
    report = build_setup_report(
        version,
        shot=ShotContext(draw_weight_lb=55.0, draw_length_in=28.5, ibo_fps=310.0),
    )
    audit = audit_setup_report(report)
    if not audit.ok:
        raise AssertionError("; ".join(issue.message for issue in audit.errors))
    estimates = [f for f in report.findings if f.needs_test]
    if not estimates:
        raise AssertionError(
            "the probe report has no estimated finding, so the labelling rule was not exercised"
        )
    return (
        f"{len(report.findings)} labelled finding(s), {len(estimates)} of them naming a test, "
        f"{len(report.experiments)} open experiment(s)"
    )


def _cmd_doctor(_: argparse.Namespace) -> int:
    checks: list[tuple[str, str, str]] = []

    try:
        validate_registry()
        checks.append(
            ("PASS", "parameter registry", f"{len(REGISTRY)} parameters, internally consistent")
        )
    except AssertionError as exc:
        checks.append(("FAIL", "parameter registry", str(exc)))

    try:
        registry = build_registry()
        checks.append(
            (
                "PASS",
                "tool registry",
                f"{len(registry.names())} tools, {len(registry.denied_names())} permanently denied",
            )
        )
    except Exception as exc:
        checks.append(("FAIL", "tool registry", str(exc)))

    try:
        checks.append(("PASS", "agent contracts", _agent_contract_report(registry)))
    except Exception as exc:
        checks.append(("FAIL", "agent contracts", str(exc)))

    try:
        import tempfile

        with (
            tempfile.TemporaryDirectory() as tmp,
            SqliteStore(Path(tmp) / "doctor-probe.db") as probe_store,
        ):
            notes = append_only_probe(probe_store)
        checks.append(("PASS", "append-only storage", "; ".join(notes)))
    except Exception as exc:
        checks.append(("FAIL", "append-only storage", str(exc)))

    try:
        checks.append(("PASS", "setup report contract", _setup_report_probe()))
    except Exception as exc:
        checks.append(("FAIL", "setup report contract", str(exc)))

    from archery_agent.sensors.validators import validate_analysis_window

    window = validate_analysis_window(n_shots=12, purpose="effect")
    checks.append(
        (
            "PASS" if not window.ok else "FAIL",
            "statistical gates",
            "12-shot effect claim is refused, as designed"
            if not window.ok
            else "gate did not fire",
        )
    )

    from archery_agent.sensors.safety import screen_message

    if screen_message("numbness in my fingers").action == "refer":
        checks.append(("PASS", "safety screen", "nerve symptoms route to referral"))
    else:
        checks.append(("FAIL", "safety screen", "a red flag did not route to referral"))

    from archery_agent.domain.targets import ring_for_offset

    centre = ring_for_offset("WA_40CM_10RING", 0.0, 0.0)
    checks.append(
        (
            "PASS" if centre.ring == 10 and centre.is_x else "FAIL",
            "target geometry",
            f"centre of the 40 cm face scores ring {centre.ring}, X={centre.is_x}",
        )
    )

    base = KnowledgeBase()
    if base.size == 0:
        checks.append(
            (
                "WARN",
                "knowledge corpus",
                "empty — factual questions must be answered with an explicit gap "
                "(expected until M4)",
            )
        )
    else:
        checks.append(("PASS", "knowledge corpus", f"{base.size} sourced documents"))

    if UNVERIFIED_CONSTANTS:
        checks.append(
            (
                "WARN",
                "unverified constants",
                "; ".join(f"{k}" for k in UNVERIFIED_CONSTANTS),
            )
        )

    interfaces = SUBAGENT_TOOLS.get("librarian", ())
    checks.append(
        (
            "PASS" if interfaces == ("knowledge.search",) else "WARN",
            "subagent tool restriction",
            f"librarian can call exactly: {', '.join(interfaces)}",
        )
    )

    data_dir = Path("data")
    try:
        data_dir.mkdir(exist_ok=True)
        probe = data_dir / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks.append(("PASS", "data directory", f"{data_dir.resolve()} is writable"))
    except OSError as exc:
        checks.append(("FAIL", "data directory", str(exc)))

    checks.append(("WARN", "model provider", "not configured (expected until M3)"))

    width = max(len(name) for _, name, _ in checks)
    for status, name, detail in checks:
        print(f"[{status}] {name.ljust(width)}  {detail}")
    failures = sum(1 for status, _, _ in checks if status == "FAIL")
    print(f"\n{len(checks) - failures}/{len(checks)} checks passed")
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="archery-agent",
        description="AI Archery Assistant — harness-engineered compound archery training agent",
    )
    parser.add_argument("--version", action="version", version=f"archery-agent {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version", help="print the harness version").set_defaults(func=_cmd_version)

    params = sub.add_parser("params", help="list the parameter registry")
    params.add_argument("--category", choices=[c.value for c in ParameterCategory], default=None)
    params.add_argument("--low-cost", action="store_true", help="only cheap-to-capture parameters")
    params.add_argument("--brief", action="store_true", help="omit per-parameter notes")
    params.add_argument(
        "--core", action="store_true", help="only the mandatory per-session capture set (Q5)"
    )
    params.set_defaults(func=_cmd_params)

    doctor = sub.add_parser("doctor", help="run harness self-checks")
    doctor.set_defaults(func=_cmd_doctor)

    demo = sub.add_parser("demo", help="run one deterministic turn end to end (no model)")
    demo.add_argument("--sessions", type=int, default=12)
    demo.add_argument("--events", default=None, help="write the run event log to this JSONL path")
    demo.add_argument("--verbose", action="store_true")
    demo.set_defaults(func=_cmd_demo)

    equipment = sub.add_parser(
        "equipment",
        help="record and inspect the equipment history; assess the current setup",
    )
    equipment.add_argument(
        "action", choices=["record", "history", "assess"], nargs="?", default="assess"
    )
    equipment.add_argument("--archer", required=True, help="archer id")
    equipment.add_argument("--db", default="data/archery.db", help="SQLite database path")
    equipment.add_argument("--bow-brand", default="unknown")
    equipment.add_argument("--bow-model", default="unknown")
    equipment.add_argument("--arrow-brand", default="unknown")
    equipment.add_argument("--arrow-model", default="unknown")
    equipment.add_argument("--draw-weight", type=float, default=None)
    equipment.add_argument("--draw-length", type=float, default=None)
    equipment.add_argument("--let-off", type=float, default=None)
    equipment.add_argument("--brace-height", type=float, default=None)
    equipment.add_argument("--ata", type=float, default=None)
    equipment.add_argument("--spine", type=float, default=None, help="static spine, thou")
    equipment.add_argument("--length", type=float, default=None, help="shaft length, in")
    equipment.add_argument("--shaft-mass", type=float, default=None, help="shaft mass, gr")
    equipment.add_argument("--point-mass", type=float, default=None)
    equipment.add_argument("--insert-mass", type=float, default=None)
    equipment.add_argument("--nock-mass", type=float, default=None)
    equipment.add_argument(
        "--measured-mass",
        type=float,
        default=None,
        help="weighed finished-arrow mass — turns estimates into measurements",
    )
    equipment.add_argument("--effective-from", default=None, help="ISO date, e.g. 2026-03-01")
    equipment.add_argument("--reason", default="", help="why the setup changed")
    equipment.add_argument("--ibo", type=float, default=None, help="for `assess`: bow IBO rating")
    equipment.add_argument("--speed", type=float, default=None, help="for `assess`: chronograph")
    equipment.set_defaults(func=_cmd_equipment)

    sim = sub.add_parser("simulate", help="arrow setup calculator")
    sim.add_argument("--draw-weight", type=float, required=True)
    sim.add_argument("--draw-length", type=float, required=True)
    sim.add_argument("--ibo", type=float, default=None)
    sim.add_argument("--speed", type=float, default=None, help="chronograph reading, if measured")
    sim.add_argument("--length", type=float, required=True, help="shaft length, inches")
    sim.add_argument("--shaft-mass", type=float, required=True, help="grains")
    sim.add_argument("--insert-mass", type=float, default=0.0)
    sim.add_argument("--point-mass", type=float, default=0.0)
    sim.add_argument("--nock-mass", type=float, default=0.0)
    sim.add_argument("--vane-mass", type=float, default=0.0)
    sim.add_argument("--measured-mass", type=float, default=None, help="weighed total, grains")
    sim.add_argument("--spine", type=float, default=None, help="static spine, thousandths")
    sim.add_argument("--brand", default="")
    sim.add_argument("--model", default="")
    sim.set_defaults(func=_cmd_simulate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
