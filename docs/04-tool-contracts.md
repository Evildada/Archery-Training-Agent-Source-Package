# 04 — Tool Contracts

Tools are the model's only way to perceive or change the world. Rules:

- **Namespaced, narrow, typed.** `sim.arrow_setup`, not `calculate().`
- **Deterministic tools before inferential ones.** If a linter can do it, a model may not.
- **Every result is sensor-checked** before it re-enters context.
- **Risk is declared, not requested.** The dispatcher enforces the level.

Risk levels: `READ` · `WRITE_DRAFT` (needs approval to commit) · `WRITE` (run-scoped
artifacts only) · `DENY` (never offered to the model).

---

## 1. `athlete.*`

| Tool | Risk | Input | Output |
| --- | --- | --- | --- |
| `athlete.read_profile` | READ | `{}` | `ShooterProfile` + current `equipment_set_id` + active `cycle_template_id` |
| `athlete.update_profile` | WRITE_DRAFT | partial profile | `ChangeProposal` (diff + effective date) — **profile changes are events, not overwrites** |
| `athlete.availability` | READ | `date_range` | `Availability{weekday → minutes}` |

## 2. Capture

| Tool | Risk | Input | Output |
| --- | --- | --- | --- |
| `session.draft` | WRITE_DRAFT | mode, distance, face, planned arrows, notes | `SessionDraft` |
| `session.commit` | WRITE | `SessionDraft` + approval token | `Session` |
| `end.draft` / `end.commit` | WRITE_DRAFT / WRITE | end index, arrows, positions | `End` |
| `shot.batch_append` | WRITE_DRAFT | `Shot[]` | validation report (rejected rows returned with reasons) |
| `cycle.draft` | WRITE_DRAFT | phase timings/ratings in archer's own words → normalised | `CycleObservation[]` |
| `parameters.normalize` | READ | free text ("held about 3 seconds") | `ParameterCandidate[]` with confidence — **never commits** |
| `capture.eod_summary` | READ | session id | "what did we record / what is missing" checklist |

The capture path exists because data entry is the real failure mode of every training log:
the agent must be able to turn "did 6 ends of 6 at 18m, felt like I was rushing the draw,
maybe 2.5 s holds" into rows, show the diff, and ask before committing.

## 3. Ledger & statistics

| Tool | Risk | Input | Output |
| --- | --- | --- | --- |
| `ledger.append` | WRITE_DRAFT | `ParameterObservation[]` | accepted / rejected with sensor reasons |
| `ledger.read` | READ | archer, param_keys, window, filters | tidy rows (paginated, ≥ 200 rows offloads to artifact) |
| `ledger.summary` | READ | param_keys, window, group_by | mean / sd / n / trend slope — **the default context input** |
| `stats.trend` | READ | param_key, window | slope + CI + change-points + n, with a minimum-n gate |
| `stats.effects` | READ | outcome_key, candidate params, window | ranked effect estimates with effect size, q-value, n |
| `stats.correlation` | READ | two param keys | r, p, q, n, plus a caveat block (correlation ≠ cause) |
| `stats.distribution` | READ | param_key, window | histogram + percentiles (used for "is this normal for me?") |
| `stats.anomaly` | READ | session id | sessions whose parameters deviate > k·MAD from the archer's own baseline |
| `stats.regression_gate` | READ | param_key | `{n, q, verdict: SUPPORTED\|PRELIMINARY\|INSUFFICIENT_EVIDENCE}` |

**Gate rule (hard):** `stats.effects` refuses to rank a parameter with n < 30 and returns
`INSUFFICIENT_EVIDENCE` rather than a weak correlation. This is the single most important
guardrail in the product — it is what stops the agent from confidently inventing causal
stories out of six arrows.

## 4. Standards & technique

| Tool | Risk | Input | Output |
| --- | --- | --- | --- |
| `standards.list` | READ | mode, difficulty | active standards |
| `standards.suggest` | READ | focus_tag, recent performance | `Standard[]` that are achievable *now* (derived from the archer's own distribution: "≤ your 40th percentile + a step") |
| `standards.validate_draft` | READ | draft standard | validated standard (executability sensor) or an executable rejection — **persisting is a separate approval-gated step (M2)** |
| `standards.evaluate` | READ | session end data | pass/fail per standard + the raw metric |
| `cycle.template_get` | READ | template_id | template with phase definitions |
| `cycle.template_publish` | PUBLISH | template draft (coach only) | published version + student notification draft |
| `cycle.phase_metrics` | READ | session(s) | per-phase parameter aggregates and drift vs baseline |
| `standards.validate_instruction` | READ | title, dose, metric/operator/threshold/window | `PracticeInstruction` draft or a rejection with the missing part named |
| `drill.recommend` | READ | failed standard / focus tag | `Drill[]` with execution, dose, and the standard it targets |

`standards.suggest` encodes the belief that a standard must be **achievable**: proposing
"group ≤ 4 cm" to an archer whose last ten ends averaged 9.5 cm is not coaching, it is
demoralisation. The suggestion therefore reads the archer's own distribution.

## 5. Equipment & simulator (deterministic, no LLM arithmetic)

| Tool | Risk | Input | Output |
| --- | --- | --- | --- |
| `equip.read_set` | READ | — | bow / release / arrows / accessories |
| `equip.draft_change` | WRITE_DRAFT | field edits + rationale | `ChangeProposal` with an effective date and a "what this invalidates" note |
| `sim.arrow_setup` | READ | shaft, components, draw weight, draw length, IB, ATA | total mass, FOC %, static spine recommendation, KE, momentum, estimated fps with assumption list |
| `sim.foc` / `sim.ke` | READ | components / mass+speed | number + formula shown |
| `sim.spine_check` | READ | shaft spine, draw weight, DL, point mass, ATA, cam aggressiveness | coherent / borderline / mismatch, with the chart source |
| `sim.sight_marks` | READ | two known sight marks | interpolated/extrapolated marks + a warning that extrapolation beyond 1.3× is a guess |
| `sim.speed_estimate` | READ | mass, KE or chrono data | estimate with ± band; labelled INTERPOLATED when derived |
| `sim.tune_advisor` | READ | current setup + symptom (e.g. "paper tear right") | ranked candidate adjustments with expected direction and a required verification protocol |

Every `sim.*` output carries `{assumptions[], confidence, verification_step}`. A tuning
recommendation without a verification step is rejected by the sensor layer.

## 6. Planning & load

| Tool | Risk | Input | Output |
| --- | --- | --- | --- |
| `plan.draft_week` | WRITE_DRAFT | availability, goal, current standards, load history | `TrainingPlanDraft` — blocks with volume, intensity, focus, standard, and the load check |
| `plan.next_session` | READ | time available, range access | one session plan with arrows, ends, standard, drills |
| `load.acwr_check` | READ | proposed weekly arrows + gym volume vs 4-week history | ratio + verdict + the reasoning (0.8–1.3 band) |
| `load.ramp_check` | READ | proposed change vs 2 weeks prior | max +10 %/week verdict |
| `load.monotony_strain` | READ | last 7/28 days | monotony & strain indices |
| `gym.template` | READ | goal, equipment available, injury flags | supporting-practice block (rotator cuff, scapular, core, grip) with sets/reps — **injury flags divert to the referral template** |

## 7. Knowledge (cited only)

| Tool | Risk | Input | Output |
| --- | --- | --- | --- |
| `knowledge.search` | READ | query, filters (topic, tier) | ≤ 5 snippets, each with a full `EvidenceRef` |
| `knowledge.fetch` | READ | evidence_ref | full extracted passage + metadata |
| `knowledge.cite` | READ | claim text + refs | formatted citation block |

`knowledge.*` never returns a snippet without a resolvable `EvidenceRef`
(`{source_id, title, author, year, venue, url_or_doi, tier, quote, retrieved_at}`).
Tiers: `PEER_REVIEWED · COACHING_CONSENSUS · MANUFACTURER_DOC · ANECDOTAL`.
The librarian is required to state the tier in user-facing text.

## 8. Reporting

| Tool | Risk | Input | Output |
| --- | --- | --- | --- |
| `report.skill_evolution` | READ | archer, param keys, window | multi-parameter time series + change-point annotations + z-scores vs own baseline |
| `report.session_report` | READ | session id | score stats, group trend, parameters that moved, standards pass/fail |
| `report.coach_card` | READ | archer, period | one-page summary for a coach: adherence, standards, drift, questions to ask |
| `report.export` | WRITE | format (csv/json/markdown) | artifact path (PII-stripped mode available) |

## 9. Guard & meta tools

| Tool | Risk | Purpose |
| --- | --- | --- |
| `guard.medical_screen` | READ | keyword/pattern screen run on every inbound message before anything else; returns `{flag, refer_to}` |
| `guard.discipline_scope` | READ | rejects recurve/barebow/other-discipline requests with a clear scope message |
| `guard.claim_gate` | READ | validates `Claim[]` before an insight is persisted (evidence, n, units) |
| `guard.executability` | READ | validates that instructions contain metric + threshold + window |
| `artifact.write` | WRITE | run-scoped files under `data/artifacts/<run_id>/` |
| `artifact.read` | READ | read back an offloaded result |
| `run.events` | READ | the observability log for debugging a run |

**Never exposed to the model (`DENY`):** raw SQL execution, arbitrary filesystem access,
network egress, shell, record deletion, `AGENTS.md`/policy edits, anything with the word
"diagnose" in its contract.

## 10. Tool result envelope (uniform)

```json
{
  "ok": true,
  "data": { "...": "schema-typed payload" },
  "units": { "group_radius_cm": "cm" },
  "assumptions": ["speed interpolated from 2 sight marks", "IB assumed 29 in"],
  "confidence": "MEASURED | DERIVED | ESTIMATED | INTERPOLATED | INSUFFICIENT_DATA",
  "n": 42,
  "artifact_ref": "data/artifacts/run_01H.../ledger_read.json",
  "warnings": ["3 rows skipped: hold_time_s out of plausible range"],
  "provenance": { "tool_version": "0.0.1", "data_snapshot_hash": "sha256:..." }
}
```

A tool that cannot fill `confidence` honestly must return `ok:false` with a reason. The
absence of a value is information; a fabricated value is corruption.
