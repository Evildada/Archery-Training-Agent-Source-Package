# 00 — Product Brief

**Working name:** AI Archery Assistant (v1 — compound only)
**Status:** draft v0.2 — six questions answered 2026-10-08 (Q1, Q2, Q3, Q5, Q6, Q11); the
remaining eleven are tracked in `07-open-questions.md` with their defaults in force.

**Decisions in force**
| # | Decision | Consequence |
| --- | --- | --- |
| Q1 | The v1 user is the **pair**, and a coach is usually also an archer | roles are capabilities on one account (`AccountRole`), not account types |
| Q2 | Day-one job: **"is my setup right"** | M1 is re-scoped: capture + setup assessment first (docs/06) |
| Q3 | Capture is **per-end phone taps** | ten-second-per-end budget is a hard constraint |
| Q5 | The **recommended ten** parameters are mandatory; all 74 stay registered | `CORE_PARAMETERS` in `domain/parameters.py` |
| Q6 | Timings are **self-estimated**, `reliability=low` | timing findings are provisional by construction |
| Q11 | Load limits **warn, never block** | `sensors/load.py` behaviour is final for v1 |

---

## 1. The problem

A compound archer's improvement is limited by **repeatability**, not by knowledge.
Everyone knows they should "aim, expand, surprise release". Almost nobody can tell you
*which* of their own parameters drifted between the session where they shot 590 and the
session where they shot 560.

Coaches see the same problem from the other side: they teach a method, the student
practises alone for two weeks, and the method is re-interpreted (or lost). There is no
shared, structured record of *what was taught*, *what was practised*, and *what changed*.

**Hypothesis (the user's own, and the spine of this product):**

> A set of parameters can form a regression that maintains a stable position.

This is testable, and that is exactly why the harness must capture structured parameters
from day one — a regression is only as good as the ledger it reads from.

## 2. Users

| User | Primary need | Frequency of use |
| --- | --- | --- |
| **Archer** (primary) | "What do I practise today, what number do I hit, what changed since last week?" — and, at M1, "is my setup right?" | daily, at the range and at home |
| **Coach** | Publish a method once, have students practise *that* method, see who is drifting. In practice the same person also shoots (Q1), so the app must switch hats without switching accounts | weekly, across several students |
| **Parent / guardian** | Understand progress, consent to data handling (many archers are minors) | monthly |

Explicit non-users in v1: recurve / barebow / traditional archers, pro-shop tuning
services, competition organisers.

## 3. The five systems (product view)

The original idea list, normalised into five buildable systems with a single shared spine.

```
                         ┌────────────────────────────────────────────┐
                         │  SPINE: Parameter Ledger + Shot Cycle record│
                         │  (every system reads and writes this)       │
                         └────────────────────────────────────────────┘
                                            ▲
   ┌────────────────┬───────────────────┬───┴───────────────┬────────────────────┐
   │ S1 SHOT CYCLE  │ S2 EQUIPMENT      │ S3 TRAINING LOG   │ S4 SIMULATOR       │
   │ + FORM PROFILE │ + ARROW SETUP     │ + STANDARDS       │ + TUNE ADVISOR     │
   │                │                   │                   │                    │
   │ phase timings, │ bow brand/model,  │ mode, face, arrow │ spine / FOC / KE / │
   │ anchor, hold,  │ cam/limb, release,│ count, drill,     │ speed / sight-mark │
   │ float, tension │ arrow spec, tune  │ focus, standards  │ estimates          │
   └────────────────┴───────────────────┴───────────────────┴────────────────────┘
                                            ▲
                    ┌───────────────────────┴────────────────────────┐
                    │ S5 COACHING INTELLIGENCE                      │
                    │ interactive standards · research w/ citations │
                    │ skill-evolution regression · gym/plan builder │
                    └───────────────────────────────────────────────┘
```

### S1 — Shot Cycle & Form Profile
Record the archer's cycle as a *named, versioned template* (phases: routine → stance →
nock/raise → draw → transfer to hold → anchor → aim/expand → release → follow-through)
and then record per-shot instances against it: phase timings, hold duration, anchor
pressure, grip pressure, back tension, aim float size, and outcome (score + hit offset).
The **Shooter Profile** is the slowly-changing half of the same parameter set (anchor
type, release type, draw length, let-off, poundage, peep/scope configuration).

### S2 — Equipment & Arrow Setup
Bow brand/model/cam configuration, release device, and full arrow specification
(brand, model, shaft spine, length, component masses, fletching, point profile).
Equipment is a *parameter source*, not decoration: poundage and arrow mass directly enter
the cycle and the simulator.

### S3 — Training Log & Standards
Every session records: mode (blank bale / grouping / scoring / competition simulation /
distance move / SPT / gym), target face, arrow count, distance, technique focus, and the
**standards** the session was measured against. A standard is executable or it is not a
standard:

> ❌ "work on your release"
> ✅ "30 arrows at 18 m, group radius ≤ 6.0 cm, hold time 2.0–4.0 s in ≥ 80 % of shots"

### S4 — Arrow / Bow Simulator & Tune Advisor
Deterministic calculators (not LLM guesses): total arrow mass, FOC %, kinetic energy,
momentum, speed estimation, spine-vs-poundage coherence, sight-mark progression.
Every output carries its **assumptions and a confidence label**, and never recommends a
tuning change without a range-verification step.

### S5 — Coaching Intelligence
The interactive surface: turns the ledger into (a) measurable practise instructions,
(b) cited research insight, (c) skill-evolution views over time, (d) a gym / shot-volume
/ schedule planner that respects the archer's real availability and load limits.

## 4. v1 scope

**In:** compound only · single archer per profile · local-first storage · manual +
assisted data capture · deterministic simulator · cited research assistant · coach-owned
templates and standards · skill-evolution views.

**Out (deliberately):** recurve/barebow · computer-vision form grading from video ·
hardware sensor integration (accelerometer/IMU on the bow) · competition scoring
integration · marketplace/social features · medical or injury advice.

Video and IMU are *architecturally anticipated* (the parameter ledger accepts
`source: MEASURED` values from any producer) but not built in v1.

## 5. Success criteria for v1 (measurable, not vibes)

| # | Criterion | Measure |
| --- | --- | --- |
| C1 | Capture is cheap enough to actually happen | a full 60-arrow session logged in < 3 min of interaction |
| C2 | Standards are executable | every generated instruction contains metric + threshold + window |
| C3 | Data is trustworthy | 100 % of persisted records pass schema + plausibility sensors |
| C4 | Claims are honest | 0 unsourced factual claims in generated output (eval suite gated) |
| C5 | The spine generalises | ≥ 3 archers × ≥ 12 sessions of usable parameter data |
| C6 | The regression question is answerable | per-parameter effect estimates with n, effect size and CI — or an explicit "insufficient evidence" |

## 6. What success is *not*

It is not "an AI that tells you your form is bad". It is a system that makes an archer's
own data legible enough that they can hold a stable position on purpose, and that a coach
can point at when teaching.
