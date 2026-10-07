"""The eval gates and the CLI are part of `make check`, so they are tested like everything else.

A gate that only runs in CI is a gate nobody notices going red locally; a gate that runs in the
test suite is one that fails in the same command the author already runs.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from archery_agent.interfaces.cli import main

EVAL_RUNNER = Path("scripts/run_evals.py")


@pytest.mark.parametrize(
    "suite",
    ["safety", "numeric_grounding", "claim_labels", "routing", "standards_executability"],
)
def test_eval_suite_passes_its_gate(suite: str) -> None:
    sys.path.insert(0, str(EVAL_RUNNER.parent))
    import run_evals  # type: ignore[import-not-found]

    results = run_evals.run_all([suite])
    result = results[0]
    failures = [case for case in result.cases if not case.passed]
    assert result.ok, (
        f"{suite} scored {result.score:.3f} against a gate of {result.gate:.2f}. "
        + "; ".join(f"{case.case_id}: {case.detail}" for case in failures)
    )


def test_eval_fixtures_contain_negative_cases() -> None:
    """A suite without negative fixtures measures nothing."""
    from archery_agent.domain.enums import EvidenceLabel

    sys.path.insert(0, str(EVAL_RUNNER.parent))
    import run_evals  # type: ignore[import-not-found]

    grounding = run_evals.load_fixture("numeric_grounding.jsonl")
    assert any(case["expect_pass"] is False for case in grounding)

    claims = run_evals.load_fixture("claim_labels.jsonl")
    assert any(case["expect"] == EvidenceLabel.INSUFFICIENT_EVIDENCE.value for case in claims)

    standards = run_evals.load_fixture("standards.jsonl")
    assert any(case["expect"] == "rejected" for case in standards)

    red_team = run_evals.load_fixture("red_team.jsonl")
    assert any(case["expect"] == "refer" for case in red_team)
    assert any(case["expect"] == "proceed" for case in red_team)


def test_eval_runner_exits_zero() -> None:
    completed = subprocess.run(
        [sys.executable, str(EVAL_RUNNER), "--no-write"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "PASS" in completed.stdout


# ---------------------------------------------------------------------- CLI


def test_cli_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["version"]) == 0
    assert "archery-agent" in capsys.readouterr().out


def test_cli_params_lists_registry(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["params", "--brief", "--category", "cycle_timing"]) == 0
    out = capsys.readouterr().out
    assert "cycle.hold_time_s" in out
    assert "outcome.score_mean" not in out, "category filter must actually filter"


def test_cli_params_core_shows_the_mandatory_set(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["params", "--core", "--brief"]) == 0
    out = capsys.readouterr().out
    assert "11 parameter(s) registered" in out
    assert "cycle.hold_time_s" in out
    assert "bow.cam_timing_offset_in" not in out, "the mandatory set is not the whole registry"


def test_cli_doctor_reports_no_failures(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "[PASS] parameter registry" in out
    assert "checks passed" in out


def test_cli_demo_runs_a_full_turn(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["demo", "--sessions", "10"]) == 0
    out = capsys.readouterr().out
    assert "DETERMINISTIC DEMO" in out
    assert "answer gate : passed" in out
    assert "no model was called" in out


def test_cli_simulate_prints_assumptions(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "simulate",
            "--draw-weight",
            "55",
            "--draw-length",
            "28.5",
            "--length",
            "28",
            "--shaft-mass",
            "180",
            "--point-mass",
            "100",
            "--insert-mass",
            "15",
            "--nock-mass",
            "10",
            "--vane-mass",
            "12",
            "--ibo",
            "315",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "FOC" in out
    assert "assumptions:" in out
    assert "fps/lb" in out


# ------------------------------------------------------- M1: equipment + setup report


def _run_cli(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, str]:
    from archery_agent.interfaces.cli import main as cli_main

    code = cli_main(argv)
    return code, capsys.readouterr().out


def test_equipment_cli_prints_a_test_for_every_estimate(
    tmp_path: pytest.TempPathFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    db = str(tmp_path / "archery.db")  # type: ignore[operator]
    code, _ = _run_cli(
        capsys,
        [
            "equipment",
            "record",
            "--archer",
            "arc_cli",
            "--db",
            db,
            "--bow-brand",
            "Test",
            "--bow-model",
            "Riser",
            "--draw-weight",
            "55",
            "--draw-length",
            "28.5",
            "--arrow-brand",
            "Easton",
            "--arrow-model",
            "X10",
            "--spine",
            "340",
            "--length",
            "28.5",
            "--shaft-mass",
            "180",
        ],
    )
    assert code == 0

    code, out = _run_cli(capsys, ["equipment", "assess", "--archer", "arc_cli", "--db", db])
    assert code == 0
    assert "[estimated]" in out or "[unverified]" in out
    assert "grain scale" in out, "the weighing test must be in the archer's output"
    assert "Not answerable yet" in out


def test_assessing_without_a_recorded_setup_refuses_to_invent_one(
    tmp_path: pytest.TempPathFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    db = str(tmp_path / "empty.db")  # type: ignore[operator]
    code, out = _run_cli(capsys, ["equipment", "assess", "--archer", "arc_none", "--db", db])
    assert code == 1
    assert "no equipment recorded" in out.lower() or "Nothing to assess" in out


def test_history_shows_the_delta_between_versions(
    tmp_path: pytest.TempPathFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    db = str(tmp_path / "archery.db")  # type: ignore[operator]
    base = [
        "equipment",
        "record",
        "--archer",
        "arc_hist",
        "--db",
        db,
        "--bow-brand",
        "Test",
        "--bow-model",
        "Riser",
        "--arrow-brand",
        "Easton",
        "--arrow-model",
        "X10",
        "--spine",
        "340",
        "--length",
        "28.5",
        "--shaft-mass",
        "180",
    ]
    assert _run_cli(capsys, [*base, "--point-mass", "100"])[0] == 0
    assert _run_cli(capsys, [*base, "--point-mass", "125", "--reason", "heavier point"])[0] == 0

    code, out = _run_cli(capsys, ["equipment", "history", "--archer", "arc_hist", "--db", db])
    assert code == 0
    assert "v1" in out and "v2" in out
    assert "+25.00" in out, "the signed delta is the change-point the later regression needs"
    assert "heavier point" in out
