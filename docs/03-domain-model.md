# 03 — Domain Model & Parameter Ledger

Everything in this system is downstream of one design decision: **the ledger is tidy
long-format, and the parameter registry is versioned code.**

Long format (`one row per observation`) rather than wide (`one column per parameter`) because:

- parameters get added/renamed constantly in early development — in long format that is a
  registry change, not a migration of every historical row;
- missingness is explicit (an absent row means "not measured", not "zero");
- statistical code is uniform: filter → group → summarise, regardless of parameter;
- a new parameter becomes analysable the day it is registered.

---

> **Q1 (2026-10-08):** identity carries **roles**, not a type. `Archer.roles` is a non-empty set of
> `AccountRole` (ARCHER · COACH · GUARDIAN); a coach who also shoots holds both, and a
> self-coached archer has no `coach_id` but does have COACH. Writes must record which role
> authorised them, because "the coach changed my draw weight" and "I changed my draw weight" are
> different events in the regression, even when they are the same person.

## 1. Entity map

```
Archer ──┬── ShooterProfile (technique identity, slow-changing)
         ├── EquipmentSet ──┬── Bow (compound)
         │                  ├── Release
         │                  ├── ArrowSetup
         │                  └── Accessories (sight, scope, peep, rest, stabiliser)
         ├── CycleTemplate (versioned) ── CyclePhase[]
         ├── Session ──┬── End ── Shot ── ShotObservation
         │             └── StandardEvaluation
         ├── ParameterObservation[]  ← the ledger (long format)
         └── TrainingPlan ── PlannedBlock

Insight ── requires ── EvidenceRef[]
Standard ── references ── ParameterKey
```

## 2. Core entities

### Archer
`archer_id (pk) · display_name · birth_year (not full DOB) · handedness (RH/LH) ·
dominant_eye · guardian_consent (bool) · coach_id? · created_at · data_retention_class`

Minors are the default: only `birth_year`, never a full date of birth; no free-text PII.

### ShooterProfile (the "Shooter Profile" from the idea list)
The **slow-changing** half of the parameter set — who this archer is, technically:

| Field | Type | Notes |
| --- | --- | --- |
| `draw_length_in` | float | measured, re-checked monthly |
| `draw_weight_lb` | float | current peak weight |
| `let_off_pct` | float | 0–90 |
| `anchor_type` | enum | `release_hand_knuckle_behind_jaw`, `valley_wall`, `nose_on_string`, `custom` |
| `release_type` | enum | `hinge`, `thumb_button`, `caliper`, `resistance` |
| `aiming_style` | enum | `scope_ring`, `pin_float`, `hybrid` |
| `hold_strategy` | enum | `expansion_through_wall`, `timed_hold`, `surprise_break` |
| `peep_config`, `scope_power`, `pin_size` | — | affect aim float diameter |
| `cycle_template_id` | fk | current adopted template version |

The **fast-changing** parameters live in the ledger, not here. The split matters: a profile
edit is an event ("I changed anchor type on 2026-03-01") and the regression in S5 needs that
date as a change-point.

### CycleTemplate (versioned, immutable once published)
```
template_id · version · name · author (archer|coach|imported) · published_at
phases: [ {phase_key, order, name, definition, target_window?, 
           observe_params: [param_key], cue?, common_faults: [ {fault, symptom, drill_ref} ]} ]
```

Canonical v1 phase keys (order matters — this is the "constant cycle" the archer executes):

| # | phase_key | What it covers | Typical observed params |
| --- | --- | --- | --- |
| 1 | `routine` | pre-shot routine, stance, breathing, shot plan | `routine_adherence_pct`, `arousal_1_10` |
| 2 | `nock_raise` | nock, hook up, bow hand set, raise | `nock_to_release_s`, `grip_pressure_1_5` |
| 3 | `draw` | draw to wall, elbow alignment, transfer | `draw_time_s`, `draw_smoothness_1_5` |
| 4 | `hold_anchor` | settle into anchor, back tension build, valley | `hold_time_s`, `anchor_pressure_1_5`, `back_tension_1_5` |
| 5 | `aim_expand` | aiming, float acceptance, continuous expansion | `aim_time_s`, `aim_float_radius_cm`, `expansion_start_s` |
| 6 | `release` | release activation, surprise vs timed | `release_latency_ms`, `release_style_used` |
| 7 | `follow_through` | post-release stillness, bow behaviour | `follow_through_s`, `bow_drop_1_5` |

Coaches can publish their own template; the *phase keys* are the shared vocabulary that
makes "my coach's method" comparable across students (this is requirement #2 of the usage
notes: unify teaching method).

### EquipmentVersion (append-only, dated) — implemented at M1

`EquipmentVersion: version_id · archer_id · version (1,2,3…) · equipment{bow, release, arrow,
accessories} · effective_from · recorded_at · reason · changes[] · supersedes`

`effective_from` is when the setup started being shot; `recorded_at` is when it was typed in. They
differ whenever someone enters a change that already happened, and the statistics use
`effective_from`. `changes[]` holds the field-level delta against the previous version, computed
once at write time by `domain/equipment.py::diff_equipment` — recomputing it later is how a
change-point analysis drifts when a field is renamed.

Nothing is overwritten: the SQLite tables carry triggers that abort `UPDATE` and `DELETE`, so a
"fix the typo" statement fails loudly instead of rewriting history. Recording a version also
publishes its registry rows (draw weight, spine, masses) into the ledger with
`equipment_set_id`, which is what connects "which setup" to "which arrows".

### Session
`session_id · archer_id · started_at · mode · distance_m · indoor_outdoor · target_face_id ·
arrow_count · duration_min · planned_arrow_count · focus_tags[] · cycle_template_id ·
coach_note? · archer_note? · environment{wind_speed_mps, temp_c, humidity_pct, light} ·
equipment_set_id · rpe_1_10 · sleep_hours · reported_readiness_1_10`

`mode` enum: `blank_bale · grouping · scoring · competition_sim · distance_move ·
shot_execution_volume · gym · mixed`

### End / Shot
```
End:  end_id · session_id · index · distance_m · target_face_id · arrows_planned · notes?
Shot: shot_id · end_id · index · score_ring (1–10, X) · 
      horizontal_offset_cm · vertical_offset_cm · 
      params: map[ParameterKey → value]   ← write path into the ledger
```

Offset is stored, not just ring — a 10 with a 3 cm drift is different from a 10 dead centre,
and *that difference is the signal* the regression needs.

### ParameterDefinition (registry — code, versioned, not user-editable at runtime)

| Field | Meaning |
| --- | --- |
| `key` | stable id, e.g. `cycle.hold_time_s` |
| `category` | `anthropometric · bow_setup · release · arrow · cycle_timing · cycle_tension · aim · mental · outcome · load · environment · adherence` |
| `unit` | SI-ish, explicit; `None` for ordinal scales |
| `kind` | `ratio · interval · ordinal · categorical · count · boolean` |
| `scale` | for ordinals, the anchor definition of 1 and 5 ("1 = no awareness of sight picture") |
| `plausible_range` | sensor gate for typos (e.g. `hold_time_s` 0.2–30) |
| `better` | `higher · lower · band · none` + target band where known |
| `capture_cost` | `free · low · medium · high` — drives which parameters the coach UI asks for first |
| `source_kinds` | which of `self_reported · coach_rated · sensor · derived` are acceptable |
| `reliability_default` | `high · medium · low` for self-reported values |
| `affects` | which outcome this plausibly influences (used to prune the search space in S5) |
| `notes` | guidance for the archer — this is also the vocabulary the agent uses |

**Registry highlights for v1 (full list in `src/archery_agent/domain/parameters.py`):**

| key | unit | better | capture | note |
| --- | --- | --- | --- | --- |
| `bow.draw_weight_lb` | lb | band | low | must match spine; changes fps ~2 lb/lb |
| `bow.let_off_pct` | % | band | free | affects hold weight & wall feel |
| `arrow.total_mass_grains` | gr | band | low | 5 gr/lb is the common starting rule |
| `arrow.foc_pct` | % | band | medium | forward of centre; tune-sensitive |
| `arrow.speed_fps` | fps | none | medium | measured, not estimated, if chrono available |
| `arrow.ke_ftlb` | ft·lb | none | medium | derived from mass + speed |
| `arrow.spine_delta` | — | none | medium | spine chart vs actual draw weight |
| `cycle.draw_time_s` | s | band | low | rushed draw → target panic signature |
| `cycle.hold_time_s` | s | band | low | 2–4 s typical band for compound |
| `cycle.expansion_time_s` | s | band | medium | time from aim settle to release |
| `cycle.release_latency_ms` | ms | none | high | needs sensor/video |
| `cycle.nock_to_release_s` | s | band | low | whole-cycle tempo |
| `cycle.follow_through_s` | s | higher | medium | stillness after release |
| `tension.back_tension_1_5` | 1–5 | higher | low | coach-rated or self-rated |
| `tension.grip_pressure_1_5` | 1–5 | lower | low | over-grip = torque/left-right |
| `tension.anchor_pressure_1_5` | 1–5 | band | low | too light = float, too hard = pluck |
| `aim.aim_float_radius_cm` | cm | lower | medium | at target distance, scope ring ratio |
| `aim.aim_time_s` | s | band | low | |
| `mental.arousal_1_10` | 1–10 | band | free | pre-shot state |
| `mental.target_panic_flag` | bool | false | free | triggers a drill pathway, not a diagnosis |
| `mental.routine_adherence_pct` | % | higher | low | |
| `outcome.group_radius_cm` | cm | lower | derived | per end |
| `outcome.group_center_x_cm` | cm | 0 | derived | signed bias |
| `outcome.group_center_y_cm` | cm | 0 | derived | signed bias |
| `outcome.score_mean` | — | higher | derived | per end/session |
| `load.arrows_shot` | count | band | free | acute load |
| `load.draw_volume_lb` | lb·reps | band | derived | Σ draw weight × reps (gym + range) |
| `load.rpe_1_10` | 1–10 | band | free | session intensity |
| `load.acwr` | ratio | band | derived | acute:chronic workload, 0.8–1.3 sweet spot |
| `env.wind_speed_mps` | m/s | none | free | confounder — must be recorded to be controlled |
| `adherence.planned_completion_pct` | % | band | derived | |

This registry is the direct answer to "Parameters affecting the shooting cycle" — and the
"maybe more" in the idea list is handled by the registry being *code*, so new parameters are
a pull request with a `plausible_range` and a category, not a schema migration.

### Standard
```
standard_id · name · owner (archer|coach|system) · mode · distance_m · target_face_id?
metric: ParameterKey or composite (e.g. "group_radius_cm over last 3 ends")
operator: lte | gte | in_band | equals_band
threshold · band_lo/hi? · n_min · window (session|end|rolling_7d) · 
difficulty (foundation|development|competitive) · drill_ref?
```

**Executability rule (sensor-enforced):** every `Standard` must have metric + operator +
threshold + window + n_min. A standard that fails this cannot be persisted — the system
refuses to accept "work on your release" as a standard.

### Insight (every model-generated conclusion)
```
insight_id · run_id · archer_id · created_at · kind (observation|recommendation|plan|
education|capture_summary) · body · claim[] · evidence_refs[] · 
model_id · prompt_version · data_snapshot_hash · confidence_label · user_acknowledged
```

`claim[]` entries are typed: `{statement, value?, unit?, n?, effect?, ci?, evidence_refs[], 
evidence_label: SUPPORTED|PRELIMINARY|INSUFFICIENT_EVIDENCE|GENERAL_EDUCATION}`.

## 3. Scoring & target faces (compound set)

| face_id | ring layout | use |
| --- | --- | --- |
| `WA_40CM_10RING` | 40 cm, 10 rings | 18 m indoor / 50 m outdoor practice |
| `WA_40CM_3SPOT_V` | 3 vertical spots | 18 m indoor competition (compound) |
| `WA_80CM_10RING` | 80 cm | 50 m outdoor |
| `WA_122CM_10RING` | 122 cm | 70 m (recurve) — kept for completeness |
| `BLANK_BALE` | no score | form/volume work, shots are recorded but unscored |
| `CUSTOM_PRACTICE` | user-defined | e.g. small dots; must declare `spot_diameter_cm` |

Ring geometry, inner-10 (X) rules and the 3-spot offset convention are needed to convert
`(x, y)` offsets into rings and back. This is a pure function in `domain/targets.py` and is
tested against published ring diameters.

## 4. Data quality rules (enforced by sensors at write time)

1. **Plausible range** per parameter (typo guard: `hold_time_s = 250` is rejected with the
   expected range in the message).
2. **No silent zero:** an absent measurement is absent. `0` must be a legal value you meant.
3. **Context requirement:** `arrow.speed_fps` demands a distance and a bow id; `outcome.*`
   demands a distance and a target face.
4. **Reliability labelling:** self-reported values carry `reliability` and are never mixed
   with `sensor` values in the same aggregate without a flag in the output.
5. **Change-point integrity:** profile/equipment changes are timestamped events. A session
   cannot reference an equipment set that was retired before it.
6. **Unit integrity:** values are stored with their registry unit; a mismatch is a hard error,
   never a conversion (conversions happen at the boundary, in `domain/units.py`).
