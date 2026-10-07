# 02 — Agent Topology

One orchestrator, five specialists, one verifier. Subagents exist here for **context
isolation and tool restriction**, not for "more intelligence".

```

                        ┌──────────────────────────────┐
   archer / coach ─────▶ │  ORCHESTRATOR (coach loop)   │  owns the turn, the budget,
                        │  routing · context · budgets │  and the final answer
                        └───────┬──────────────────────┘
             ┌──────────┬───────┼──────────┬─────────────┐
             ▼          ▼       ▼          ▼             ▼
        cycle_analyst  equip_tech  planner  librarian  (capture)
         (read-only)   (pure calc) (writes   (cited)    (write-draft)
                                     drafts)
             └──────────┴───────┴──────────┴─────────────┘
                                ▼
                        ┌──────────────────┐
                        │     VERIFIER     │  separate context, sees only the
                        │ rubric + sensors │  candidate answer + evidence refs
                        └──────────────────┘
```

## 1. Orchestrator

**Job:** understand what the archer actually wants, decide which specialists are needed,
assemble the answer, and be accountable for it.

**Allowed tools:** `athlete.read`, `ledger.summary`, `standards.list`, `artifact.write`,
plus the dispatcher for subagents.

**Never:** computes a number, invents a citation, writes to durable records without
approval, exceeds the turn budget.

**Routing table (deterministic first pass, model second):**

| Input class | Route |
| --- | --- |
| "I shot 560 today, here's my end breakdown" | `capture` (write draft) → `cycle_analyst` |
| "Why did my group open up at 30 m?" | `cycle_analyst` (+ `librarian` if technique claim needed) |
| "Should I go to 60 lb?" | `equip_tech` → `sim.arrow_setup` → `verifier` |
| "What do I do this week? I can train Tue/Thu, 90 min" | `planner` (respects load guardrail + standards) |
| "What does research say about target panic?" | `librarian` (citations mandatory) |
| "My shoulder hurts on the draw" | **unsafe → fixed referral template. No analysis.** |

## 2. Specialists

| Subagent | Purpose | Tools allowed | Output contract | Budget |
| --- | --- | --- | --- | --- |
| **cycle_analyst** | Turn the parameter ledger into honest observations about form/cycle | `ledger.read`, `stats.effects`, `stats.trend`, `standards.evaluate_check`, `artifact.write` | `CycleObservation[]` — each with n, effect size, CI, and an explicit evidence label | 8k tokens, 12 tool calls |
| **equip_tech** | Bow/arrow/release reasoning, tuning advice | `equipment.read`, `sim.arrow_setup`, `sim.spine_check`, `sim.sight_marks`, `artifact.write` | `Recommendation[]` — each with assumptions, confidence, and a required range test | 8k tokens, 12 tool calls |
| **planner** | Session/week plan, gym/support work, schedule fitting | `plan.read`, `plan.draft_week`, `load.acwr_check`, `standards.suggest`, `athlete.availability` | `TrainingPlanDraft` — blocks with volume, intensity, focus, standard, and the load check result | 10k tokens, 16 tool calls |
| **librarian** | Cited research insight (archery technique, sport psychology) | `knowledge.search`, `knowledge.fetch`, `artifact.write` | `EvidenceCard[]` — quote + `EvidenceRef` + quality tier; **no claim without a ref** | 8k tokens, 10 tool calls |
| **capture** | Convert messy practice narration into structured records | `session.draft`, `cycle.draft`, `end.draft`, `parameters.normalize` | `SessionDraft` + `parameter` values with `source=SELF_REPORTED`, `reliability` set | 6k tokens, 10 tool calls |
| **verifier** | Adversarial check of the candidate answer against rubrics and sensors | read-only access to the artifact being checked + `sensors.*` | `Verdict{pass|fail, failed_rules[], repair_hint}` | 4k tokens, 0 writes |

## 3. Rules that apply to every subagent

1. **No recursive spawning.** A subagent may not create subagents. Fan-out is the
   orchestrator's decision, capped at 3 concurrent.
2. **Brief, not transcript.** Each subagent receives a structured brief
   (`{task, archer_id, data_refs, constraints, output_schema}`) and returns
   `{summary, structured_result, artifact_refs, warnings}`. Parent transcripts never leak in.
3. **Tool restriction is real.** A subagent's tool list is enforced by the dispatcher,
   not requested in the prompt. `librarian` literally cannot call `session.draft`.
4. **Generation ≠ evaluation.** No subagent verifies its own output. The verifier runs in a
   fresh context with no knowledge of the drafting process, only the artifact and the rubric.
5. **Fail loud, fail small.** A subagent that cannot complete its contract returns
   `{"status":"insufficient", "missing":[...]}` rather than a plausible-sounding guess.
   The orchestrator is required to surface that to the user.

## 4. Why this shape (and not one big prompt)

- A single prompt that "does everything" ends up carrying 40 tools and 8 output formats.
  Tool-selection accuracy falls off with tool count; specialists keep action spaces small
  (a [blueprint-level rule](https://gist.github.com/amazingvince/52158d00fb8b3ba1b8476bc62bb562e3)).
- The cycle/statistics path must be **deterministic and auditable** — a subagent with 4
  read tools and a stats contract is auditable; a generalist is not.
- The verifier only works if it is structurally separate. Same context = same blind spots.
- Adding a sixth specialist later (e.g. `video_form` in v2) is additive: new tool
  namespace, new contract, no change to the loop.
