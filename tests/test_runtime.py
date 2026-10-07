"""The loop, the gates and the context assembly.

These are the tests that matter most: they assert that the harness *refuses* correctly. A system
that can only be tested on its happy path is a system whose failure modes are unknown.
"""

from __future__ import annotations

import pytest

from archery_agent.domain.enums import EvidenceLabel, EvidenceTier
from archery_agent.domain.insight import Claim, EvidenceRef
from archery_agent.interfaces.demo import DEMO_ARCHER_ID, DemoPlanner, seed_demo_ledger
from archery_agent.runtime.budgets import Budget, BudgetExceeded, BudgetGuard
from archery_agent.runtime.context import assemble_context, estimate_tokens
from archery_agent.runtime.events import EventLog, EventType
from archery_agent.runtime.guards import AnswerGate, numeric_grounding_check, preflight
from archery_agent.runtime.loop import (
    CoachingLoop,
    PlannerDecision,
    ScriptedPlanner,
    collect_numbers,
)
from archery_agent.store.memory import InMemoryLedger
from archery_agent.tools.builtin import build_registry
from archery_agent.tools.registry import ToolContext

# ------------------------------------------------------------------- preflight


def test_medical_red_flag_stops_the_turn_before_any_tool_runs() -> None:
    result = preflight("my fingers go numb when I hold at full draw")
    assert result.action == "refer"
    assert "medical professional" in result.response


def test_scope_mismatch_is_handled_before_analysis() -> None:
    result = preflight("how do I set up a recurve clicker?")
    assert result.action == "clarify"
    assert "compound" in result.response


def test_pain_produces_one_question_not_a_lecture() -> None:
    result = preflight("my shoulder hurts on every draw")
    assert result.action == "clarify"
    assert result.follow_up_question


def test_normal_question_proceeds() -> None:
    assert preflight("why did my group open up at 30 m?").action == "proceed"


# ------------------------------------------------------------ numeric grounding


def test_numbers_not_from_a_tool_are_flagged() -> None:
    result = numeric_grounding_check("Your group radius is 4.37 cm.", tool_values={4.37})
    assert result.ok

    bad = numeric_grounding_check("Your group radius is 4.37 cm.", tool_values={6.1})
    assert not bad.ok
    assert "4.37" in bad.errors[0].message


def test_structural_numbers_are_allowed() -> None:
    ok = numeric_grounding_check(
        "Shoot 6 arrows per end at 18 m on the 40 cm face.", tool_values=set()
    )
    assert ok.ok


def test_years_are_not_treated_as_measurements() -> None:
    assert numeric_grounding_check("This held in 2026.", tool_values=set()).ok


def test_answer_gate_blocks_unsupported_claims() -> None:
    gate = AnswerGate()
    claim = Claim(
        statement="Grip pressure is causing the left drift.",
        n=40,
        q_value=0.6,
        effect_size=0.05,
        evidence_label=EvidenceLabel.SUPPORTED,
    )
    result = gate.check(
        answer_text="Grip pressure is causing the drift.", tool_values=set(), claims=(claim,)
    )
    assert not result.passed
    assert result.repair_hint


def test_answer_gate_accepts_a_cited_claim_from_a_peer_reviewed_source() -> None:
    ref = EvidenceRef(
        source_id="smith2021",
        title="Hold time and score",
        author="Smith",
        year=2021,
        venue="Journal of Archery Science",
        doi="10.1234/jas.2021.001",
        tier=EvidenceTier.PEER_REVIEWED,
        quote="Longer holds correlated with higher scores.",
    )
    claim = Claim(
        statement="Published work links longer holds with higher scores.",
        evidence_refs=("smith2021",),
        evidence_label=EvidenceLabel.GENERAL_EDUCATION,
    )
    gate = AnswerGate()
    assert gate.check(
        answer_text="See Smith 2021.", tool_values=set(), claims=(claim,), evidence_refs=(ref,)
    ).passed


# -------------------------------------------------------------------- budgets


def test_budget_guard_reports_the_dimension_it_hit() -> None:
    budget = BudgetGuard(Budget(max_steps=2))
    budget.record_step()
    budget.record_step()
    with pytest.raises(BudgetExceeded) as excinfo:
        budget.enforce()
    assert excinfo.value.dimension == "steps"
    assert "Do not attempt a workaround" in str(excinfo.value)


def test_write_drafts_are_counted_separately() -> None:
    from archery_agent.domain.enums import RiskLevel

    budget = BudgetGuard(Budget(max_write_drafts=1))
    budget.record_tool_call(RiskLevel.WRITE_DRAFT)
    with pytest.raises(BudgetExceeded):
        budget.enforce()


# -------------------------------------------------------------------- context


def test_context_sections_keep_a_stable_order() -> None:
    context = assemble_context(
        system_prompt="sys",
        harness_rules="rules",
        archer_profile="profile",
        ledger_summary="summary",
        standards="standards",
        knowledge="knowledge",
        history=("a", "b"),
        question="question",
    )
    assert [s.name for s in context.sections][:3] == ["system", "harness_rules", "archer_profile"]
    assert context.sections[-1].name == "question"


def test_context_drops_the_least_critical_material_first() -> None:
    context = assemble_context(
        system_prompt="s" * 100,
        ledger_summary="L" * 5000,
        knowledge="K" * 5000,
        question="q",
        char_budget=2000,
    )
    assert "knowledge" in context.dropped_sections
    assert "system" not in context.dropped_sections
    assert "question" not in context.dropped_sections


def test_token_estimate_is_pessimistic() -> None:
    assert estimate_tokens("a" * 35) >= 10


# ----------------------------------------------------------------------- loop


def _ctx(store: InMemoryLedger) -> ToolContext:
    return ToolContext(run_id="run_test", archer_id=DEMO_ARCHER_ID, store=store)


def test_loop_returns_a_referral_without_calling_any_tool() -> None:
    store = InMemoryLedger()
    loop = CoachingLoop(
        registry=build_registry(),
        planner=ScriptedPlanner([]),
        store=store,
        event_log=EventLog(),
    )
    result = loop.run_turn("I've had numbness in my hand for two weeks", archer_id=DEMO_ARCHER_ID)
    assert result.action == "refer"
    assert result.observations == ()
    assert result.event_counts.get("guard_block") == 1
    assert result.event_counts.get("tool_call") is None


def test_full_deterministic_turn_answers_and_passes_its_own_gate() -> None:
    store = InMemoryLedger()
    seed_demo_ledger(store, archer_id=DEMO_ARCHER_ID)
    loop = CoachingLoop(
        registry=build_registry(),
        planner=DemoPlanner(DEMO_ARCHER_ID),
        store=store,
        event_log=EventLog(),
        auto_summary_keys=("cycle.hold_time_s",),
        auto_summary_window_days=90,
    )
    result = loop.run_turn("what should I work on?", archer_id=DEMO_ARCHER_ID)
    assert result.action == "answered"
    assert result.gate is not None and result.gate.passed
    assert len(result.observations) >= 3
    assert result.usage.tool_calls >= 3
    assert result.usage.tokens > 0, "context tokens must be accounted for"
    assert result.event_counts["turn_start"] == 1
    assert result.event_counts["turn_end"] == 1


def test_loop_finds_the_planted_effect_and_not_the_decoy() -> None:
    store = InMemoryLedger()
    seed_demo_ledger(store, archer_id=DEMO_ARCHER_ID)
    loop = CoachingLoop(
        registry=build_registry(),
        planner=DemoPlanner(DEMO_ARCHER_ID),
        store=store,
        event_log=EventLog(),
    )
    result = loop.run_turn("why did my group open up?", archer_id=DEMO_ARCHER_ID)
    assert "cycle.hold_time_s tracks your score" in result.answer
    assert "no detectable association" in result.answer
    assert "grip_pressure_1_5 tracks your score" not in result.answer


def test_number_that_comes_from_nowhere_is_blocked() -> None:
    store = InMemoryLedger()
    seed_demo_ledger(store, archer_id=DEMO_ARCHER_ID, sessions=2)
    planner = ScriptedPlanner(
        [
            PlannerDecision(
                kind="tool_call",
                tool_name="ledger.summary",
                arguments={"archer_id": DEMO_ARCHER_ID, "keys": ["cycle.hold_time_s"]},
            ),
            PlannerDecision(
                kind="answer",
                answer_text="Your hold time is 4.82 s, which is causing the low group.",
            ),
        ]
    )
    loop = CoachingLoop(
        registry=build_registry(), planner=planner, store=store, event_log=EventLog()
    )
    result = loop.run_turn("explain my group", archer_id=DEMO_ARCHER_ID)
    assert result.gate is not None and not result.gate.passed
    assert result.action == "answered"
    assert "could not verify the numbers" in result.answer
    assert result.event_counts.get("answer_gate") == 1


def test_insufficient_decision_degrades_honestly() -> None:
    store = InMemoryLedger()
    loop = CoachingLoop(
        registry=build_registry(),
        planner=ScriptedPlanner([]),
        store=store,
        event_log=EventLog(),
    )
    result = loop.run_turn("how is my form?", archer_id=DEMO_ARCHER_ID)
    assert result.action == "insufficient"
    assert "enough to go on" in result.answer


def test_turn_budget_exhaustion_is_a_designed_outcome() -> None:
    store = InMemoryLedger()
    seed_demo_ledger(store, archer_id=DEMO_ARCHER_ID, sessions=2)
    endless = [
        PlannerDecision(
            kind="tool_call",
            tool_name="ledger.summary",
            arguments={"archer_id": DEMO_ARCHER_ID, "keys": ["cycle.hold_time_s"]},
        )
        for _ in range(50)
    ]
    loop = CoachingLoop(
        registry=build_registry(),
        planner=ScriptedPlanner(endless),
        store=store,
        event_log=EventLog(),
        budget=Budget(max_steps=3),
    )
    result = loop.run_turn("loop forever", archer_id=DEMO_ARCHER_ID)
    assert result.action == "budget_exhausted"
    assert "ran out of working room" in result.answer
    assert result.event_counts.get("budget_hit") == 1


def test_tool_failure_does_not_crash_the_turn() -> None:
    store = InMemoryLedger()
    planner = ScriptedPlanner(
        [
            PlannerDecision(kind="tool_call", tool_name="stats.trend", arguments={"key": "nope"}),
            PlannerDecision(kind="answer", answer_text="I could not retrieve that."),
        ]
    )
    loop = CoachingLoop(
        registry=build_registry(), planner=planner, store=store, event_log=EventLog()
    )
    result = loop.run_turn("trend please", archer_id=DEMO_ARCHER_ID)
    assert result.action == "answered"
    assert not result.observations[0].result.ok


def test_warning_is_emitted_when_context_had_to_drop_sections() -> None:
    store = InMemoryLedger()
    seed_demo_ledger(store, archer_id=DEMO_ARCHER_ID)
    planner = ScriptedPlanner([PlannerDecision(kind="answer", answer_text="Nothing to report.")])
    loop = CoachingLoop(
        registry=build_registry(), planner=planner, store=store, event_log=EventLog()
    )
    result = loop.run_turn(
        "question", archer_id=DEMO_ARCHER_ID, profile_text="p" * 5000, char_budget=1200
    )
    assert any("context budget" in warning for warning in result.warnings)


def test_collect_numbers_walks_nested_tool_output() -> None:
    from archery_agent.runtime.loop import ToolObservation
    from archery_agent.tools.registry import ToolResult

    observation = ToolObservation(
        tool_name="x",
        result=ToolResult.success({"a": [1.5, {"b": "2.25 s"}], "c": True}, n=3),
    )
    numbers = collect_numbers((observation,))
    assert {1.5, 2.25, 3.0} <= numbers


def test_event_log_persists_jsonl(tmp_path: pytest.TempPathFactory) -> None:
    path = tmp_path / "runs" / "2026-10-07.jsonl"  # type: ignore[operator]
    log = EventLog(path)
    log.emit(EventType.TURN_START, archer_id="arc_1")
    log.emit(EventType.TURN_END, action="answered")
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert '"event":"turn_start"' in lines[0].replace(" ", "")


def test_model_boundary_refuses_cleanly_when_unconfigured() -> None:
    from archery_agent.runtime.model_provider import Message, ModelNotConfiguredError, NullProvider

    with pytest.raises(ModelNotConfiguredError, match="deterministic harness"):
        NullProvider().complete([Message(role="user", content="hi")])


def test_scripted_provider_supports_loop_testing_without_a_model() -> None:
    from archery_agent.runtime.model_provider import Message, ModelResponse, ScriptedProvider

    provider = ScriptedProvider([ModelResponse(content="planned", model_id="scripted")])
    response = provider.complete([Message(role="user", content="hi")])
    assert response.content == "planned"
    assert response.model_id == "scripted"
    assert provider.calls
