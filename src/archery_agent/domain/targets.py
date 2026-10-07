"""Target-face geometry and scoring — pure functions, no IO.

Why this is in the domain layer and not in a tool: every score, group statistic and
aim-float estimate in the product is derived from these functions. If they are wrong,
nothing above them can be right, so they are unit-tested against published ring geometry
(see ``tests/test_targets.py``).

Geometry model (compound-relevant WA faces)
-------------------------------------------
A standard WA 10-ring face is divided so that each ring is the same width. Therefore for a
face of radius ``R`` with 10 rings::

    ring_width  = R / 10
    radius(n)   = ring_width * (11 - n)      # outer radius of ring n, n in 1..10
    x_radius    = radius(10) / 2             # inner 10 (tie-break only, scores as 10)

Check for the 40 cm face (R = 20 cm): ``radius(10) = 2 cm`` -> 4 cm ten-ring, and
``radius(1) = 20 cm``. That matches the published face: rings 4 cm apart in diameter.

The 40 cm *vertical 3-spot* face is the same geometry with rings 1-5 omitted from each of
three 20 cm spots: ``radius(6) = 10 cm = spot radius``, so each spot prints rings 6-10 with
the identical 2 cm radial width, and the 10-ring is still 4 cm across — which is why the
two faces are interchangeable for scoring.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field

from archery_agent.domain.enums import Confidence

RINGS_PER_FACE: int = 10


#: Q8 (docs/07-open-questions.md, answered 2026-10-08): World Archery **compound** rules, indoor
#: 18 m on the 40 cm vertical 3-spot, outdoor 50 m on the 80 cm face, plus blank bale at any
#: distance. The 40 cm 10-ring and the 122 cm face stay implemented — they cost nothing and are
#: used for practice scoring — but they are not part of the v1 promise, and a session on them is
#: reported as out-of-scope practice rather than as a scored result.
V1_FACES: tuple[str, ...] = ("WA_40CM_3SPOT_V", "WA_80CM_10RING", "BLANK_BALE")
V1_RULESET: str = "World Archery — compound"
#: Which v1 face is shot at which v1 distance. Kept as a pair rather than two lists, because
#: "18 m on the 80 cm face" is a different session from "50 m on the 80 cm face" and the geometry
#: only allows what it allows (asserted in tests/test_domain_targets.py).
V1_FACE_AT_DISTANCE_M: dict[str, float] = {
    "WA_40CM_3SPOT_V": 18.0,
    "WA_80CM_10RING": 50.0,
}
V1_DISTANCES_M: tuple[float, ...] = tuple(V1_FACE_AT_DISTANCE_M.values())


class TargetFaceSpec(BaseModel):
    """A target face: pure geometry plus its provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    face_id: str
    name: str
    ring_width_cm: float = Field(gt=0.0, description="Radial width of one ring.")
    spot_count: int = Field(default=1, ge=1, le=3)
    spot_center_offsets_cm: tuple[float, ...] = (0.0,)
    lowest_printed_ring: int = Field(default=1, ge=1, le=10)
    is_scored: bool = True
    source: str = ""
    confidence: Confidence = Confidence.UNVERIFIED
    notes: str = ""

    @property
    def face_radius_cm(self) -> float:
        return self.ring_width_cm * RINGS_PER_FACE

    @property
    def spot_radius_cm(self) -> float:
        """Radius of one spot's printed area (equal to the face radius for single faces)."""
        return self.ring_width_cm * (11 - self.lowest_printed_ring)

    def ring_radius_cm(self, ring: int) -> float:
        """Outer radius of ``ring`` measured from the centre of the spot it belongs to."""
        if not 1 <= ring <= RINGS_PER_FACE:
            raise ValueError(f"ring must be 1..10, got {ring}")
        if ring < self.lowest_printed_ring:
            raise ValueError(
                f"ring {ring} is not printed on {self.face_id} "
                f"(lowest printed ring is {self.lowest_printed_ring})"
            )
        return self.ring_width_cm * (11 - ring)

    @property
    def x_radius_cm(self) -> float:
        """Radius of the inner 10 (X). Scores 10; used only for tie-breaks and for
        precision statistics, where it is a genuinely useful 'dead centre' measure."""
        return self.ring_radius_cm(10) / 2.0


#: Faces in scope for v1 (docs/07-open-questions.md Q8 pins the final list).
#: ``confidence`` is deliberately explicit: a face whose geometry came from a rulebook is
#: VERIFIED; a face whose spacing was inferred is not, and the simulator/scoring code must
#: say so rather than quietly averaging it into a trend.
FACES: dict[str, TargetFaceSpec] = {
    "WA_40CM_10RING": TargetFaceSpec(
        face_id="WA_40CM_10RING",
        name="WA 40 cm, 10 rings",
        ring_width_cm=2.0,
        source="WA Book 2 target-face geometry: ring widths are equal across the face; "
        "40 cm face -> 2 cm radial ring width, 4 cm ten-ring.",
        confidence=Confidence.MEASURED,
        notes="Standard 18 m indoor face.",
    ),
    "WA_40CM_3SPOT_V": TargetFaceSpec(
        face_id="WA_40CM_3SPOT_V",
        name="WA 40 cm vertical 3-spot",
        ring_width_cm=2.0,
        spot_count=3,
        # Each spot is a 20 cm diameter face (rings 6-10) stacked vertically. Centres are
        # 20 cm apart: three 20 cm spots + ~2.75 cm margin top and bottom fit the published
        # 21.5 x 65.5 cm paper size. Spacing is DERIVED, not read from a rulebook — hence
        # UNVERIFIED below, and it must be confirmed before it is used for scoring decisions.
        spot_center_offsets_cm=(-20.0, 0.0, 20.0),
        lowest_printed_ring=6,
        source="Spot diameter and ring geometry follow the 40 cm 10-ring face (rings 1-5 "
        "omitted). Centre spacing derived from the published 21.5 x 65.5 cm paper size.",
        confidence=Confidence.UNVERIFIED,
        notes="Centre spacing pending confirmation against the governing rulebook "
        "(docs/07-open-questions.md Q8). Ring geometry within a spot is verified.",
    ),
    "WA_80CM_10RING": TargetFaceSpec(
        face_id="WA_80CM_10RING",
        name="WA 80 cm, 10 rings",
        ring_width_cm=4.0,
        source="WA Book 2 target-face geometry: equal ring widths; 80 cm face -> 4 cm radial "
        "ring width, 8 cm ten-ring.",
        confidence=Confidence.MEASURED,
        notes="50 m outdoor compound face.",
    ),
    "WA_122CM_10RING": TargetFaceSpec(
        face_id="WA_122CM_10RING",
        name="WA 122 cm, 10 rings",
        ring_width_cm=6.1,
        source="WA Book 2: 122 cm face, equal ring widths (12.2 cm ten-ring).",
        confidence=Confidence.MEASURED,
        notes="Kept for completeness/import only — not part of the v1 compound workflow.",
    ),
    "BLANK_BALE": TargetFaceSpec(
        face_id="BLANK_BALE",
        name="Blank bale (no scoring)",
        ring_width_cm=20.0,
        is_scored=False,
        source="Training construct: form work with no target.",
        confidence=Confidence.MEASURED,
        notes="Shots are recorded but never scored; outcome parameters must be absent.",
    ),
}


class RingHit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    face_id: str
    spot_index: int | None = None
    ring: int | None = Field(default=None, description="None = miss, or unscored face.")
    is_x: bool = False
    radius_cm: float = Field(ge=0.0)

    @property
    def score_value(self) -> int:
        if self.ring is None:
            return 0
        return self.ring


def get_face(face_id: str) -> TargetFaceSpec:
    try:
        return FACES[face_id]
    except KeyError:
        raise ValueError(
            f"unknown target face {face_id!r}; known faces: {sorted(FACES)}. "
            "A custom face must be registered in domain/targets.py with its geometry."
        ) from None


def ring_for_offset(
    face_id: str,
    horizontal_offset_cm: float,
    vertical_offset_cm: float,
) -> RingHit:
    """Convert a signed impact offset (x right positive, y up positive) into a ring.

    For multi-spot faces the nearest spot is selected first; an impact that lands in the
    space *between* spots is a miss, which is the correct behaviour for 3-spot scoring and
    is exactly the mistake a naive Euclidean-distance implementation makes.
    """
    face = get_face(face_id)
    if not face.is_scored:
        raise ValueError(
            f"{face_id} is not a scored face — a hit on a blank bale has no ring. "
            "Leave scoring fields empty for this mode."
        )

    if face.spot_count == 1:
        spot_index: int | None = 0
        local_x, local_y = horizontal_offset_cm, vertical_offset_cm
    else:
        distances = [
            (math.hypot(horizontal_offset_cm, vertical_offset_cm - cy), i)
            for i, cy in enumerate(face.spot_center_offsets_cm)
        ]
        _, spot_index = min(distances)
        local_y = vertical_offset_cm - face.spot_center_offsets_cm[spot_index]
        local_x = horizontal_offset_cm

    radius = math.hypot(local_x, local_y)

    if radius > face.spot_radius_cm:
        return RingHit(face_id=face_id, spot_index=spot_index, ring=None, radius_cm=radius)

    # Iterate from the innermost ring outwards and take the first match: the highest-scoring
    # ring the impact falls inside. (Iterating outwards-to-inwards returns ring 1 for every
    # good shot, which is the kind of bug that only shows up when a real score card is compared.)
    for ring in range(RINGS_PER_FACE, face.lowest_printed_ring - 1, -1):
        if radius <= face.ring_radius_cm(ring):
            return RingHit(
                face_id=face_id,
                spot_index=spot_index,
                ring=ring,
                is_x=radius <= face.x_radius_cm,
                radius_cm=radius,
            )
    # radius <= spot_radius but larger than the outermost printed ring is impossible given
    # ring_radius_cm(lowest_printed_ring) == spot_radius_cm; kept as an explicit guard.
    return RingHit(face_id=face_id, spot_index=spot_index, ring=None, radius_cm=radius)


def max_range_m(face_id: str) -> float | None:
    """Sanity bound for the face's intended distance, used by the capture sensors."""
    return {
        "WA_40CM_10RING": 25.0,
        "WA_40CM_3SPOT_V": 25.0,
        "WA_80CM_10RING": 60.0,
        "WA_122CM_10RING": 90.0,
        "BLANK_BALE": 30.0,
    }.get(face_id)
