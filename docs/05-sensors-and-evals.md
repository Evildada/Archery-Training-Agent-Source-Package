# 05 — Sensors & Evals

**Guides steer before acting. Sensors verify after acting.** Most projects over-invest in
markdown and under-invest in sensors; this document is the plan to not be one of them.

Rule of thumb: *computational sensors before inferential ones.* A range check is faster,
cheaper and more reliable than an LLM judge — so it runs first, and a model judge only
covers what determinism cannot reach.

---

## 1. The sensor ladder

| Tier | Runs | Cost | Example | Where |
| --- | --- | --- | --- | --- |
| **T0 — types & schema** | every write | µs | pydantic validation, enum membership | `domain/`, `store/` |
| **T1 — invariants** | every write | µs | plausible range, unit match, context requirements | `sensors/validators.py` |
| **T2 — statistics & thresholds** | every claim | ms | n ≥ 30 gate, q < 0.10, executability of standards, load ramp limits | `sensors/stats.py`, `sensors/standards.py` |
| **T3 — process** | every turn | ms | budget check, tool allow-list, approval before write | `runtime/guards.py` |
| **T4 — model-judged** | every insight | $ | rubric grading: tone, executability, over-claiming | `evals/` (M4) |
| **T5 — human** | weekly | time | coach reviews 20 sampled insights | `docs/06-roadmap.md` M4 |

T0–T3 are non-negotiable and run in CI with **no model and no network**.

## 2. Implemented sensors (v0.1)

| Sensor | Rule | Failure action | Code |
| --- | --- | --- | --- |
| `validate_record` | pydantic + enum + context requirements | reject write, return reasons | `sensors/validators.py` |
| `validate_parameter_value` | value within `plausible_range`; unit matches registry | reject with expected range | `sensors/validators.py` |
| `validate_analysis_window` | ≥ 5 sessions for *any* trend; ≥ 30 shots for *any* effect claim | downgrade to `INSUFFICIENT_EVIDENCE` | `sensors/validators.py` |
| `validate_claim_strength` | claim label must not exceed what n / q support | force downgrade or reject | `sensors/stats.py` |
| `validate_evidence_coverage` | every non-derived claim carries ≥ 1 `EvidenceRef` | reject insight | `sensors/citations.py` |
| `validate_citation` | ref has source, year, and tier; URL/DOI shape valid | reject ref | `sensors/citations.py` |
| `validate_standard_executability` | metric + operator + threshold + window + n_min present | reject standard | `sensors/standards.py` |
| `validate_instruction` | user-facing instruction contains a number, a threshold and a window | reject / rewrite | `sensors/standards.py` |
| `validate_load_progression` | ACWR band + ≤ 10 % weekly ramp | block the plan block, propose a reduced variant | `sensors/load.py` |
| `validate_safety` | medical red-flag vocabulary; scope (compound only) | hard stop → referral / scope message | `sensors/safety.py` |
| `validate_layering` | 4 import-linter contracts | CI failure | `.importlinter` |
| `validate_schema_drift` | generated JSON Schemas match committed files | CI failure | `scripts/export_schemas.py --check` |

## 3. Eval suites (M3+; specs written now so the design is testable)

| Suite | Question it answers | Method | Gate |
| --- | --- | --- | --- |
| `route` | Does the orchestrator pick the right specialist? | 60 labelled inputs incl. refusals | ≥ 0.92 |
| `tool_args` | Are tool arguments well-formed and minimal? | recorded runs replayed | ≥ 0.95 valid-call rate |
| `numeric_grounding` | Is every number traceable to a tool result? | string-match numbers against the run's tool outputs | **1.00 — hard gate** |
| `standard_quality` | Are instructions executable? | `validate_instruction` + rubric | ≥ 0.95 |
| `evidence` | Are factual claims cited and correctly tiered? | `validate_evidence_coverage` + judge | **1.00 for coverage** |
| `overclaim` | Does it assert causation from thin data? | adversarial fixtures with n = 4, n = 12 | 0 violations |
| `safety` | Does it refuse medical/scope cases correctly? | 25 red-team prompts | 0 violations |
| `consistency` | Same question twice → same numbers? | replay with fixed seed + temp 0 | number-identical |
| `coach_alignment` | Does advice match the published cycle template? | rubric vs template phase definitions | ≥ 0.9 |
| `capture_fidelity` | Does narration → rows preserve meaning? | 30 annotated transcripts, field-level F1 | ≥ 0.92 |
| `latency_cost` | p95 latency and tokens per turn | run metrics | p95 < 12 s, < 25k tok/turn |

Failure cases matter more than passing ones: every suite must contain **negative**
fixtures, otherwise it measures nothing.

## 4. The ratchet protocol (how the harness gets better)

When something goes wrong, ask *which rung of the ladder was missing* and fix that rung —
never just the sentence in a prompt:

| Symptom | Fix rung | Concrete action |
| --- | --- | --- |
| "It didn't know the rule" | guide | add the rule to `AGENTS.md` / a doc |
| "It knew the rule and broke it" | sensor | add a T1/T2 check + a test fixture |
| "It lacked data/tools" | capability | add a tool or a knowledge doc |
| "It did something dangerous" | permission | tighten the tool risk level |
| "Its context was polluted" | orchestration | move the work into a subagent |
| "It was right but unreadable" | interface | fix the output schema, not the prompt |

Every fix lands with a regression fixture in `evals/fixtures/` so it can never silently
return.

## 5. CI gates

```
on: pull_request
 ├─ ruff check + format --check          (style sensor)
 ├─ mypy --strict-ish                    (type sensor)
 ├─ lint-imports                         (architecture sensor)
 ├─ scripts/export_schemas.py --check    (drift sensor)
 └─ pytest                              (T0–T2 sensors + domain math)
```

M3+ adds: nightly eval suite run against the pinned prompt version, with a results table
committed to `evals/results/<date>.json` so regressions are visible as a diff.

## 6. Metrics we will actually track (adapted from the 12-metric framework)

Pre-launch (now): record validity rate, schema drift count, architecture violations (must
be 0), domain-math test coverage on `domain/targets.py` and `sim/` (must be ≥ 95 %).

Soft launch: tool-selection accuracy, tool execution success, numeric grounding, citation
coverage, refusal correctness, capture F1.

Production: cost per turn, p95 latency, insights acknowledged vs dismissed (the only honest
proxy for usefulness), sessions logged per active archer per week.
