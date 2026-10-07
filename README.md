# AI Archery Assistant — source package

A harness-engineered training agent for **compound archery**. The agent's job is not to sound
like a coach; it is to keep an honest, structured record of what an archer actually did, and to
refuse to say more than that record supports.

**Status: M0 complete — the deterministic spine runs with no model, no network and no
credentials.** The model goes in at M3 (`docs/06-roadmap.md`); everything below the model is
already built, tested and enforced.

**Decisions locked (2026-10-08, `docs/07-open-questions.md` — eleven of sixteen answered):** the
v1 user is the *pair* and a coach is usually also an archer (roles, not account types) · the
day-one job is **"is my setup right"**, so M1 is capture + setup assessment · capture is per-end
phone taps · the mandatory parameter set is the recommended ten, with all 74 kept in the registry
· timings are self-estimated at `reliability=low` · load limits warn, never block · one model
interface with cloud default and a real local option (M3) · ring **and** offset, offsets asked for
per mode · v1 faces are 18 m 40 cm 3-spot and 50 m 80 cm under WA compound rules · a neutral fault
taxonomy with the coach owning the template · gym work is accessory-only, no periodisation. The
five remaining questions (Q12-Q16) are M4-M5 scope and keep their documented defaults.

```
$ make setup && make check          # lint · types · architecture · schemas · tests · eval gates
$ archery-agent doctor              # 11/11 checks: the harness auditing itself
$ archery-agent demo                # one full deterministic coaching turn, no model called
$ archery-agent equipment assess --archer arc_1 --ibo 315   # the setup report
$ archery-agent simulate --help     # the arrow/bow calculator
```

## What works today

| Capability | Where | Evidence |
| --- | --- | --- |
| 74-parameter registry, units in the key, capture cost per parameter | `domain/parameters.py` | `doctor`, `tests/test_domain_parameters.py` |
| Target geometry: 40 cm 10-ring, 40 cm vertical 3-spot, 80 cm | `domain/targets.py` | `tests/test_domain_targets.py` |
| Arrow/bow physics: mass, FOC, gr/lb, KE, momentum, spine check, sight marks, tune advice — always with assumptions and a confidence label, never a bare number | `sim/` | `tests/test_sim_assessment.py` |
| Sensors: validators, statistics with effect sizes and BH-corrected q-values, citation rules, standard executability, load (ACWR), safety screen | `sensors/` | `tests/test_sensors_*.py` |
| Append-only ledger, snapshots, knowledge base | `store/` | `tests/test_store_and_tools.py` |
| Tool registry with per-tool risk levels, approval gates, subagent action spaces | `tools/` | same |
| Equipment as dated versions + the setup report (every estimate names its range test) | `domain/equipment.py`, `store/sqlite.py`, `sensors/setup_assessment.py` | `tests/test_equipment_versions.py`, `tests/test_setup_report.py` |
| Subagent contracts, deterministic routing, contract-enforcing dispatcher | `agents/` | `tests/test_agents.py` |
| Coaching loop: budgets, hooks, guards, answer gate, event log | `runtime/` | `tests/test_runtime.py` |
| CLI: `doctor`, `demo`, `params`, `simulate`, `version` | `interfaces/cli.py` | `tests/test_evals_and_cli.py` |
| 5 deterministic eval suites with published gates, wired into `make check` | `evals/` | `scripts/run_evals.py` |
| 51 exported JSON Schemas, drift-checked in CI | `schemas/` | `make check-schemas` |

## The five non-negotiables

These are enforced by code and by CI, not by good intentions:

1. **Compound only.** A recurve/barebow question is refused at the door (`sensors/safety.py`,
   `SCOPE_TEMPLATE`), because every geometry table in here is compound.
2. **Arithmetic happens in Python.** The model never does maths; it calls a tool. Tool outputs
   carry `Confidence` and `assumptions`, and `numeric_grounding` (a hard eval gate) rejects any
   answer containing a number that no tool produced.
3. **No claim without evidence.** Effect claims need n ≥ 30 and a corrected q < 0.10
   (`sensors/stats.py`); knowledge claims need an `EvidenceRef` with a checkable locator. The
   label `SUPPORTED` / `PRELIMINARY` / `INSUFFICIENT_EVIDENCE` travels with every number.
4. **Pain is not a coaching problem.** A medical red flag short-circuits the turn into a referral
   template — no analysis, no tool calls. The safety eval gate is 1.00, not 0.99.
5. **Every fix comes with a sensor.** A bug that reached a user becomes a fixture, the fix lands
   one layer down (sensor or registry, not the prompt), and the fixture stays forever. See the
   ratchet rule in `evals/README.md`.

## Harness engineering, concretely

An agent is *model + harness*, and the harness is where the engineering is. In this repository:

* **Layers are mechanically enforced** (`make lint-arch`): `domain < sim < sensors < store < tools
  < agents < runtime < interfaces`. The domain layer cannot import `sqlite3`; nothing outside
  `runtime` may import a model SDK; sensors can never develop a side effect by accident.
* **Sensors run before the model does.** Red flags, scope, action spaces and statistical gates are
  decided deterministically. The model may refine a decision; it cannot overrule one.
* **Tool restrictions are real.** A subagent receives a registry containing only its allow-list
  (`agents/dispatcher.py`), so "the librarian cannot write to the ledger" is a fact, not a prompt.
* **Subagents get briefs, not transcripts.** Structured brief in, structured result out, with a
  budget; a specialist that overspends is refused rather than trimmed.
* **Everything the model produced is re-checked.** The answer gate inspects the final text for
  unsupported numbers and overclaims before it reaches the archer.

## Layout

```
src/archery_agent/
  domain/      pure types: parameters, sessions, standards, ledger rows, targets, units
  sim/         deterministic physics: arrow, spine, sights, tuning
  sensors/     validators, statistics gates, citations, standards, load, safety
  store/       append-only ledger, knowledge base
  tools/       registry + implementations; the only write path into the system
  agents/      subagent contracts, routing, dispatcher
  runtime/     the loop: budgets, hooks, guards, context assembly, event log
  interfaces/  CLI and the deterministic demo
docs/          00 product brief … 07 open questions
evals/         fixtures + gates (the ratchet)
knowledge/     citation corpus (empty by design until M4 — see knowledge/README.md)
schemas/       generated, drift-checked
```

## Read next

* `docs/00-product-brief.md` — the problem, the users, the five systems.
* `docs/01-harness-architecture.md` — why the layers are ordered this way.
* `docs/02-agent-topology.md` — orchestrator, five specialists, one verifier.
* `docs/05-sensors-and-evals.md` — what "done" is allowed to mean.
* `docs/07-open-questions.md` — **17 questions with provisional defaults; four of them block M1.**

`AGENTS.md` is the contract for any agent (human-directed or otherwise) working in this
repository: read it before changing anything.
