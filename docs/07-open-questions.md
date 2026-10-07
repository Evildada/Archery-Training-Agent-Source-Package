# 07 — Open Questions

This is the interface between the design and the archer/coach who owns it. Each question has
a **recommended default** so work can continue, but the default is provisional until the
answer is written underneath it. Guessing silently is the most expensive failure mode here.

Legend: 🔴 blocks M1 · 🟠 blocks M2–M3 · 🟢 blocks M4–M5

---

### 🔴 Q1 — Who is the v1 user: the archer, the coach, or the pair?
The whole data model changes: a single-user personal log vs a coach dashboard with many
students. The brief assumes **the pair**, with coach-owned templates (M2).
**Default:** build the ledger archer-centric, add `coach_id` and template ownership now.
**Answer:** _(open)_

### 🔴 Q2 — What is the *actual* job on day one?
Ranked guesses: (a) "what do I practise today", (b) "why did my score drop", (c) "log my
session with less typing", (d) "is my setup right".
**Default:** (c) then (a) — capture is the bottleneck; everything downstream starves without it.
**Answer:** _(open)_

### 🔴 Q3 — Where does data come from at the range? *(determines the capture UX)*
phone-tap per end · voice note after the session · paper scorecard transcribed later ·
scorecard photo (OCR, later) · IMU/video (v2).
**Default:** per-end phone taps + optional voice/typed paragraph normalised by the agent.
**Answer:** _(open)_

### 🟠 Q4 — Model & hosting *(decides `runtime/model_provider.py`)*
Cloud API, local (Ollama/llama.cpp), or both behind one interface.
**Default:** one interface, cloud default for quality, local for archers who refuse cloud
(small models are acceptable because the *harness* carries the domain logic, not the model).
**Answer:** _(open)_

### 🟠 Q5 — Which parameters will the archer *actually* measure?
Every parameter has a capture cost. Long lists fail. The registry has `capture_cost` precisely
so a subset can be chosen: which 8–12 are "always" and which are "when asked"?
**Default:** always = score/offset, arrows, distance, mode, RPE, readiness, hold time,
grip pressure, aim float, routine adherence.
**Answer:** _(open)_

### 🟠 Q6 — How is `hold_time_s` (and other timings) captured without a sensor?
Self-estimate (cheap, ±40 %), coach stopwatch, phone timer, video frame counting, or
clicker/audio cue. This decides whether timings may enter the regression at all.
**Default:** self-estimate is stored with `reliability=low` and never used for a SUPPORTED
claim; a coach stopwatch or video marks a value `MEDIUM`/`HIGH`.
**Answer:** _(open)_

### 🟠 Q7 — Scoring convention: ring, offset, or both?
A 10 with a 3 cm drift is not a 10 taken cleanly. Storing `(x, y)` offsets unlocks group
analysis and aim-float work, but requires more entry effort (or an electronic target).
**Default:** store both; offsets optional per mode (`grouping` asks for them, `scoring` does not).
**Answer:** _(open)_

### 🟠 Q8 — Target faces, distances, and ruleset in scope for v1?
Indoor 18 m on the 40 cm 3-spot, 50 m on the 80 cm, or both? Which governing ruleset
(WA indoor/outdoor compound)? This pins the geometry tables.
**Default:** 18 m 3-spot + 50 m 80 cm, World Archery compound rules, plus blank bale.
**Answer:** _(open)_

### 🟠 Q9 — Coaching method ownership: one house method or many?
If the product's promise is "unify a coach's teaching method", the template must be
*the coach's*, not ours. But then which fault taxonomy does the app use internally?
**Default:** our internal phase keys + fault taxonomy as the neutral vocabulary; each coach's
template maps onto it (lossy in one direction only, and the loss is documented).
**Answer:** _(open)_

### 🟠 Q10 — Gym/support-work content: how far do we go?
"Support practice planner" could mean anything between a checklist and a periodised strength
program. Injury risk rises steeply with specificity.
**Default:** accessory work only (rotator cuff, scapular control, core, grip/forearm), no
periodisation, hard stop on any injury flag → referral.
**Answer:** _(open)_

### 🔴 Q11 — Load limits: is there a maximum safe arrow volume we should enforce?
ACWR and +10 %/week are the defaults, but youth archers and high-volume compound training
have their own conventions.
**Default:** ACWR 0.8–1.3, ramp ≤ 10 %/week, warn (do not block) beyond; the archer can
override with a logged reason.
**Answer:** _(open)_

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
