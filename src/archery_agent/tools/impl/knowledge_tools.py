"""``knowledge.*`` — the only path to an external factual claim.

The corpus is empty in this milestone, and the tool *says so* rather than returning nothing
quietly. That distinction is the whole point: an empty result and an unavailable corpus look
identical to a language model, and one of them invites invention.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from archery_agent.domain.enums import Confidence, EvidenceTier, RiskLevel
from archery_agent.store.knowledge_base import KnowledgeBase
from archery_agent.tools.registry import ToolContext, ToolResult, ToolSpec


class KnowledgeSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=3, max_length=300)
    limit: int = Field(default=5, ge=1, le=10)
    topic: str | None = Field(
        default=None, description="Optional topic filter, e.g. 'target_panic'."
    )
    minimum_tier: EvidenceTier | None = Field(
        default=None, description="Reject sources weaker than this tier."
    )


def _knowledge_search(payload: BaseModel, ctx: ToolContext) -> ToolResult:
    assert isinstance(payload, KnowledgeSearchInput)
    root = ctx.settings.get("knowledge_root")
    base = KnowledgeBase(root)

    if base.size == 0:
        problems = "; ".join(base.load_problems) or "no documents"
        return ToolResult.failure(
            "the curated knowledge base is empty, so there is no sourced answer available. "
            f"({problems}) Do NOT answer factual questions from memory — say that the research "
            "corpus is not loaded yet, offer what the archer's own logged data does show, and "
            "note the question so it can be added to the corpus. See knowledge/README.md."
        )

    hits = base.search(payload.query, limit=payload.limit, topic=payload.topic)
    if payload.minimum_tier is not None:
        order = list(EvidenceTier)
        cutoff = order.index(payload.minimum_tier)
        hits = tuple(h for h in hits if order.index(h.document.ref.tier) <= cutoff)

    if not hits:
        return ToolResult.failure(
            "no source in the corpus matches that query. Do not paraphrase something adjacent "
            "to it: report the gap, and answer from the archer's own data if that is relevant."
        )

    return ToolResult.success(
        {
            "results": [
                {
                    "source_id": hit.document.ref.source_id,
                    "title": hit.document.ref.title,
                    "author": hit.document.ref.author,
                    "year": hit.document.ref.year,
                    "venue": hit.document.ref.venue,
                    "tier": hit.document.ref.tier.value,
                    "quote": hit.document.ref.quote,
                    "locator": hit.document.ref.locator,
                    "doi": hit.document.ref.doi,
                    "url": hit.document.ref.url,
                    "match_score": hit.score,
                }
                for hit in hits
            ]
        },
        n=len(hits),
        confidence=Confidence.MEASURED,
        assumptions=(
            "lexical term-overlap search over a curated corpus (no embeddings in v1)",
            "every result carries the tier it comes from; the tier must be shown to the archer",
        ),
        warnings=(
            "quote the source and name its tier — a coaching-consensus source is not the same "
            "as a peer-reviewed one",
        ),
        snapshot_hash=ctx.data_snapshot_hash,
    )


SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="knowledge.search",
        summary="Search the curated, cited corpus. Fails loudly when the corpus cannot answer.",
        risk=RiskLevel.READ,
        input_model=KnowledgeSearchInput,
        handler=_knowledge_search,
        tags=("research", "citations"),
    ),
)
