"""Target-face geometry. Every score and group statistic in the product depends on this module."""

from __future__ import annotations

import pytest

from archery_agent.domain.targets import (
    FACES,
    V1_FACE_AT_DISTANCE_M,
    V1_FACES,
    get_face,
    max_range_m,
    ring_for_offset,
)


def test_ring_radii_match_published_geometry() -> None:
    face = get_face("WA_40CM_10RING")
    assert face.ring_radius_cm(10) == pytest.approx(2.0)  # 4 cm ten-ring
    assert face.ring_radius_cm(1) == pytest.approx(20.0)  # 40 cm face
    assert face.x_radius_cm == pytest.approx(1.0)  # 2 cm inner ten

    big = get_face("WA_80CM_10RING")
    assert big.ring_radius_cm(10) == pytest.approx(4.0)  # 8 cm ten-ring
    assert big.ring_radius_cm(1) == pytest.approx(40.0)


def test_scoring_boundaries_are_inclusive_of_the_inner_ring() -> None:
    assert ring_for_offset("WA_40CM_10RING", 0.0, 0.0).ring == 10
    assert ring_for_offset("WA_40CM_10RING", 1.9, 0.0).ring == 10
    assert ring_for_offset("WA_40CM_10RING", 2.0, 0.0).ring == 10, "on the line scores the higher"
    assert ring_for_offset("WA_40CM_10RING", 2.1, 0.0).ring == 9
    assert ring_for_offset("WA_40CM_10RING", 19.9, 0.0).ring == 1
    assert ring_for_offset("WA_40CM_10RING", 20.1, 0.0).ring is None, "outside the face is a miss"


def test_inner_ten_detection() -> None:
    assert ring_for_offset("WA_40CM_10RING", 1.0, 0.0).is_x is True
    assert ring_for_offset("WA_40CM_10RING", 1.5, 0.0).is_x is False


def test_three_spot_uses_the_same_ring_width_as_the_single_face() -> None:
    spot = get_face("WA_40CM_3SPOT_V")
    single = get_face("WA_40CM_10RING")
    assert spot.ring_width_cm == single.ring_width_cm
    assert spot.lowest_printed_ring == 6
    assert spot.spot_radius_cm == pytest.approx(10.0)


def test_three_spot_selects_the_nearest_spot() -> None:
    centre = ring_for_offset("WA_40CM_3SPOT_V", 0.0, 0.0)
    assert centre.spot_index == 1
    assert centre.ring == 10 and centre.is_x

    upper = ring_for_offset("WA_40CM_3SPOT_V", 0.0, 20.0)
    assert upper.spot_index == 2 and upper.ring == 10

    lower = ring_for_offset("WA_40CM_3SPOT_V", 0.0, -20.0)
    assert lower.spot_index == 0 and lower.ring == 10


def test_impact_outside_every_spot_is_a_miss() -> None:
    """The classic naive-implementation bug: Euclidean distance from the face centre.

    On the vertical 3-spot the spots touch, so there is no vertical gap to fall into; the miss
    that matters is an impact that is inside the 40 cm face but outside every 20 cm spot.
    """
    hit = ring_for_offset("WA_40CM_3SPOT_V", 15.0, 10.0)
    assert hit.ring is None, "inside the face but outside every spot is a miss"
    assert hit.radius_cm > 10.0


def test_impact_exactly_between_two_spots_is_deterministic() -> None:
    """The tangent point belongs to two spots at once; the choice must be stable, not random."""
    first = ring_for_offset("WA_40CM_3SPOT_V", 0.0, 10.0)
    second = ring_for_offset("WA_40CM_3SPOT_V", 0.0, 10.0)
    assert first == second
    assert first.ring == 6, "the tangent point is on the outer ring of the nearest spot"


def test_unscored_face_refuses_to_score() -> None:
    with pytest.raises(ValueError, match="not a scored face"):
        ring_for_offset("BLANK_BALE", 0.0, 0.0)


def test_unknown_face_error_lists_known_faces() -> None:
    with pytest.raises(ValueError, match="WA_40CM_10RING"):
        get_face("MY_HOMEMADE_FACE")


def test_every_face_declares_provenance() -> None:
    for face_id, face in FACES.items():
        assert face.source, f"{face_id} has no documented source"
        assert max_range_m(face_id) is not None


def test_unverified_face_is_flagged_as_such() -> None:
    """The 3-spot spacing is derived, not read from a rulebook — and the type says so."""
    from archery_agent.domain.enums import Confidence

    assert get_face("WA_40CM_3SPOT_V").confidence is Confidence.UNVERIFIED
    assert get_face("WA_40CM_10RING").confidence is Confidence.MEASURED


def test_v1_faces_cover_the_v1_distances() -> None:
    """Q8: 18 m on the 40 cm 3-spot, 50 m on the 80 cm face.

    The point of this test is the *interaction*: the face's own range limit must reach the
    distance it is shot at in v1. A geometry table and a ruleset that disagree is exactly the
    kind of quiet inconsistency that turns into wrong scores.
    """
    assert V1_FACE_AT_DISTANCE_M == {"WA_40CM_3SPOT_V": 18.0, "WA_80CM_10RING": 50.0}
    for face_id, distance in V1_FACE_AT_DISTANCE_M.items():
        assert face_id in V1_FACES
        reach = max_range_m(face_id)
        assert reach is not None, f"{face_id} has no rating but is shot at {distance} m in v1"
        assert reach >= distance, (
            f"{face_id} is rated to {reach} m but v1 shoots it at {distance} m"
        )
