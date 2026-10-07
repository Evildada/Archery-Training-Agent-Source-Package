"""Curated knowledge base — the only place a factual claim may come from.

Design choice: **no vector database in v1.** The corpus is deliberately small (tens of sources,
checked by a human), citations matter more than semantic recall, and lexical search over a
curated corpus is auditable — an embedding can surface a plausible-sounding source that does not
actually say what the claim needs it to say.

Each line of ``knowledge/sources/*.jsonl`` is one document:

.. code-block:: json

    {"ref": {"source_id": "...", "title": "...", "author": "...", "year": 2021,
             "venue": "...", "doi": "10.xxxx/...", "tier": "peer_reviewed",
             "quote": "...", "locator": "p. 42"},
     "topics": ["target_panic", "routine"],
     "body": "extracted passage text used for lexical search"}

The corpus ships **empty** on purpose. Filling it is milestone M4 and requires a human to check
each source; a placeholder citation would poison every downstream claim, so there are none.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from archery_agent.domain.insight import EvidenceRef

DEFAULT_KNOWLEDGE_ROOT = Path("knowledge/sources")
_WORD_RE = re.compile(r"[a-z0-9]{3,}")


class KnowledgeDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: EvidenceRef
    topics: tuple[str, ...] = ()
    body: str = ""


class KnowledgeHit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    document: KnowledgeDocument
    score: float = Field(ge=0.0)


class KnowledgeBaseError(RuntimeError):
    pass


class KnowledgeBase:
    """Lexical search over a small, human-curated corpus."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else DEFAULT_KNOWLEDGE_ROOT
        self._documents: tuple[KnowledgeDocument, ...] = ()
        self._load_problems: list[str] = []
        self._loaded = False

    @property
    def size(self) -> int:
        self._ensure_loaded()
        return len(self._documents)

    @property
    def load_problems(self) -> tuple[str, ...]:
        self._ensure_loaded()
        return tuple(self._load_problems)

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        documents: list[KnowledgeDocument] = []
        if not self.root.exists():
            self._load_problems.append(f"knowledge root {self.root} does not exist")
            self._documents = ()
            return
        for path in sorted(self.root.glob("*.jsonl")):
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if not stripped or stripped.startswith("//"):
                    continue
                try:
                    documents.append(KnowledgeDocument.model_validate(json.loads(stripped)))
                except (json.JSONDecodeError, ValidationError) as exc:
                    self._load_problems.append(f"{path.name}:{line_number}: {exc}")
        self._documents = tuple(documents)

    def all_documents(self) -> tuple[KnowledgeDocument, ...]:
        self._ensure_loaded()
        return self._documents

    def search(
        self, query: str, *, limit: int = 5, topic: str | None = None
    ) -> tuple[KnowledgeHit, ...]:
        """Term-overlap search. Returns nothing rather than a bad match, by design."""
        self._ensure_loaded()
        terms = set(_WORD_RE.findall(query.lower()))
        if not terms:
            return ()
        hits: list[KnowledgeHit] = []
        for document in self._documents:
            if topic and topic.lower() not in {t.lower() for t in document.topics}:
                continue
            haystack = " ".join(
                (
                    document.ref.title,
                    document.ref.venue,
                    document.ref.quote,
                    document.body,
                    " ".join(document.topics),
                )
            ).lower()
            words = set(_WORD_RE.findall(haystack))
            overlap = terms & words
            if not overlap:
                continue
            score = len(overlap) / len(terms)
            if document.ref.tier.value == "peer_reviewed":
                score += 0.15
            hits.append(KnowledgeHit(document=document, score=round(score, 4)))
        return tuple(sorted(hits, key=lambda h: h.score, reverse=True)[:limit])
