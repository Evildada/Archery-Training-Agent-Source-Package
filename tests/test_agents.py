"""The agent layer is the part most likely to rot silently: a subagent keeps its name and
loses its constraints. These tests pin the constraints.

Every test here corresponds to a rule in docs/02-agent-topology.md. If a rule is not enforced
here, it is a paragraph, not a property.
"""

from __future__ import annotations

from typing import Any

import pytest

from archery_agent.agents import (
    SPECS,
    AgentResult,
    AgentStatus,
    Brief,
    BudgetExceededError,
    Dispatcher,
    UnknownSubagentError,
    route_message,
    spec_for,
)
from archery_agent.agents.specs import READ_ONLY_SUBAGENTS
from archery_agent.domain.enums import RiskLevel
from archery_agent.tools.builtin import build_registry
from archery_agent.tools.registry import ToolContext


def _ctx() -> ToolContext:
    return ToolContext(run_id="run_test", archer_id="arc_test")


class _Runner:
    """A runner that returns whatever the test tells it to."""

    def __init__(self, result: AgentResult | None = None) -> None:
        self.result = result
        self.seen_spec = None
        self.seen_tools: tuple[str, ...] = ()

    def run(self, spec: Any, brief: Brief, tools: Any, ctx: ToolContext) -> AgentResult:
        self.seen_spec = spec
        self.seen_tools = tools.names()
        if self.result is not None:
            return self.result
        return AgentResult(
            status=AgentStatus.OK,
            summary=f"{spec.name} did {brief.task}",
            structured={"answers": 42},
        )


# ------------------------------------------------------------------ the contracts


def test_every_subagent_has_a_resolvable_action_space() -> None:
    full = set(build_registry().names())
    for name, spec in SPECS.items():
        assert set(spec.allowed_tools) <= full, f"{name} references unknown tools"


def test_no_subagent_can_spawn_another_subagent() -> None:
    """No recursive spawning: there must be no dispatch tool to call in the first place."""
    for name, spec in SPECS.items():
        offenders = [tool for tool in spec.allowed_tools if tool.startswith(("agent.", "spawn."))]
        assert not offenders, f"{name} could spawn a subagent via {offenders}"


@pytest.mark.parametrize("name", sorted(READ_ONLY_SUBAGENTS))
def test_read_only_specialists_hold_only_read_tools(name: str) -> None:
    registry = build_registry()
    spec = spec_for(name)
    offenders = [
        tool for tool in spec.allowed_tools if registry.get(tool).risk is not RiskLevel.READ
    ]
    assert not offenders, f"{name} must be read-only but holds {offenders}"


def test_the_verifier_holds_no_write_tools() -> None:
    registry = build_registry()
    verifier = spec_for("verifier")
    assert verifier.tool_budget <= 4, "the verifier is a check, not a second author"
    assert all(registry.get(tool).risk is RiskLevel.READ for tool in verifier.allowed_tools)


def test_only_capture_and_orchestrator_may_write() -> None:
    """A write tool anywhere else means the action-space story is already inconsistent."""
    registry = build_registry()
    writers = {
        name
        for name, spec in SPECS.items()
        if any(
            registry.get(tool).risk in (RiskLevel.WRITE_DRAFT, RiskLevel.PUBLISH)
            for tool in spec.allowed_tools
        )
    }
    assert writers <= {"capture", "orchestrator"}, f"unexpected writers: {sorted(writers)}"


def test_budgets_are_within_the_documented_ceilings() -> None:
    for name, spec in SPECS.items():
        assert spec.tool_budget <= 24, f"{name} has an unbounded tool budget"
        assert spec.token_budget <= 24_000, f"{name} has an unbounded token budget"
    assert spec_for("verifier").token_budget < spec_for("orchestrator").token_budget


def test_denied_tools_makes_the_boundary_visible() -> None:
    denied = Dispatcher(_Runner()).denied_tools("librarian")
    assert "ledger.append" in denied
    assert "raw.sql" not in denied, "a permanently denied tool is not a capability at all"


# ------------------------------------------------------------------- the dispatcher


def test_dispatcher_hands_the_runner_only_the_allow_list() -> None:
    runner = _Runner()
    dispatcher = Dispatcher(runner)
    brief = Brief(task="summarise my last block", output_schema="CycleObservation[]")
    result = dispatcher.dispatch("cycle_analyst", brief, _ctx())
    assert result.usable
    assert set(runner.seen_tools) == set(spec_for("cycle_analyst").allowed_tools)
    assert "ledger.append" not in runner.seen_tools


def test_dispatcher_rejects_a_brief_for_the_wrong_output_shape() -> None:
    brief = Brief(task="summarise", output_schema="WhateverIFeel")
    with pytest.raises(ValueError, match="contract"):
        Dispatcher(_Runner()).dispatch("cycle_analyst", brief, _ctx())


def test_dispatcher_refuses_an_overbudget_result() -> None:
    over = AgentResult(
        status=AgentStatus.OK,
        summary="did ten times the allowed work",
        structured={},
        tool_calls=99,
    )
    with pytest.raises(BudgetExceededError, match="exceeded its contract"):
        Dispatcher(_Runner(over)).dispatch(
            "librarian", Brief(task="find sources", output_schema="EvidenceCard[]"), _ctx()
        )


def test_dispatcher_refuses_artifacts_from_a_read_only_specialist() -> None:
    sneaky = AgentResult(
        status=AgentStatus.OK,
        summary="wrote a file it should not have",
        structured={},
        artifact_refs=("artifact://run/1",),
    )
    with pytest.raises(BudgetExceededError, match="read-only"):
        Dispatcher(_Runner(sneaky)).dispatch(
            "librarian", Brief(task="find sources", output_schema="EvidenceCard[]"), _ctx()
        )


def test_unknown_subagent_is_a_loud_failure() -> None:
    with pytest.raises(UnknownSubagentError):
        spec_for("nutritionist")


def test_an_insufficient_result_must_name_what_is_missing() -> None:
    with pytest.raises(ValueError, match="must name what is missing"):
        AgentResult(status=AgentStatus.INSUFFICIENT, summary="could not do it")


def test_an_ok_result_must_carry_structured_output() -> None:
    with pytest.raises(ValueError, match="structured output"):
        AgentResult(status=AgentStatus.OK, summary="all good, trust me")


# --------------------------------------------------------------------- routing


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("I shot 560 today, here's my end breakdown", "capture"),
        ("why did my group open up at 30 m?", "cycle_analyst"),
        ("should I move to 60 lb draw weight?", "equip_tech"),
        ("what do I do this week? I can train Tuesday and Thursday for 90 minutes", "planner"),
        ("what does the research say about target panic?", "librarian"),
    ],
)
def test_routing_matches_the_topology_table(message: str, expected: str) -> None:
    assert expected in route_message(message).routes


def test_a_red_flag_never_reaches_a_specialist() -> None:
    decision = route_message("numbness in my fingers on every shot")
    assert decision.blocked
    assert decision.routes == ()
    assert decision.safety_response


def test_a_pain_report_is_clarified_before_any_analysis() -> None:
    """Reporting pain is not automatically a red flag, but it is never quietly analysed either."""
    decision = route_message("I shot 560 today but my shoulder hurts")
    assert decision.needs_clarification
    assert decision.safety_response
    assert decision.routes == (), "no specialist runs until the pain question is answered"


def test_out_of_scope_stops_at_the_door() -> None:
    decision = route_message("what draw weight for my recurve riser?")
    assert decision.blocked
    assert decision.out_of_scope_response
    assert decision.routes == ()


def test_an_intent_free_message_asks_rather_than_guesses() -> None:
    decision = route_message("hello")
    assert decision.routes == ()
    assert decision.needs_clarification


def test_capture_route_requires_approval_before_writing() -> None:
    decision = route_message("I shot 3 ends of 6 today, all in the 9 and 10")
    assert decision.requires_approval, "writing to the ledger is never silent"


# ------------------------------------- Q10: constraints travel with the contract, not the brief


def test_contract_constraints_are_merged_into_every_brief() -> None:
    captured: list[Brief] = []

    class _Capture:
        def run(self, spec: Any, brief: Brief, tools: Any, ctx: ToolContext) -> AgentResult:
            captured.append(brief)
            return AgentResult(status=AgentStatus.OK, summary="ok", structured={})

    brief = Brief(
        task="plan next week",
        output_schema="TrainingPlanDraft",
        constraints=("only Tuesday and Thursday",),
    )
    Dispatcher(_Capture()).dispatch("planner", brief, _ctx())

    effective = captured[0].constraints
    assert "only Tuesday and Thursday" in effective, "the caller's constraint survives"
    assert any("accessory work only" in c for c in effective), "the contract's own rule survives"
    assert any("never prescribe through pain" in c for c in effective)
    assert brief.constraints == ("only Tuesday and Thursday",), "the caller's brief is unchanged"


def test_every_specialist_carries_at_least_one_constraint() -> None:
    """A subagent with no constraint is a specialist with no boundary."""
    for name, spec in SPECS.items():
        assert spec.constraints, f"{name} has no constraints attached to its contract"
