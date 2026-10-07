# Eval Suites

An eval that only contains cases the system passes measures nothing. Every suite here has
**negative fixtures**, and every negative fixture exists because that failure was real or is
clearly reachable.

## Status

| Suite | Fixture | Status | Gate |
| --- | --- | --- | --- |
| `routing` | `fixtures/red_team.jsonl` (exact action) | **live (deterministic)** | ≥ 0.90 |
| `safety` | `fixtures/red_team.jsonl` (red flags never missed, core cases never refused) | **live (deterministic)** | **1.00 (hard)** |
| `numeric_grounding` | `fixtures/numeric_grounding.jsonl` | **live (deterministic)** | **1.00 (hard)** |
| `claim_labels` | `fixtures/claim_labels.jsonl` | **live (deterministic)** | **1.00 (hard)** |
| `standards_executability` | `fixtures/standards.jsonl` | **live (deterministic)** | ≥ 0.95 |
| `tool_args` | — | M3 (needs recorded runs) | ≥ 0.95 |
| `overclaim` | — | M3 (needs generation) | 0 violations |
| `consistency` | — | M3 (needs generation) | number-identical |
| `coach_alignment` | — | M4 (needs a published template + judge) | ≥ 0.90 |
| `capture_fidelity` | — | M4 (needs annotated transcripts) | F1 ≥ 0.92 |

The live suites are deterministic and run in CI with no model and no network
(`scripts/run_evals.py`, wired into `make check`). Once a model is attached at M3, the same
fixtures gate the generated output — a fixture that passes deterministically is the *floor*, not
the goal.

Two routing gates exist and they are not the same measurement: the `routing` suite above scores
the deterministic preflight (`agents/routing.py`), which decides red flags, scope and intent
*before* the model is called. The M3 `route` suite in `docs/06-roadmap.md` (≥ 0.92) scores the
model's choice of specialist once it is allowed to refine that first pass. The deterministic gate
is the hard one; the model gate is allowed to be a little softer because the first pass already
catches the failures that matter.

## Why these five first

They correspond to the failure modes that would do real damage in this specific product:

* **routing** — a form question answered with equipment advice, or the reverse;
* **safety** — anything that talks an archer out of seeing a professional;
* **numeric_grounding** — a confident, plausible, invented number, which is the single most
  damaging thing a coaching agent can produce;
* **claim_labels** — a correlation from 12 arrows presented as a discovery;
* **standards_executability** — advice the archer cannot score at the end of the session, which
  is how the original brief's *"executable measures"* requirement quietly fails.

## Adding a fixture (the ratchet)

Every time the system gets something wrong in real use:

1. add the failing case to the relevant fixture file;
2. run `python scripts/run_evals.py` and watch it fail;
3. fix the cause one layer down (sensor or registry — not the prompt);
4. keep the fixture forever.

Rule of thumb: if a suite's fixtures are all ones the system was designed to pass, that suite has
already stopped being useful.
