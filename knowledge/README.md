# Knowledge Corpus

The only place a factual claim about archery, biomechanics or sport psychology may come from.

**Current state: empty.** That is deliberate, not unfinished. Every entry must be checked by a
human against the actual source, because a plausible-looking fabricated citation is worse than no
citation at all: it launders an invented claim into a trustworthy-looking one. Until the corpus
is populated (milestone M4), `knowledge.search` fails loudly and the agent is instructed to say
*"I don't have a sourced answer for that"* rather than answering from memory.

## Format

One JSON object per line in `knowledge/sources/*.jsonl`:

```json
{"ref": {"source_id": "smith2021holdtime",
         "title": "Hold duration and score in compound archery",
         "author": "Smith, J.; Lee, A.",
         "year": 2021,
         "venue": "Journal of Sports Sciences",
         "doi": "10.1234/jss.2021.0042",
         "url": null,
         "tier": "peer_reviewed",
         "quote": "Mean hold duration was positively associated with score (r = .34, n = 61).",
         "locator": "p. 412"},
 "topics": ["hold_time", "cycle_timing"],
 "body": "Extracted passage text used for lexical search."}
```

Field rules the schema enforces:

* **a way to check it** — a DOI, URL, venue or page locator must be present;
* **a quote** for anything anecdotal, and strongly encouraged otherwise;
* **a tier** — one of `peer_reviewed`, `coaching_consensus`, `manufacturer_doc`, `anecdotal`.
  The tier is shown to the archer with every claim. Peer-reviewed is required for anything about
  injury, psychology or physiology.

## Tier policy

| Tier | May be used for | May not be used for |
| --- | --- | --- |
| `peer_reviewed` | anything, including sensitive topics | — |
| `coaching_consensus` | technique and training practice | injury, psychology, physiology |
| `manufacturer_doc` | equipment specification and tuning | technique effectiveness claims |
| `anecdotal` | illustration, hypothesis generation | any claim presented as evidence |

## Topic tags in use

`target_panic`, `routine`, `hold_time`, `cycle_timing`, `release_technique`, `aiming`,
`arrow_setup`, `spine`, `bow_setup`, `fletching`, `physical_preparation`, `load_management`,
`competition_preparation`, `psychology_arousal`, `youth_development`, `injury_prevention`.

## Why no vector database (yet)

The corpus is small and curated, so term-overlap search is both sufficient and **auditable** — a
reviewer can see exactly why a source surfaced. Embeddings would retrieve a source whose *topic*
matches while its *claim* does not, which is precisely the failure this system cannot afford. The
decision is revisited at M4 or above ~500 documents, whichever comes first.
