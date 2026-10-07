# 01 — Harness Architecture

The engineering discipline of this repository: **build the harness, not the prompt.**

```
Agent = Model + Harness
```

The model is a swappable dependency behind `runtime/model_provider.py`. Everything else —
loop, tools, context assembly, memory, sensors, guardrails, observability — is the
harness, and the harness is what this repo owns and tests.

---

## 1. The four constitutive parts

Per the current literature on agent harnesses, four things are *necessary*; anything else
is a qualifier. All four are present here from milestone M0.

| Constitutive part | Where it lives | This project's version of it |
| --- | --- | --- |
| **Agent loop** (reason → act → observe) | `runtime/loop.py` | The *coaching loop*: interpret the archer's question → retrieve their ledger → call deterministic tools → verify the answer against standards/guardrails → persist an `Insight` |
| **Tool interface** | `tools/` | Namespaced tools over the ledger, the simulator and the knowledge base |
| **Context management** | `runtime/context.py` | Layered, cache-stable prompt assembly + artifact offload + compaction, with the ledger *summarised deterministically* (never dumped raw) |
| **Control mechanisms** | `sensors/`, `runtime/guards.py` | Deterministic validators, statistical claim gates, budgets, write approvals, no-medical-advice policy |

## 2. The ten harness components, mapped to real files

| # | Component | Role | In this repo |
| --- | --- | --- | --- |
| 1 | **Context pipelines** | what the model reasons over | `runtime/context.py`, `AGENTS.md`, `docs/`, `knowledge/` |
| 2 | **Guides** (feedforward) | constrain before acting | `AGENTS.md`, `domain/parameters.py` registry, tool schemas |
| 3 | **Sensors** (feedback) | verify after acting | `sensors/`, `tests/`, `evals/`, `.github/workflows/ci.yml` |
| 4 | **Tool interfaces** | controlled access to the world | `tools/registry.py` + `tools/impl/` |
| 5 | **Memory** | durable state across sessions | `store/` (SQLite) + **Parameter Ledger** (the domain memory) |
| 6 | **Sandbox** | safe execution | local-only v1; simulation tools are pure functions; writes require approval |
| 7 | **Orchestration** | multi-agent coordination | `agents/` — orchestrator + restricted subagents (`docs/02-agent-topology.md`) |
| 8 | **Hooks / lifecycle** | interception points | `runtime/hooks.py` — pre-tool, post-tool, pre-persist |
| 9 | **Permissions** | what the agent may do | tool `risk` level + `requires_approval` + budget guards |
| 10 | **Observability** | debugging and trust | append-only event log (`data/runs/*.jsonl`), trace ids, token/cost accounting |

## 3. Layered architecture (mechanically enforced)

```
interfaces/   CLI · HTTP · (later) chat adapters          ← thinnest possible
    ▲
runtime/      loop · context · guards · budgets · events   ← the only place a model is called
    ▲
agents/       orchestrator + subagent definitions          ← prompts, routing, tool allow-lists
    ▲
tools/        registry + implementations                   ← every side effect lives here
    ▲
store/        repositories (SQLite, JSONL artifacts)       ← the only place that touches disk
    ▲
sensors/      validators, statistics, load guards          ← pure functions, no IO, no LLM
    ▲
sim/          deterministic physics: arrows, spine, sights ← pure functions, fully unit-tested
    ▲
domain/       schemas, units, parameter registry           ← pure types, pydantic only
```

The split between `sim/` and `sensors/` is deliberate: `sim/` answers *"what do the physics
say?"* (arrow mass, FOC, kinetic energy, spine coherence, sight marks) and `sensors/` answers
*"is this value, claim or plan defensible?"* (plausible ranges, minimum-n gates, executability
of standards, load progression). One computes, the other judges. Conflating them is how
scientific guards quietly turn into scoring heuristics.

Enforced by `.importlinter` (`make lint-arch`). Four contracts:

1. **layers** — no upward imports, ever.
2. **domain purity** — `domain/` may not import `sqlite3`, HTTP clients, or any model SDK.
3. **sensors purity** — sensors are deterministic and side-effect free, so they can be run
   inside the loop cheaply *and* in CI without a model.
4. **llm isolation** — only `runtime/` may import a model provider, so the rest of the
   system is testable with the provider absent.

**Why this matters concretely:** the model must never be the component that computes a
score, a p-value or a kinetic energy. If arithmetic lived in the prompt, the same question
could give two answers on two days, and the whole "stable position" claim collapses.
Layering makes the honest design the *easy* design.

## 4. The loop (specification)

```
turn(user_message, archer_id)
 ├─ 0. GUARD      classify: capture | question | planning | equipment | research | unsafe
 │                 (deterministic pre-checks: medical red flags, out-of-scope discipline)
 ├─ 1. CONTEXT    assemble (see §5): profile snapshot + ledger summary + active standards
 │                 + last N sessions + knowledge hits — never the whole database
 ├─ 2. PLAN       the model proposes tool calls, not answers
 ├─ 3. ACT        tool calls execute; every result is validated by a sensor before it
 │                 re-enters context; results > offload_threshold become artifacts + preview
 ├─ 4. VERIFY     deterministic gate on the candidate answer:
 │                   units consistent · numbers traceable to a tool result ·
 │                   standards are executable · claims carry evidence · no medical advice
 ├─ 5. REPAIR     if the gate fails: one bounded retry with the failure reasons injected
 │                 (max 2 repairs, then the harness degrades honestly: "I need X to answer")
 └─ 6. PERSIST    event log (always) · Insight (if generated) · proposed ledger writes
                   (require archer/coach approval before commit)
```

Budgets are guards, not defaults: `max_steps_per_turn=40`, `max_tool_calls=60`,
`max_tokens_per_run=150k`, `max_repairs=2`. Hitting a budget is a *designed* outcome that
produces a partial, honestly-labelled answer — never a silent truncation.

## 5. Context assembly (cache-stable, budgeted)

Order matters for both cache hits and attention. The assembly order is fixed:

```
1. static system prompt + tool stubs            (changes only with a version bump)
2. AGENTS.md rules extract + domain invariants  (stable)
3. archer profile snapshot                      (changes rarely)
4. deterministic ledger summary                 (computed by tools, not by the model)
5. active standards + current plan block        (changes per session)
6. knowledge hits (cited snippets, ≤ 5)         (per question)
7. recent turn history (compacted)              (volatile)
8. the user's actual question                   (volatile)
```

Rules:
- **Deterministic summary over raw dump.** The ledger is summarised by `tools/impl/ledger.py`
  (means, trends, n) so the model cannot misread an aggregate. Raw rows only enter context
  when the question is explicitly about specific shots, and then as an artifact reference.
- **Artifact offload.** Any tool result > 8 000 tokens is written to
  `data/artifacts/<run_id>/<tool>.json` and replaced by a path + ≤ 40-line preview.
- **Compaction at 80 %** of the model window into a structured summary (decisions, numbers,
  open questions) — never truncation.
- **Fresh context per subagent.** Subagents receive a *brief*, not the parent transcript.

## 6. Memory model (three tiers, deliberately separate)

| Tier | Content | Store | Lifetime |
| --- | --- | --- | --- |
| **Parameter Ledger** | every captured parameter value, tidy long format | SQLite table `parameter_ledger` | forever — this is the asset |
| **Athlete Profile** | slow-changing identity + setup | SQLite tables `archer`, `equipment_*`, `standards` | months–years |
| **Session Memory** | per-session working state (what was asked, what was concluded) | `data/runs/<run_id>.jsonl` + `insight` table | append-only |

The model's context window is **not** memory. If a fact is not in one of these three
tiers, it does not exist for the next session.

## 7. Guardrails and permissions

| Level | Meaning | Examples |
| --- | --- | --- |
| `READ` | no side effects | read ledger, compute stats, simulate arrow setup |
| `WRITE_DRAFT` | proposes a record, requires approval to commit | add session, add end, add standard |
| `WRITE` | commits immediately (only for run-scoped artifacts) | event log, artifact files |
| `PUBLISH` | coach-only, reviewed | teaching card / cycle template published to students |
| `DENY` | never available to the model | raw SQL, network egress, file deletion, medical advice, editing `AGENTS.md` |

Every denial has a fixed, user-facing fallback message. A refusal that does not explain
*why* and *what would work instead* is a harness defect.

## 8. Observability contract

Every run appends to `data/runs/<date>.jsonl`:

```json
{"ts":"...","run_id":"...","event":"tool_call","tool":"sim.arrow_setup","args_hash":"...",
 "result_tokens":812,"artifact":"data/artifacts/...","ms":14,"approved_by":null}
```

Minimum event set: `turn_start`, `context_assembled` (token counts per section),
`tool_call`, `guard_block`, `repair`, `budget_hit`, `insight_persisted`, `turn_end`.
These events are what make the harness debuggable *and* what make eval suites possible
later (`docs/05-sensors-and-evals.md`).

## 9. What we are explicitly not doing yet

- No vector database: the curated corpus in `knowledge/` is small enough for lexical +
  metadata retrieval, and citations matter more than semantic recall. Revisit at > 500 docs.
- No fine-tuning: harness quality dominates model quality at this size.
- No autonomous background loop: v1 is archer-initiated. Background agents without a
  verifier and a budget are how you get a training log nobody trusts.
