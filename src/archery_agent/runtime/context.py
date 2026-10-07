"""Context assembly — cache-stable ordering, explicit budgets, deterministic summaries.

Two principles (docs/01 §5):

* **Order is fixed and stable.** Static material first, volatile last, so provider-side prompt
  caching keeps working and attention is not wasted on re-reading rules.
* **The model never receives raw rows it could misread.** The ledger enters as a *deterministic
  summary* produced by a tool; raw data enters only as an artifact reference when a question is
  genuinely about specific shots.

Every section records its estimated size, so a turn's context can be audited after the fact —
"why was this slow/expensive/confused" is answerable from the event log rather than from memory.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

#: Cheap, provider-agnostic token estimate. Deliberately pessimistic (chars/3.5) so the budget
#: trips before the provider's hard limit does.
CHARS_PER_TOKEN: float = 3.5


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


class ContextSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    content: str
    stable: bool = Field(
        description="True for content that changes only with a harness/prompt version bump — "
        "these belong at the front for cache stability."
    )

    @property
    def est_tokens(self) -> int:
        return estimate_tokens(self.content)


class AssembledContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sections: tuple[ContextSection, ...] = ()
    dropped_sections: tuple[str, ...] = ()
    char_budget: int = 60_000

    @property
    def est_tokens(self) -> int:
        return sum(s.est_tokens for s in self.sections)

    def render(self) -> str:
        parts = []
        for section in self.sections:
            parts.append(f"### {section.name}\n{section.content}")
        return "\n\n".join(parts)

    def audit(self) -> dict[str, int]:
        return {s.name: s.est_tokens for s in self.sections}


#: The fixed order. Changing it is a design decision, not a refactor: it invalidates prompt
#: caching and shifts attention weights.
SECTION_ORDER: tuple[str, ...] = (
    "system",
    "harness_rules",
    "archer_profile",
    "ledger_summary",
    "standards",
    "knowledge",
    "history",
    "question",
)


def assemble_context(
    *,
    system_prompt: str,
    harness_rules: str = "",
    archer_profile: str = "",
    ledger_summary: str = "",
    standards: str = "",
    knowledge: str = "",
    history: tuple[str, ...] = (),
    question: str,
    char_budget: int = 60_000,
) -> AssembledContext:
    """Build the context block by block, dropping the *least critical* material first.

    Drop order is knowledge -> history -> standards -> ledger_summary, and the dropped section is
    named in the result so the answer can be labelled as degraded rather than quietly thinner.
    That matters: an answer given without the ledger summary is a different kind of answer, and
    the loop is required to say which one it is.
    """
    candidates: list[ContextSection] = [
        ContextSection(name="system", content=system_prompt, stable=True),
        ContextSection(name="harness_rules", content=harness_rules, stable=True),
        ContextSection(name="archer_profile", content=archer_profile, stable=False),
        ContextSection(name="ledger_summary", content=ledger_summary, stable=False),
        ContextSection(name="standards", content=standards, stable=False),
        ContextSection(name="knowledge", content=knowledge, stable=False),
        ContextSection(name="history", content="\n".join(history), stable=False),
        ContextSection(name="question", content=question, stable=False),
    ]
    by_name = {section.name: section for section in candidates}

    dropped: list[str] = []
    for name in ("knowledge", "history", "standards", "ledger_summary"):
        total = sum(
            by_name[n].est_tokens for n in SECTION_ORDER if n not in dropped and n in by_name
        )
        if total * CHARS_PER_TOKEN <= char_budget:
            break
        dropped.append(name)

    kept = tuple(
        by_name[name] for name in SECTION_ORDER if name not in dropped and by_name[name].content
    )
    return AssembledContext(sections=kept, dropped_sections=tuple(dropped), char_budget=char_budget)
