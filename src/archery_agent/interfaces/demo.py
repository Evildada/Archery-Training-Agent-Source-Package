"""The deterministic end-to-end demo.

What this demonstrates — and why it is worth more than a screenshot of a chat:

* a full turn runs through **guard → context → plan → act → verify → persist**;
* the tools are real tools, dispatched through the real registry with real sensors;
* the answer is composed *from tool results*, so the numeric-grounding gate passes on merit;
* no model, no network, no credentials.

The data is synthetic and the planner is a fixed template. Both of those are stated in the
output: the purpose is to prove the harness, not to pretend to be intelligence.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict

from archery_agent.domain.enums import Confidence, ObservationSource, Reliability
from archery_agent.domain.ledger import ParameterObservation
from archery_agent.runtime.context import AssembledContext
from archery_agent.runtime.loop import PlannerDecision, ToolObservation
from archery_agent.store.memory import InMemoryLedger

DEMO_ARCHER_ID = "arc_demo0001"

#: The parameters the demo archer records. Chosen to include one that genuinely drives the
#: outcome in the synthetic data (hold time) and two that do not, so the statistics have to
#: discriminate rather than confirm.
DEMO_KEYS: tuple[str, ...] = (
    "cycle.hold_time_s",
    "tension.grip_pressure_1_5",
    "mental.routine_adherence_pct",
)


class DemoSeedReport(BaseModel):
    """What the seeding produced. Typed, so callers cannot mis-read it."""

    model_config = ConfigDict(extra="forbid")

    accepted: int
    rejected: int
    sessions: int
    shots: int
    ground_truth: dict[str, str]


def seed_demo_ledger(
    store: InMemoryLedger,
    *,
    archer_id: str,
    sessions: int = 12,
    arrows_per_session: int = 6,
    seed: int = 20261007,
) -> DemoSeedReport:
    """Generate a plausible 12-session history with a *known* structure.

    Ground truth baked into the synthetic data:

    * score rises with hold time (the effect the agent should find);
    * grip pressure is noise (the agent must not claim it);
    * routine adherence is a weak, real secondary effect (the agent may report it as
      preliminary at best).

    Having a known ground truth is what makes this a test rather than a demo, and it is the same
    approach the roadmap uses for M1's recovery test.
    """
    rng = random.Random(seed)
    start = datetime.now(UTC) - timedelta(days=sessions * 3)
    rows: list[ParameterObservation] = []

    for session_index in range(sessions):
        session_id = f"sess_demo{session_index:03d}"
        observed_at = start + timedelta(days=session_index * 3)
        # a slow improvement in hold time across the block, plus noise
        base_hold = 2.0 + 0.09 * session_index
        for shot_index in range(arrows_per_session):
            shot_id = f"{session_id}_shot{shot_index:02d}"
            hold = max(0.5, rng.gauss(base_hold, 0.35))
            grip = min(5.0, max(1.0, rng.gauss(3.0, 0.6)))
            routine = min(100.0, max(0.0, rng.gauss(72.0 + 0.6 * session_index, 8.0)))
            noise = rng.gauss(0.0, 0.45)
            score = (
                7.4 + 0.55 * (hold - 2.6) + 0.006 * (routine - 75.0) + 0.05 * (grip - 3.0) + noise
            )
            score = min(10.0, max(4.0, score))

            common = {
                "archer_id": archer_id,
                "session_id": session_id,
                "shot_id": shot_id,
                "observed_at": observed_at,
                "distance_m": 18.0,
                "target_face_id": "WA_40CM_3SPOT_V",
            }
            rows.extend(
                [
                    ParameterObservation.model_validate(
                        {
                            **common,
                            "key": "cycle.hold_time_s",
                            "value": round(hold, 2),
                            "source": ObservationSource.SELF_REPORTED,
                            "reliability": Reliability.LOW,
                        }
                    ),
                    ParameterObservation.model_validate(
                        {
                            **common,
                            "key": "tension.grip_pressure_1_5",
                            "value": round(grip, 1),
                            "source": ObservationSource.SELF_REPORTED,
                            "reliability": Reliability.LOW,
                        }
                    ),
                    ParameterObservation.model_validate(
                        {
                            **common,
                            "key": "mental.routine_adherence_pct",
                            "value": round(routine, 1),
                            "source": ObservationSource.COACH_RATED,
                            "reliability": Reliability.MEDIUM,
                        }
                    ),
                    ParameterObservation.model_validate(
                        {
                            **common,
                            "key": "outcome.score_mean",
                            "value": round(score, 2),
                            "source": ObservationSource.DERIVED,
                            "reliability": Reliability.HIGH,
                        }
                    ),
                ]
            )

    batch = store.append(tuple(rows))
    return DemoSeedReport(
        accepted=len(batch.accepted),
        rejected=len(batch.rejected),
        sessions=sessions,
        shots=sessions * arrows_per_session,
        ground_truth={
            "cycle.hold_time_s": "real effect (score rises ~0.55 per +1 s hold)",
            "mental.routine_adherence_pct": "weak real effect (+0.006 per %)",
            "tension.grip_pressure_1_5": "no effect - a decoy the agent must not promote",
        },
    )


class DemoPlanner:
    """A deterministic template planner.

    It exists to prove the loop, and it is deliberately *not* a model: it calls summary, effects
    and trend tools, then composes an answer strictly from their outputs. That the composed
    answer passes the numeric-grounding gate is therefore evidence about the harness, not about
    the planner's fluency.
    """

    def __init__(self, archer_id: str, *, keys: tuple[str, ...] = DEMO_KEYS) -> None:
        self.archer_id = archer_id
        self.keys = keys

    def next_action(
        self,
        *,
        user_message: str,
        archer_id: str,
        context: AssembledContext,
        observations: tuple[ToolObservation, ...],
        step: int,
    ) -> PlannerDecision:
        del user_message, archer_id, context

        if step == 0:
            return PlannerDecision(
                kind="tool_call",
                tool_name="ledger.summary",
                arguments={"archer_id": self.archer_id, "keys": list(self.keys), "window_days": 90},
                reason="establish the archer's own baseline before any comparison",
            )
        if step == 1:
            return PlannerDecision(
                kind="tool_call",
                tool_name="stats.effects",
                arguments={
                    "archer_id": self.archer_id,
                    "outcome_key": "outcome.score_mean",
                    "candidate_keys": list(self.keys),
                    "window_days": 90,
                    "unit": "shot",
                },
                reason="test which recorded parameters actually move with the score",
            )
        if step == 2:
            hold = self._key(observations, "cycle.hold_time_s")
            if hold and hold.get("mean") is not None:
                return PlannerDecision(
                    kind="tool_call",
                    tool_name="stats.trend",
                    arguments={"archer_id": self.archer_id, "key": "cycle.hold_time_s"},
                    reason="a level is not a direction: check whether hold time is changing",
                )
        return PlannerDecision(kind="answer", answer_text=self._compose(observations))

    def _key(self, observations: tuple[ToolObservation, ...], key: str) -> dict[str, object] | None:
        for observation in observations:
            data = observation.result.data
            if isinstance(data, dict):
                summaries = data.get("summaries")
                if isinstance(summaries, dict) and key in summaries:
                    value = summaries[key]
                    if isinstance(value, dict):
                        return value
                if data.get("key") == key:
                    return data
        return None

    def _compose(self, observations: tuple[ToolObservation, ...]) -> str:
        lines: list[str] = []
        hold = self._key(observations, "cycle.hold_time_s")
        if hold and hold.get("mean") is not None:
            lines.append(
                f"Your recorded hold time averages {hold['mean']} s "
                f"(sd {hold['sd']}, n={hold['n']} arrows)."
            )

        for observation in observations:
            data = observation.result.data
            if not isinstance(data, dict) or "results" not in data:
                continue
            results = data["results"]
            if not isinstance(results, list):
                continue
            for row in results:
                if not isinstance(row, dict):
                    continue
                label = row.get("label")
                if label == "supported":
                    lines.append(
                        f"{row['parameter']} tracks your score: r = {row['r']} over "
                        f"n = {row['n_paired']} paired shots (q = {row['q']})."
                    )
                elif label == "preliminary":
                    lines.append(
                        f"{row['parameter']} is suggestive but unconfirmed (r = {row['r']}, "
                        f"q = {row['q']}, n = {row['n_paired']})."
                    )
                elif label == "insufficient_evidence" and row.get("q") is None:
                    lines.append(
                        f"{row['parameter']} has too few paired shots ({row['n_paired']}) to say "
                        "anything yet; keep recording it."
                    )
                elif label == "insufficient_evidence":
                    lines.append(
                        f"{row['parameter']} showed no detectable association (r = {row['r']}, "
                        f"q = {row['q']}, n = {row['n_paired']}) — treat that as a real "
                        "non-finding rather than a weak signal."
                    )

        for observation in observations:
            data = observation.result.data
            if isinstance(data, dict) and data.get("slope_per_session") is not None:
                lines.append(
                    f"Hold time is trending {data['slope_per_session']:+.3f} s per session over "
                    f"{data['sessions']} sessions ({data['label']}, r2 = {data['r2']})."
                )

        lines.append("")
        lines.append(
            "Deterministic demo: no model was called. The planner is a fixed template and the "
            "ledger is synthetic data with a known ground truth, so the numbers above are a test "
            "of the harness rather than of any intelligence."
        )
        lines.append(
            "Two limitations you should hold me to: this is a correlation from your own history "
            "with no control for equipment or distance changes, and the hold-time values are "
            "self-reported (reliability low) unless a coach times them."
        )
        return "\n".join(lines)


def model_provider_status() -> tuple[Confidence, str]:
    """Report the model boundary honestly: the demo proves the harness runs without one."""
    return (
        Confidence.INSUFFICIENT_DATA,
        "no model provider configured — deterministic harness only (see docs/06-roadmap.md M3)",
    )
