"""Conversions and group statistics — hand-checked values, not self-referential ones.

The kinetic-energy constant in particular is worth pinning: it is the number most often quoted
loosely in archery ("KE = mass x speed squared divided by 450,000"), and a formula that is
approximately right is exactly the kind of thing that never gets caught by a round-trip test.
"""

from __future__ import annotations

import pytest

from archery_agent.domain.units import (
    cm_to_in,
    fps_to_mps,
    grains_to_grams,
    group_center_cm,
    group_radius_cm,
    in_to_cm,
    joules_to_ft_lb,
    kg_to_lb,
    kinetic_energy_ft_lb,
    kinetic_energy_joules,
    lb_to_kg,
    momentum_lb_s,
    mps_to_fps,
)


def test_length_conversions() -> None:
    assert in_to_cm(1.0) == pytest.approx(2.54)
    assert cm_to_in(2.54) == pytest.approx(1.0)
    assert cm_to_in(in_to_cm(27.5)) == pytest.approx(27.5)


def test_mass_conversions() -> None:
    assert lb_to_kg(1.0) == pytest.approx(0.45359237)
    assert kg_to_lb(lb_to_kg(55.0)) == pytest.approx(55.0)
    assert grains_to_grams(7000.0) == pytest.approx(453.59237, rel=1e-6)


def test_speed_conversions() -> None:
    assert fps_to_mps(300.0) == pytest.approx(91.44)
    assert mps_to_fps(fps_to_mps(285.0)) == pytest.approx(285.0)


def test_kinetic_energy_matches_hand_calculation() -> None:
    # 300 gr at 300 fps: 300 * 300^2 / (2 * 7000 * 32.17405) = 59.94 ft·lb
    assert kinetic_energy_ft_lb(300.0, 300.0) == pytest.approx(59.94, abs=0.01)
    # and the commonly quoted rounded constant differs by ~0.04 %, which is why we do not use it
    rounded = 300.0 * 300.0**2 / 450_240.0
    assert rounded == pytest.approx(59.97, abs=0.01)
    assert rounded != pytest.approx(kinetic_energy_ft_lb(300.0, 300.0), abs=0.001)


def test_kinetic_energy_in_joules() -> None:
    assert kinetic_energy_joules(300.0, 300.0) == pytest.approx(81.26, abs=0.05)
    assert joules_to_ft_lb(kinetic_energy_joules(300.0, 300.0)) == pytest.approx(
        kinetic_energy_ft_lb(300.0, 300.0)
    )


def test_momentum_is_in_lb_ft_per_s() -> None:
    assert momentum_lb_s(300.0, 300.0) == pytest.approx(0.3997, abs=0.001)


def test_negative_inputs_are_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        kinetic_energy_ft_lb(-1.0, 300.0)
    with pytest.raises(ValueError, match="non-negative"):
        momentum_lb_s(300.0, -5.0)


def test_group_radius_measures_precision_not_accuracy() -> None:
    """A tight group far from the centre has a small radius — that is the definition."""
    tight_but_offset = [(10.0, 10.0), (10.0, 12.0), (12.0, 10.0), (12.0, 12.0)]
    assert group_radius_cm(tight_but_offset) == pytest.approx(1.4142, abs=0.001)
    assert group_center_cm(tight_but_offset) == pytest.approx((11.0, 11.0))


def test_group_radius_rejects_an_empty_group() -> None:
    with pytest.raises(ValueError, match="zero shots"):
        group_radius_cm([])
