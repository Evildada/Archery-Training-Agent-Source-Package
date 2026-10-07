"""The write path and the tool dispatcher — where guardrails either hold or do not."""

from __future__ import annotations

from archery_agent.domain.enums import RiskLevel
from archery_agent.domain.ledger import ParameterObservation
from archery_agent.store.base import ObservationFilter
from archery_agent.store.memory import InMemoryLedger
from archery_agent.tools.builtin import SUBAGENT_TOOLS, build_registry, subagent_registry
from archery_agent.tools.registry import ToolContext, ToolRegistry

# ------------------------------------------------------------------- the ledger


def test_append_keeps_valid_rows_and_reports_rejections() -> None:
    store = InMemoryLedger()
    good = ParameterObservation(archer_id="arc_1", key="cycle.hold_time_s", value=3.0)
    typos = ParameterObservation(archer_id="arc_1", key="cycle.hold_time_s", value=250.0)
    batch = store.append((good, typos))
    assert len(batch.accepted) == 1
    assert len(batch.rejected) == 1
    assert "plausible range" in batch.rejected[0]["reason"]
    assert "0.2" in batch.rejected[0]["reason"], "the reason must state the expected range"
    assert store.size == 1


def test_ledger_is_append_only_and_queryable_by_window() -> None:
    store = InMemoryLedger()
    store.append(
        (
            ParameterObservation(
                archer_id="arc_1", key="cycle.hold_time_s", value=2.5, session_id="sess_a"
            ),
            ParameterObservation(
                archer_id="arc_1", key="cycle.hold_time_s", value=3.5, session_id="sess_b"
            ),
        )
    )
    series = store.series("cycle.hold_time_s", archer_id="arc_1")
    assert [row.value for row in series] == [2.5, 3.5]
    filtered = store.query(ObservationFilter(archer_id="arc_1", session_id="sess_b"))
    assert len(filtered) == 1


def test_snapshot_hash_is_stable_and_content_addressed() -> None:
    store = InMemoryLedger()
    empty_hash = store.snapshot_hash()
    store.append((ParameterObservation(archer_id="arc_1", key="cycle.hold_time_s", value=3.0),))
    assert store.snapshot_hash() != empty_hash
    assert store.snapshot_hash().startswith("sha256:")
    assert store.snapshot_hash() == store.snapshot_hash()


# ------------------------------------------------------------------- registry


def test_unknown_tool_error_lists_what_exists(registry: ToolRegistry) -> None:
    with pytest.raises(KeyError) as excinfo:
        registry.get("ledger.telepathy")
    assert "ledger.summary" in str(excinfo.value)


def test_denied_tools_exist_but_are_unreachable(registry: ToolRegistry) -> None:
    assert "raw.sql" in registry.denied_names()
    import pytest

    with pytest.raises(PermissionError, match="permanently denied"):
        registry.get("raw.sql")


def test_write_tools_require_approval(registry: ToolRegistry) -> None:
    ctx = ToolContext(run_id="run_1", archer_id="arc_1", store=InMemoryLedger())
    result = registry.dispatch(
        "ledger.append",
        {
            "archer_id": "arc_1",
            "observations": [{"key": "cycle.hold_time_s", "value": 3.0}],
        },
        ctx,
    )
    assert not result.ok
    assert "requires explicit approval" in result.error


def test_invalid_arguments_return_a_repair_instruction(registry: ToolRegistry) -> None:
    ctx = ToolContext(run_id="run_1", archer_id="arc_1")
    result = registry.dispatch("stats.trend", {"key": "cycle.hold_time_s"}, ctx)
    assert not result.ok
    assert "invalid arguments" in result.error
    assert "archer_id" in result.error


def test_a_tool_that_raises_becomes_a_failed_result_not_a_crash(registry: ToolRegistry) -> None:
    ctx = ToolContext(run_id="run_1", archer_id="arc_1")
    # zero paired observations must not raise out of the dispatcher
    result = registry.dispatch(
        "stats.effects",
        {
            "archer_id": "arc_1",
            "outcome_key": "outcome.score_mean",
            "candidate_keys": ["cycle.hold_time_s"],
        },
        ctx,
    )
    assert not result.ok
    assert result.error


def test_subagent_views_are_restricted_to_their_allow_list() -> None:
    librarian = subagent_registry("librarian")
    assert librarian.names() == ("knowledge.search",)
    with pytest.raises(KeyError):
        librarian.get("ledger.append")


def test_every_subagent_tool_exists_in_the_main_registry() -> None:
    registry = build_registry()
    for subagent, tools in SUBAGENT_TOOLS.items():
        for tool in tools:
            assert tool in registry.names(), f"{subagent} references unknown tool {tool}"


def test_subagents_with_write_access_are_deliberate() -> None:
    """Capture is the only subagent allowed to write, and only as a draft."""
    registry = build_registry()
    writers = {
        subagent
        for subagent, tools in SUBAGENT_TOOLS.items()
        for tool in tools
        if registry.get(tool).risk in {RiskLevel.WRITE, RiskLevel.WRITE_DRAFT, RiskLevel.PUBLISH}
    }
    assert writers == {"capture"}, f"unexpected subagents with write access: {writers}"


def test_knowledge_search_fails_loudly_when_the_corpus_is_empty(registry: ToolRegistry) -> None:
    ctx = ToolContext(run_id="run_1", archer_id="arc_1")
    result = registry.dispatch("knowledge.search", {"query": "target panic routine"}, ctx)
    assert not result.ok
    assert "knowledge base is empty" in result.error
    assert "Do NOT answer factual questions from memory" in result.error


def test_ledger_append_through_the_tool_persists_and_validates() -> None:
    store = InMemoryLedger()
    ctx = ToolContext(run_id="run_1", archer_id="arc_1", store=store)
    registry = build_registry()
    result = registry.dispatch(
        "ledger.append",
        {
            "archer_id": "arc_1",
            "observations": [
                {"key": "cycle.hold_time_s", "value": 3.2, "session_id": "sess_1"},
                {"key": "cycle.hold_time_s", "value": 99.0, "session_id": "sess_1"},
            ],
        },
        ctx,
        approved=True,
    )
    assert result.ok
    assert result.data["accepted"] == 1  # type: ignore[index]
    assert len(result.data["rejected"]) == 1  # type: ignore[index]
    assert store.size == 1


def test_confidence_label_always_present_on_results(registry: ToolRegistry) -> None:
    from archery_agent.domain.enums import Confidence

    ctx = ToolContext(run_id="run_1", archer_id="arc_1")
    result = registry.dispatch(
        "sim.arrow_setup",
        {
            "shaft_length_in": 28.0,
            "shaft_mass_grains": 180.0,
            "draw_weight_lb": 55.0,
            "draw_length_in": 28.5,
        },
        ctx,
    )
    assert result.ok
    assert isinstance(result.confidence, Confidence)
    assert result.assumptions, "a result without assumptions is not usable for a decision"


import pytest  # noqa: E402  (kept at the bottom so the module reads top-down as behaviour)
