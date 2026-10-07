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

from archery_agent import __version__
from archery_agent.agents import SPECS, Dispatcher, NullRunner
from archery_agent.domain.enums import ParameterCategory, RiskLevel
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
from archery_agent.tools.builtin import SUBAGENT_TOOLS, build_registry
from archery_agent.tools.registry import ToolRegistry


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
