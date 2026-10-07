"""Evidence references, claims and insights — the trust layer of the product.

Rules encoded here (AGENTS.md 3 and 8):

* no unsourced factual claim: an :class:`EvidenceRef` must be complete to exist at all;
* every insight carries its provenance — model id, prompt version, harness version and a
  hash of the data snapshot it was generated from — so any statement can be reproduced or
  withdrawn later;
* a claim's ``evidence_label`` is a *contract*: SUPPORTED and PRELIMINARY require either an
  external reference or the archer's own sample size. The strict statistical gate lives in
  :mod:`archery_agent.sensors.stats`; this module only makes the dishonest shape impossible
  to construct accidentally.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from archery_agent.domain.entities import utcnow
from archery_agent.domain.enums import (
    Confidence,
    EvidenceLabel,
    EvidenceTier,
    InsightKind,
)
from archery_agent.domain.ids import new_id

_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
_URL_RE = re.compile(r"^https?://\S+\.\S+$")


class EvidenceRef(BaseModel):
    """A citation. Incomplete citations are rejected at construction time."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=3, max_length=80)
    title: str = Field(min_length=3, max_length=300)
    author: str = ""
    year: int = Field(ge=1900, le=2100)
    venue: str = Field(default="", description="Journal, book, or publisher.")
    doi: str | None = None
    url: str | None = None
    tier: EvidenceTier
    quote: str = Field(
        default="",
        max_length=2000,
        description="The specific passage relied on. Required for anything quoted; strongly "
        "encouraged otherwise so a human can check the claim without fetching the source.",
    )
    locator: str = Field(default="", description="Page / section / table, for print sources.")
    retrieved_at: datetime = Field(default_factory=utcnow)

    @field_validator("doi")
    @classmethod
    def _doi_shape(cls, value: str | None) -> str | None:
        if value is not None and not _DOI_RE.match(value):
            raise ValueError(f"doi {value!r} does not look like a DOI (10.xxxx/...)")
        return value

    @field_validator("url")
    @classmethod
    def _url_shape(cls, value: str | None) -> str | None:
        if value is not None and not _URL_RE.match(value):
            raise ValueError(f"url {value!r} is not a resolvable http(s) URL")
        return value

    @model_validator(mode="after")
    def _identifiable(self) -> EvidenceRef:
        if not any((self.doi, self.url, self.locator, self.venue)):
            raise ValueError(
                f"{self.source_id}: a reference needs a DOI, URL, venue or locator — otherwise "
                "nobody can check it, and an uncheckable reference is not evidence"
            )
        if self.tier is EvidenceTier.ANECDOTAL and not self.quote:
            raise ValueError(
                f"{self.source_id}: anecdotal sources must carry the quote being relied on, "
                "so its weakness is visible to the reader"
            )
        return self


class Claim(BaseModel):
    """One assertable statement inside an insight."""

    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=8, max_length=1000)
    parameter_key: str | None = None
    value: float | None = None
    unit: str | None = None
    n: Annotated[int, Field(ge=0)] | None = None
    effect_size: float | None = Field(
        default=None, description="Pearson r for associations; signed slope for trends."
    )
    ci_low: float | None = None
    ci_high: float | None = None
    q_value: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_refs: tuple[str, ...] = Field(
        default=(), description="source_id values of the EvidenceRef entries relied on."
    )
    evidence_label: EvidenceLabel = EvidenceLabel.INSUFFICIENT_EVIDENCE
    caveats: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _label_is_honest(self) -> Claim:
        if self.evidence_label in {EvidenceLabel.SUPPORTED, EvidenceLabel.PRELIMINARY}:
            has_external = bool(self.evidence_refs)
            has_own_data = self.n is not None and self.n >= 1
            if not (has_external or has_own_data):
                raise ValueError(
                    f"claim labelled {self.evidence_label} but carries neither an evidence "
                    f"reference nor a sample size: {self.statement[:60]!r}"
                )
        if self.evidence_label is EvidenceLabel.SUPPORTED and self.n is not None and self.n < 30:
            raise ValueError(
                f"n={self.n} cannot support a SUPPORTED claim about the archer's own data — "
                "use PRELIMINARY or INSUFFICIENT_EVIDENCE (AGENTS.md rule 5)"
            )
        if self.ci_low is not None and self.ci_high is not None and self.ci_low > self.ci_high:
            raise ValueError("ci_low must be <= ci_high")
        if self.parameter_key is not None:
            from archery_agent.domain import parameters as registry

            registry.get(self.parameter_key)
        return self


class Insight(BaseModel):
    """A generated conclusion, stored with enough provenance to reproduce or retract it."""

    model_config = ConfigDict(extra="forbid")

    insight_id: str = Field(default_factory=lambda: new_id("insight"))
    run_id: str
    archer_id: str
    kind: InsightKind
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=1)
    claims: tuple[Claim, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    confidence: Confidence = Confidence.INSUFFICIENT_DATA

    # --- provenance (AGENTS.md rule 8)
    model_id: str = "none"
    prompt_version: str = "none"
    harness_version: str = "0.0.1"
    data_snapshot_hash: str = Field(
        default="", description="sha256 over the exact ledger slice used to generate this."
    )
    created_at: datetime = Field(default_factory=utcnow)
    acknowledged: bool = False

    @model_validator(mode="after")
    def _claims_are_referenced(self) -> Insight:
        available = {ref.source_id for ref in self.evidence_refs}
        for claim in self.claims:
            missing = set(claim.evidence_refs) - available
            if missing:
                raise ValueError(
                    f"claim cites unknown source_id(s) {sorted(missing)} — a reference that is "
                    "not attached to the insight is not a reference"
                )
        return self
