# AGENTS.md — Working rules for this repository

This file is a **guide** in the harness-engineering sense: it steers any coding agent
(and any human) *before* they act. Sensors (`scripts/`, `tests/`, `.github/workflows/`)
enforce it *after* they act. If a rule below is violated repeatedly, the fix is not a
better sentence here — it is a new sensor. See `docs/05-sensors-and-evals.md`.

---

## 1. What this repository is

A **harness-engineered training agent for compound archery**. The product is defined in
`docs/00-product-brief.md`. The engineering discipline is defined in
`docs/01-harness-architecture.md`.

Core equation this repo lives by:

```
Agent = Model + Harness
```

The model is swappable and lives behind an interface. The harness — loop, tools, context,
memory, sensors, guardrails, observability — is what this repository actually owns.

## 2. Map of the repository

| Path | Layer | May import from |
| --- | --- | --- |
| `src/archery_agent/domain/` | 0 — pure types, units, parameter registry, target geometry | stdlib, pydantic only |
| `src/archery_agent/sim/` | 1 — deterministic physics/estimators (arrows, spine, sights) | domain |
| `src/archery_agent/sensors/` | 2 — deterministic validators/metrics/gates | domain, sim |
| `src/archery_agent/store/` | 3 — persistence (SQLite/JSONL) | domain, sim, sensors |
| `src/archery_agent/tools/` | 4 — tool registry + tool implementations | domain, sim, sensors, store |
| `src/archery_agent/agents/` | 5 — subagent definitions, prompts, routing | domain, sim, tools, sensors |
| `src/archery_agent/runtime/` | 6 — loop, context assembly, budgets, events | everything above |
| `src/archery_agent/interfaces/` | 7 — CLI / HTTP / chat adapters | everything above |
| `docs/` | design contracts (source of truth for intent) | — |
| `schemas/` | **generated** JSON Schema exports — never hand-edit | — |
| `evals/` | eval suites, fixtures, rubrics | — |
| `knowledge/` | curated, cited archery corpus (RAG source) | — |
| `data/` | gitignored runtime data (SQLite DB, artifacts, raw logs) | — |

Layering is enforced mechanically by `.importlinter` via `make lint-arch`
(or `lint-imports`). Do not "fix" a layering violation by editing `.importlinter`
unless the design doc changes first.

## 3. Hard domain rules

These are non-negotiable, and each one has (or must get) a sensor.

1. **Compound only.** v1 models compound bows and compound equipment. `BowType` rejects
   recurve/barebow/other with an explicit error. Do not add recurve fields "just in case".
2. **Arithmetic is done in Python, never by the model.** Every number a user sees
   (FOC, kinetic energy, group radius, averages, p-values) comes from a deterministic
   function in `src/archery_agent/`. The LLM narrates; it does not calculate.
3. **No unsourced factual claim.** Any statement about archery technique, biomechanics or
   sport psychology that is not derived from the archer's own logged data must carry an
   `EvidenceRef`. `insight.Claim` without evidence refs fails validation.
4. **No medical, injury or rehabilitation advice.** Symptoms -> a fixed referral template.
   Never diagnose, never prescribe loading for a suspected injury.
5. **No overclaiming from small n.** Parameter-effect claims require n >= 30 shots and
   q < 0.10 after multiple-comparison correction, or they are labelled
   `INSUFFICIENT_EVIDENCE`. The sensor lives in `sensors/stats.py`.
6. **Units live in field names.** `draw_weight_lb`, `shaft_mass_grains`,
   `group_radius_cm`, `hold_duration_s`. Never a bare `weight` or `length`. Conversions
   live only in `domain/units.py`.
7. **Minors are the default, not the exception.** Youth archers are a primary user group:
   no free-text PII beyond a display name, no photo retention by default, explicit
   `guardian_consent` flag before any record leaves the device.
8. **Every persisted record is reproducible.** Store model id, prompt version and a data
   snapshot hash with every generated `Insight`.

## 4. Definition of done for any change

Run and pass, in this order:

```bash
make setup       # one-time: venv + editable install + dev deps
make check       # ruff + mypy + lint-imports + pytest + schema drift check
```

`make check` must be green. A change that adds user-visible numbers must add a test.
A change that fixes a bug must add a **sensor** that would have caught it
(the ratchet: every mistake becomes a permanent check).

## 5. Conventions

- Python 3.11+, `from __future__ import annotations` at the top of every module.
- Pydantic v2 models for anything that is persisted or crosses a tool boundary.
  `model_config = ConfigDict(extra="forbid")` on persisted records — silent typos in a
  training log are data corruption.
- Enums for all closed sets (modes, phases, focus areas). If you are tempted to use a
  free string, add it to `domain/parameters.py` instead.
- Time is timezone-aware UTC (`datetime.now(timezone.utc)`); durations in seconds or
  milliseconds, suffixed.
- Ids are ULIDs or `uuid4().hex` strings, prefixed by entity (`sess_`, `shot_`, `arc_`).
- No new runtime dependency without a note in `docs/07-open-questions.md` and a reason
  in the commit message. The dependency budget is small on purpose.
- Never edit `schemas/*.json` by hand — run `make schemas`.

## 6. When the design is unclear

Ask, do not guess. Write the question in `docs/07-open-questions.md` with a
recommended default, and pick the default only if the user agrees. Guessing silently
is the most expensive failure mode in this project: it produces domain data that has to
be migrated later.
