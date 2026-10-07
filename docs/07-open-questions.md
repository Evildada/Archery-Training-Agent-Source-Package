# 07 — Open Questions

This is the interface between the design and the archer/coach who owns it. Each question has
a **recommended default** so work can continue, but the default is provisional until the
answer is written underneath it. Guessing silently is the most expensive failure mode here.

Legend: 🔴 blocks M1 · 🟠 blocks M2–M3 · 🟢 blocks M4–M5
Status: **eleven answered on 2026-10-08** (Q1-Q3, Q5-Q11). A default is never an answer: this
file keeps the provisional ones visible until someone actually decides.

---

### 🔴 Q1 — Who is the v1 user: the archer, the coach, or the pair?
The whole data model changes: a single-user personal log vs a coach dashboard with many
students. The brief assumes **the pair**, with coach-owned templates (M2).
**Default:** build the ledger archer-centric, add `coach_id` and template ownership now.
**Answer (2026-10-08):** the **pair** — and *the coach is usually also an archer themselves*.
So a role is a **capability on one account**, not an account type: `Archer.roles` holds a
non-empty set of `AccountRole` (ARCHER / COACH / GUARDIAN), a self-coached archer keeps COACH
without a `coach_id`, and every write must be audit-able as "which hat was on". Implemented in
`domain/entities.py` + `domain/enums.py`; enforced by `tests/test_domain_records.py`.

### 🔴 Q2 — What is the *actual* job on day one?
Ranked guesses: (a) "what do I practise today", (b) "why did my score drop", (c) "log my
session with less typing", (d) "is my setup right".
**Default:** (c) then (a) — capture is the bottleneck; everything downstream starves without it.
**Answer (2026-10-08): (d) "is my setup right"** — the equipment/setup assessment is the day-one
job, with capture as its prerequisite rather than as the headline. This is the cheapest path to
real value: the arrow/spine/sight physics is already built and testable (`sim/`), it needs no
weeks of history to be useful, and it produces the *equipment record* the later regression needs
anyway. **Consequence:** M1 is re-scoped (see `docs/06-roadmap.md`) to *capture + setup
assessment*, and every setup claim must end in a named range test that would confirm or refute
it — an unverifiable setup claim is the same sin as an invented number.

### 🔴 Q3 — Where does data come from at the range? *(determines the capture UX)*
phone-tap per end · voice note after the session · paper scorecard transcribed later ·
scorecard photo (OCR, later) · IMU/video (v2).
**Default:** per-end phone taps + optional voice/typed paragraph normalised by the agent.
**Answer (2026-10-08): phone taps per end**, with free-text as the escape hatch (the agent
normalises a typed paragraph, it does not require one). Implication: the capture surface must be
usable with one hand, gloves on, in under ten seconds per end — which is why the mandatory set
(Q5) is capped and why the ten-second budget is treated as a hard design constraint, not a
preference. The `capture` subagent stays at M3; the tap UI can be built before it.

### 🟠 Q4 — Model & hosting *(decides `runtime/model_provider.py`)*
Cloud API, local (Ollama/llama.cpp), or both behind one interface.
**Default:** one interface, cloud default for quality, local for archers who refuse cloud
(small models are acceptable because the *harness* carries the domain logic, not the model).
**Answer (2026-10-08): one interface, cloud default, local as a real option.** Implemented as
`CLOUD_PROVIDERS` / `LOCAL_PROVIDERS`, `ProviderKind` and `settings_from_env` in
`runtime/model_provider.py`: a cloud provider without a key reports `ready=False` and the doctor
says so; a local provider needs no key. The structural point is that the sensors, the safety
screen and the tool layer are identical either way — choosing local degrades the *conversation*
and never a guardrail.

### 🟠 Q5 — Which parameters will the archer *actually* measure?
Every parameter has a capture cost. Long lists fail. The registry has `capture_cost` precisely
so a subset can be chosen: which 8–12 are "always" and which are "when asked"?
**Default:** always = score/offset, arrows, distance, mode, RPE, readiness, hold time,
grip pressure, aim float, routine adherence.
**Answer (2026-10-08): the recommended ten, as the *mandatory* set — and all 74 stay in the
bank for a later review.** Encoded as `CORE_PARAMETERS` in `domain/parameters.py` (eleven keys
covering ten concepts: the group centre is stored as an x/y pair, and `mode`/distance are session
fields rather than registry parameters). The remaining parameters stay registered, queryable and
validated; they are simply not asked for by default. The review is a deliberate future task, and
`validate_registry()` refuses a core set that references an unregistered key so a rename cannot
silently drop one.

### 🟠 Q6 — How is `hold_time_s` (and other timings) captured without a sensor?
Self-estimate (cheap, ±40 %), coach stopwatch, phone timer, video frame counting, or
clicker/audio cue. This decides whether timings may enter the regression at all.
**Default:** self-estimate is stored with `reliability=low` and never used for a SUPPORTED
claim; a coach stopwatch or video marks a value `MEDIUM`/`HIGH`.
**Answer (2026-10-08): self-estimate**, stored as `reliability=low`. The gate that follows from
this is already implemented: a SUPPORTED claim needs n ≥ 30 *and* a corrected q < 0.10, and the
answer must carry the reliability of its inputs — so a timing-based finding from self-reported
values arrives explicitly marked as provisional and is never the sole basis for a plan change.

### 🟠 Q7 — Scoring convention: ring, offset, or both?
A 10 with a 3 cm drift is not a 10 taken cleanly. Storing `(x, y)` offsets unlocks group
analysis and aim-float work, but requires more entry effort (or an electronic target).
**Default:** store both; offsets optional per mode (`grouping` asks for them, `scoring` does not).
**Answer (2026-10-08): both — offsets optional per mode.** `domain/entities.py` declares
`OFFSETS_REQUIRED_MODES` (grouping, shot-execution volume) and `offsets_required(mode)`;
`sensors/validators.py::validate_offsets_for_mode` emits an `offsets_missing_for_mode` **warning**
when a mode that needs positions has none. A warning rather than an error: rejecting the session
would punish a range-day compromise and lose the data — the report simply states that group shape
is unavailable, and why.

### 🟠 Q8 — Target faces, distances, and ruleset in scope for v1?
Indoor 18 m on the 40 cm 3-spot, 50 m on the 80 cm, or both? Which governing ruleset
(WA indoor/outdoor compound)? This pins the geometry tables.
**Default:** 18 m 3-spot + 50 m 80 cm, World Archery compound rules, plus blank bale.
**Answer (2026-10-08): 18 m on the 40 cm vertical 3-spot, 50 m on the 80 cm face, WA compound
rules, blank bale at any distance.** Encoded as `V1_FACES`, `V1_RULESET` and
`V1_FACE_AT_DISTANCE_M` in `domain/targets.py`, with a test asserting that each face's range
rating actually reaches the distance v1 shoots it at — a geometry table and a ruleset that quietly
disagree is how wrong scores happen. The 40 cm 10-ring and the 122 cm face stay implemented but
outside the v1 promise: practice on them is reported as out-of-scope practice, not as a scored
result.

### 🟠 Q9 — Coaching method ownership: one house method or many?
If the product's promise is "unify a coach's teaching method", the template must be
*the coach's*, not ours. But then which fault taxonomy does the app use internally?
**Default:** our internal phase keys + fault taxonomy as the neutral vocabulary; each coach's
template maps onto it (lossy in one direction only, and the loss is documented).
**Answer (2026-10-08): neutral taxonomy, the coach owns the template.** The seven phase keys
already existed in the canonical cycle template; `domain/standards.py` now adds `FaultKey` (16
neutral faults) and `FAULTS_BY_PHASE`, so a fault attached to the wrong phase is a closed-set
error rather than free text. Nothing here teaches a house *method*: the coach's template is the
method, and the taxonomy is what makes it measurable and comparable across students.

### 🟠 Q10 — Gym/support-work content: how far do we go?
"Support practice planner" could mean anything between a checklist and a periodised strength
program. Injury risk rises steeply with specificity.
**Default:** accessory work only (rotator cuff, scapular control, core, grip/forearm), no
periodisation, hard stop on any injury flag → referral.
**Answer (2026-10-08): accessory work only.** The ceiling is a constant in code, not a sentence in
a prompt: `agents/specs.py::CONSTRAINTS["planner"]` carries "accessory work only - no periodised
strength programme", "never prescribe through pain", the load guardrail, and the requirement that
every block carries a scoreable standard. `AgentSpec.constraints` is merged into every brief by
the dispatcher, so a caller can add restrictions but cannot remove these: the contract travels
with the specialist instead of living in a prompt that can be rewritten.

### 🔴 Q11 — Load limits: is there a maximum safe arrow volume we should enforce?
ACWR and +10 %/week are the defaults, but youth archers and high-volume compound training
have their own conventions.
**Default:** ACWR 0.8–1.3, ramp ≤ 10 %/week, warn (do not block) beyond; the archer can
override with a logged reason.
**Answer (2026-10-08): warn, do not block** — matching the implemented `sensors/load.py`
behaviour. The override is a logged reason, never a silent bypass; two consecutive over-threshold
weeks escalate the wording but still do not block.

### 🟢 Q12 — Research corpus: what may we cite, and how strict on tiers?
Peer-reviewed only? Include coaching books and manufacturer tuning guides (tiered)?
**Default:** all four tiers allowed, tier always displayed; PEER_REVIEWED required for any
claim about injury, psychology, or physiology.
**Answer:** _(open)_

### 🟢 Q13 — Visual "form recognition" (usage note #1): automated or human-in-the-loop?
Automatic judging from video is a hard, high-risk feature (and out of v1 scope by design).
**Default:** v1 = parameter trajectories + annotated overlays for a human to read; no
automated form scores.
**Answer:** _(open)_

### 🟢 Q14 — Deployment shape
Local desktop app, self-hosted web, native mobile, or note-first (a chat channel the archer
already uses)? Determines how much UI work M5 needs.
**Default:** local-first CLI/Python core + minimal web UI; the ledger stays portable so the
surface can change without a migration.
**Answer:** _(open)_

### 🟢 Q15 — Multi-archer sharing & leaderboards?
Deferred from v1, but the sharing model (if any) affects privacy design (minors!).
**Default:** no cross-archer sharing in v1; exportable coach card only.
**Answer:** _(open)_

### 🟢 Q16 — Competition calendar integration
The planner's value improves sharply with real competition dates and taper targets.
**Default:** manual date entry now, import later.
**Answer:** _(open)_
