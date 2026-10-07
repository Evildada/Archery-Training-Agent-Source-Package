"""The agent loop.

One turn, six phases, all of them observable (docs/01 §4):

```
0 GUARD    → 1 CONTEXT → 2 PLAN → 3 ACT → 4 VERIFY → 5 PERSIST
```

The loop is model-agnostic: it drives a :class:`Planner`, which in M0 is
:class:`ScriptedPlanner` (a fixed plan) and at M3 becomes a model-backed planner. That the loop
runs, enforces budgets, emits events and gates the answer *without* a model is the point — it
means every one of those behaviours is testable on its own.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from archery_agent.domain.ids import new_id
from archery_agent.domain.insight import Claim, EvidenceRef
from archery_agent.runtime.budgets import Budget, BudgetExceeded, BudgetGuard, BudgetUsage
from archery_agent.runtime.context import AssembledContext, assemble_context
from archery_agent.runtime.events import EventLog, EventType
from archery_agent.runtime.guards import AnswerGate, GateResult, preflight
from archery_agent.runtime.hooks import HookBus, HookPhase, default_hooks
from archery_agent.runtime.model_provider import Message, ModelProvider, NullProvider
from archery_agent.tools.registry import ToolContext, ToolRegistry, ToolResult

SYSTEM_PROMPT = """You are the training assistant for a compound archery programme.

You work from the archer's own recorded data. You never calculate, never estimate a number and
never state a fact from memory: numbers come from tools, facts come from cited sources.

Your job in one line: turn a training log into an honest, achievable next action.

Non-negotiables:
- compound only in this version; say so plainly and offer the transferable parts instead;
- never assess, diagnose or advise on pain, injury or medication — refer, and keep the log tidy;
- if the data cannot support a claim, say that, name what is missing, and never substitute a
  plausible-sounding guess for a measurement.
"""

HARNESS_RULES_EXTRACT = """Rules the harness enforces mechanically (not style preferences):
- every number you state must come from a tool result;
- effect claims need n >= 30 paired shots and q < 0.10 after correction;
- every factual claim outside the archer's data needs a citation with its tier;
- every instruction needs a dose and a numeric criterion;
- writes to durable records require explicit archer approval."""


class PlannerDecision(BaseModel):
    """One step of a plan. A tool call, a final answer, or an honest refusal to answer."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["tool_call", "answer", "insufficient"]
    tool_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    answer_text: str = ""
    reason: str = ""
    claims: tuple[Claim, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()


class ToolObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    result: ToolResult


class Planner(Protocol):
    def next_action(
        self,
        *,
        user_message: str,
        archer_id: str,
        context: AssembledContext,
        observations: tuple[ToolObservation, ...],
        step: int,
    ) -> PlannerDecision: ...


class ScriptedPlanner:
    """A fixed plan. Replays decisions in order; returns 'insufficient' when exhausted."""

    def __init__(self, decisions: Sequence[PlannerDecision]) -> None:
        self._decisions = list(decisions)

    def next_action(
        self,
        *,
        user_message: str,
        archer_id: str,
        context: AssembledContext,
        observations: tuple[ToolObservation, ...],
        step: int,
    ) -> PlannerDecision:
        del user_message, archer_id, context, observations, step
        if not self._decisions:
            return PlannerDecision(
                kind="insufficient",
                reason=(
                    "the scripted plan has no further steps; a real planner would answer or "
                    "declare what is missing here"
                ),
            )
        return self._decisions.pop(0)


class TurnResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    action: Literal["answered", "clarify", "refer", "insufficient", "budget_exhausted"]
    answer: str = ""
    observations: tuple[ToolObservation, ...] = ()
    gate: GateResult | None = None
    usage: BudgetUsage = Field(default_factory=BudgetUsage)
    warnings: tuple[str, ...] = ()
    event_counts: dict[str, int] = Field(default_factory=dict)
    context_audit: dict[str, int] = Field(default_factory=dict)

    @property
    def tool_numbers(self) -> set[float]:
        return collect_numbers(self.observations)


def collect_numbers(observations: tuple[ToolObservation, ...]) -> set[float]:
    """Every number that appears anywhere in a tool result — the grounding evidence set."""

    def walk(node: object, acc: set[float]) -> None:
        if isinstance(node, bool):
            return
        if isinstance(node, (int, float)):
            acc.add(float(node))
        elif isinstance(node, dict):
            for value in node.values():
                walk(value, acc)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value, acc)
        elif isinstance(node, str):
            import re

            for match in re.finditer(r"(\d+(?:\.\d+)?)", node):
                acc.add(float(match.group(1)))

    numbers: set[float] = set()
    for observation in observations:
        walk(observation.result.data, numbers)
        walk(list(observation.result.assumptions), numbers)
        walk(list(observation.result.warnings), numbers)
        if observation.result.n is not None:
            numbers.add(float(observation.result.n))
    return numbers


class CoachingLoop:
    """Drives one turn: guard, context, plan, act, verify, persist."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        planner: Planner,
        store: Any = None,
        provider: ModelProvider | None = None,
        budget: Budget | None = None,
        event_log: EventLog | None = None,
        hooks: HookBus | None = None,
        gate: AnswerGate | None = None,
        auto_summary_keys: tuple[str, ...] = (),
        auto_summary_window_days: int = 28,
        settings: dict[str, Any] | None = None,
    ) -> None:
        self.registry = registry
        self.planner = planner
        self.store = store
        self.provider = provider or NullProvider()
        self.budget = budget or Budget()
        self.events = event_log or EventLog()
        self.hooks = hooks or default_hooks()
        self.gate = gate or AnswerGate()
        self.auto_summary_keys = auto_summary_keys
        self.auto_summary_window_days = auto_summary_window_days
        self.settings = settings or {}

    # ------------------------------------------------------------------ turn
    def run_turn(
        self,
        user_message: str,
        *,
        archer_id: str,
        profile_text: str = "",
        history: tuple[str, ...] = (),
        approved_tools: frozenset[str] = frozenset(),
        char_budget: int = 60_000,
    ) -> TurnResult:
        run_id = new_id("run")
        self.events.run_id = run_id
        self.events.emit(EventType.TURN_START, archer_id=archer_id, message_chars=len(user_message))

        guard = preflight(user_message)
        if guard.action != "proceed":
            self.events.emit(
                EventType.GUARD_BLOCK,
                action=guard.action,
                matched_terms=list(guard.matched_terms),
                notes=list(guard.notes),
            )
            answer = guard.response
            if guard.follow_up_question:
                answer = f"{answer}\n\n{guard.follow_up_question}"
            self.events.emit(EventType.TURN_END, action=guard.action)
            return TurnResult(
                run_id=run_id,
                action="refer" if guard.action == "refer" else "clarify",
                answer=answer,
                warnings=guard.notes,
                event_counts=self.events.summary(),
            )

        budget = BudgetGuard(self.budget)
        ctx = ToolContext(
            run_id=run_id,
            archer_id=archer_id,
            store=self.store,
            approved_tools=set(approved_tools),
            settings=self.settings,
            data_snapshot_hash=self.store.snapshot_hash() if self.store is not None else "",
        )

        observations: list[ToolObservation] = []
        warnings: list[str] = list(guard.notes)

        # 0b. deterministic ledger summary into context (never raw rows by default)
        ledger_summary = self._auto_summary(ctx, archer_id, observations, budget)

        context = assemble_context(
            system_prompt=SYSTEM_PROMPT,
            harness_rules=HARNESS_RULES_EXTRACT,
            archer_profile=profile_text,
            ledger_summary=ledger_summary,
            history=history,
            question=user_message,
            char_budget=char_budget,
        )
        budget.record_tokens(context.est_tokens)
        self.events.emit(
            EventType.CONTEXT_ASSEMBLED,
            **context.audit(),
            dropped=list(context.dropped_sections),
            est_tokens=context.est_tokens,
        )
        if context.dropped_sections:
            warnings.append(
                "context budget forced these sections out: "
                + ", ".join(context.dropped_sections)
                + " — the answer is necessarily thinner than usual, and should say so"
            )

        decision_kind = "insufficient"
        answer_text = ""
        gate_result: GateResult | None = None

        for step in range(self.budget.max_steps):
            budget.record_step()
            try:
                budget.enforce()
            except BudgetExceeded as exc:
                self.events.emit(EventType.BUDGET_HIT, step=step, dimension=exc.dimension)
                self.events.emit(EventType.TURN_END, action="budget_exhausted")
                return TurnResult(
                    run_id=run_id,
                    action="budget_exhausted",
                    answer=(
                        "I ran out of working room before I could answer properly. Here is what "
                        "was established:\n" + self._render_observations(observations)
                    ),
                    observations=tuple(observations),
                    usage=budget.usage,
                    warnings=(*warnings, str(exc)),
                    event_counts=self.events.summary(),
                    context_audit=context.audit(),
                )

            decision = self.planner.next_action(
                user_message=user_message,
                archer_id=archer_id,
                context=context,
                observations=tuple(observations),
                step=step,
            )
            self.events.emit(EventType.PLAN, step=step, kind=decision.kind, reason=decision.reason)

            if decision.kind == "tool_call":
                if decision.tool_name is None:
                    warnings.append("planner asked for a tool without naming one; step skipped")
                    continue
                observation = self._act(decision, ctx, budget, step)
                observations.append(observation)
                continue

            answer_text = decision.answer_text
            decision_kind = decision.kind
            break

        if decision_kind == "insufficient":
            self.events.emit(EventType.TURN_END, action="insufficient")
            return TurnResult(
                run_id=run_id,
                action="insufficient",
                answer=(
                    "I don't have enough to go on yet. "
                    + (
                        answer_text
                        or "Tell me which session or parameter you mean, or record a session so "
                        "there is something to look at."
                    )
                    + "\n\n"
                    + self._render_observations(observations)
                ).strip(),
                observations=tuple(observations),
                usage=budget.usage,
                warnings=tuple(warnings),
                event_counts=self.events.summary(),
                context_audit=context.audit(),
            )

        gate_result = self.gate.check(
            answer_text=answer_text,
            tool_values=collect_numbers(tuple(observations)),
        )
        self.events.emit(
            EventType.ANSWER_GATE,
            passed=gate_result.passed,
            failures=list(gate_result.failures),
        )
        if not gate_result.passed:
            answer_text = (
                "I could not verify the numbers in the answer I was about to give, so I'm not "
                "giving it:\n- "
                + "\n- ".join(gate_result.failures)
                + "\n\nThe figures I do trust from this turn:\n"
                + self._render_observations(observations)
            )
            warnings.append("answer blocked by the numeric-grounding gate")

        self.events.emit(EventType.TURN_END, action="answered")
        return TurnResult(
            run_id=run_id,
            action="answered",
            answer=answer_text,
            observations=tuple(observations),
            gate=gate_result,
            usage=budget.usage,
            warnings=tuple(warnings),
            event_counts=self.events.summary(),
            context_audit=context.audit(),
        )

    # ------------------------------------------------------------- internals
    def _auto_summary(
        self,
        ctx: ToolContext,
        archer_id: str,
        observations: list[ToolObservation],
        budget: BudgetGuard,
    ) -> str:
        if not self.auto_summary_keys or self.store is None:
            return ""
        result = self.registry.dispatch(
            "ledger.summary",
            {
                "archer_id": archer_id,
                "keys": list(self.auto_summary_keys),
                "window_days": self.auto_summary_window_days,
            },
            ctx,
        )
        budget.record_tool_call(self.registry.get("ledger.summary").risk)
        observations.append(ToolObservation(tool_name="ledger.summary", result=result))
        self.events.emit(
            EventType.TOOL_CALL,
            tool="ledger.summary",
            ok=result.ok,
            confidence=result.confidence.value,
            result_tokens=len(str(result.data)) // 4,
        )
        return result.context_block() if result.ok else ""

    def _act(
        self,
        decision: PlannerDecision,
        ctx: ToolContext,
        budget: BudgetGuard,
        step: int,
    ) -> ToolObservation:
        assert decision.tool_name is not None
        spec = self.registry.get(decision.tool_name)
        pre = self.hooks.run(
            HookPhase.PRE_TOOL,
            {"spec": spec, "arguments": decision.arguments, "step": step},
        )
        for note in pre.notes:
            self.events.emit(EventType.TOOL_CALL, step=step, tool=spec.name, hook_note=note)

        result = self.registry.dispatch(decision.tool_name, decision.arguments, ctx)
        budget.record_tool_call(spec.risk)

        post = self.hooks.run(HookPhase.POST_TOOL, {"spec": spec, "result": result, "step": step})
        if post.notes:
            result = result.model_copy(update={"warnings": (*result.warnings, *post.notes)})

        self.events.emit(
            EventType.TOOL_CALL,
            step=step,
            tool=spec.name,
            ok=result.ok,
            confidence=result.confidence.value,
            risk=spec.risk.value,
            result_tokens=len(str(result.data)) // 4,
            error=result.error[:200],
        )
        return ToolObservation(tool_name=spec.name, result=result)

    @staticmethod
    def _render_observations(observations: Sequence[ToolObservation]) -> str:
        if not observations:
            return "(no data was retrieved)"
        return "\n".join(
            f"- {o.tool_name}: {o.result.context_block(char_budget=300)}" for o in observations
        )


def scripted_messages(decisions: Sequence[PlannerDecision]) -> list[Message]:
    """Helper for provider-backed tests: turn a scripted plan into provider responses."""
    return [
        Message(
            role="assistant",
            content=decision.answer_text or f"call {decision.tool_name}",
        )
        for decision in decisions
    ]
