# 06 — Roadmap

Deterministic spine first, model second. Each milestone has an **exit criterion** that is a
sensor, not an opinion. Do not start a milestone before the previous one's exit criterion is
green in CI.

---

## M0 — Harness skeleton *(this repository, now)*

**Deliverables**
- Layered package with mechanically enforced architecture (`.importlinter`).
- Domain schemas: parameters registry, cycle template, session/end/shot, standard, insight.
- The sensor layer (validators, stats gates, citations, standards, load, safety).
- Deterministic simulator core (arrow mass, FOC, KE, spine check, sight marks).
- CLI (`python -m archery_agent.interfaces.cli doctor|demo`), tests, CI, schema export.
- This documentation set, `AGENTS.md`, and the open-questions log.

**Exit criterion**
`make setup && make check` green on a clean clone; `archery-agent demo` prints a validated
end-to-end deterministic run with **no model provider configured**.

## M1 — Ledger & capture (deterministic, still no LLM)

**Deliverables**
- SQLite repos behind `store/` interfaces; append-only `parameter_ledger`.
- FSM-driven capture CLI: create archer → equipment set → session → ends → shots →
  parameter observations, with every write passing T0–T1 sensors.
- Blank-bale / grouping / scoring modes, target-face geometry for `40CM_3SPOT_V` & `80CM`.
- `report.session_report` equivalent as a deterministic markdown output.
- 200 synthetic sessions with known ground-truth effects (for S5 to be tested against).

**Exit criterion**
A single archer's real 12-session history can be entered and a session report generated;
synthetic-data recovery test shows `stats.effects` finds a planted effect with n ≥ 30 and
does **not** report a null effect as SUPPORTED.

## M2 — Coach & standards layer

**Deliverables**
- Versioned `CycleTemplate` authoring + `cycle.template_publish` with coach/student linking.
- Standard authoring UI/CLI + `standards.suggest` from the archer's own distribution.
- Drill catalog with at least 3 drills per phase fault and per standard.
- `report.coach_card`.

**Exit criterion**
A coach publishes one template; ≥ 2 students practise against it; every generated
instruction passes `validate_instruction` (metric + threshold + window).

## M3 — Orchestrator + first subagents (model goes in)

**Deliverables**
- `runtime/loop.py` with budgets, repairs, guards, event log.
- Model provider interface + one concrete provider behind an env var.
- Subagents: `capture`, `cycle_analyst`, `equip_tech` (librarian and planner at M4).
- Context assembly with deterministic ledger summary + artifact offload + compaction.
- The `route`, `tool_args`, `numeric_grounding`, `consistency` eval suites.

**Exit criterion**
`numeric_grounding = 1.00`, `route ≥ 0.92`, zero budget overruns; a full turn is
reproducible from the event log alone.

## M4 — Research librarian, planner, verifier

**Deliverables**
- Curated `knowledge/` corpus (≥ 40 cited sources: technique, equipment, sport psychology,
  load management) + `knowledge.*` tools with tiering.
- `planner` + `load.*` (ACWR, ramp, monotony) + `gym.template`.
- `verifier` subagent with rubrics; nightly eval run + committed results table.
- human sampling loop: 20 insights/week reviewed by a coach, logged in `evals/human/`.

**Exit criterion**
`evidence = 1.00`, `overclaim = 0 violations`, `safety = 0 violations`; a coach agrees with
≥ 80 % of sampled insights (and every disagreement becomes a fixture).

## M5 — Skill-evolution view & beta with real archers

**Deliverables**
- `report.skill_evolution` — multi-parameter trajectories, change-points at equipment/
  technique events, z-scores against the archer's own baseline, export to coach-friendly PDF.
- Weekly planner derived from real availability + competition calendar.
- Beta: ≥ 3 archers (≥ 1 minor with guardian consent) × ≥ 12 sessions.
- Data-privacy review and a deletion/export path.

**Exit criterion**
C5/C6 from `docs/00-product-brief.md` met: at least one parameter with a SUPPORTED effect
estimate from real data, and the archer can state what changed and when.

---

## Sequencing rationale

- **Why no LLM until M3:** every layer below the loop is testable without a model, and
  debugging a harness and a prompt simultaneously is how projects stall. The deterministic
  spine also gives the eval suites something objective to check numbers against.
- **Why the coach layer precedes the orchestrator:** the standards/cycle vocabulary is the
  agent's *output contract*. Building the agent first would mean inventing the contract
  under time pressure and then retrofitting it.
- **Why the verifier comes late but the gates come early:** T0–T2 sensors are cheap and
  catch most failures; the LLM verifier only earns its cost once the suites show what
  deterministic checks miss.
