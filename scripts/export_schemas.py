#!/usr/bin/env python
"""Export JSON Schemas for every persisted domain type and every tool input.

Why this exists as a *sensor* rather than a convenience script:

* the schemas are the contract between the ledger, the tools and (later) an HTTP surface;
* a schema that drifts from the code silently breaks consumers, so CI runs
  ``--check`` and fails on any difference;
* reading the schemas is the fastest way for a human — or a coding agent — to understand what
  the system actually accepts, without reading eleven pydantic modules.

Usage::

    python scripts/export_schemas.py           # write schemas/
    python scripts/export_schemas.py --check   # fail if schemas/ is out of date
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from archery_agent.domain.entities import (
    Archer,
    ArrowSetup,
    Bow,
    CycleTemplate,
    End,
    EndStats,
    Environment,
    EquipmentSet,
    ProfileChange,
    Release,
    Session,
    ShooterProfile,
    Shot,
)
from archery_agent.domain.equipment import (
    EquipmentChange,
    EquipmentSnapshot,
    EquipmentVersion,
)
from archery_agent.domain.insight import Claim, EvidenceRef, Insight
from archery_agent.domain.ledger import ObservationBatch, ParameterObservation
from archery_agent.domain.parameters import ParameterDefinition
from archery_agent.domain.standards import (
    Dose,
    PracticeInstruction,
    Standard,
    StandardEvaluation,
)
from archery_agent.runtime.events import Event
from archery_agent.runtime.loop import PlannerDecision, TurnResult
from archery_agent.sensors.setup_assessment import Experiment, Finding, SetupReport
from archery_agent.tools.impl.equipment_tools import (
    EquipmentAssessInput,
    EquipmentHistoryInput,
    EquipmentRecordInput,
)
from archery_agent.tools.impl.guard_tools import TextInput
from archery_agent.tools.impl.knowledge_tools import KnowledgeSearchInput
from archery_agent.tools.impl.ledger_tools import (
    LedgerAppendInput,
    LedgerReadInput,
    LedgerSummaryInput,
    StatsEffectsInput,
    StatsTrendInput,
)
from archery_agent.tools.impl.sim_tools import (
    ArrowSetupInput,
    SightMarkInput,
    SpineCheckInput,
    TuneAdviceInput,
)
from archery_agent.tools.impl.standards_tools import (
    InstructionDraftInput,
    StandardDraftInput,
    StandardEvaluateInput,
    StandardSuggestInput,
)
from archery_agent.tools.registry import ToolResult

SCHEMA_ROOT = Path("schemas")

MODELS: tuple[type[Any], ...] = (
    # domain
    Archer,
    EquipmentVersion,
    EquipmentChange,
    EquipmentSnapshot,
    ShooterProfile,
    ProfileChange,
    Bow,
    Release,
    ArrowSetup,
    EquipmentSet,
    CycleTemplate,
    Session,
    Environment,
    End,
    Shot,
    EndStats,
    ParameterDefinition,
    ParameterObservation,
    ObservationBatch,
    Standard,
    StandardEvaluation,
    PracticeInstruction,
    Dose,
    EvidenceRef,
    Claim,
    Insight,
    EquipmentVersion,
    EquipmentChange,
    EquipmentSnapshot,
    Finding,
    Experiment,
    SetupReport,
    # runtime
    Event,
    TurnResult,
    PlannerDecision,
    ToolResult,
    # tool inputs
    LedgerAppendInput,
    LedgerReadInput,
    LedgerSummaryInput,
    StatsEffectsInput,
    StatsTrendInput,
    ArrowSetupInput,
    SpineCheckInput,
    SightMarkInput,
    TuneAdviceInput,
    StandardSuggestInput,
    StandardDraftInput,
    StandardEvaluateInput,
    InstructionDraftInput,
    KnowledgeSearchInput,
    EquipmentRecordInput,
    EquipmentHistoryInput,
    EquipmentAssessInput,
    TextInput,
)


def build_schemas() -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    for model in MODELS:
        name = model.__name__
        if name in schemas:
            raise RuntimeError(f"two models share the name {name!r}: schema file collision")
        schema = model.model_json_schema(mode="validation")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["title"] = name
        schemas[f"{name}.json"] = schema
    return schemas


def write_schemas(schemas: dict[str, dict[str, Any]]) -> list[str]:
    SCHEMA_ROOT.mkdir(exist_ok=True)
    written: list[str] = []
    for filename, schema in sorted(schemas.items()):
        path = SCHEMA_ROOT / filename
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(filename)
    return written


def check_schemas(schemas: dict[str, dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    for filename, schema in sorted(schemas.items()):
        path = SCHEMA_ROOT / filename
        expected = json.dumps(schema, indent=2, sort_keys=True) + "\n"
        if not path.exists():
            problems.append(f"missing: {filename}")
        elif path.read_text(encoding="utf-8") != expected:
            problems.append(f"out of date: {filename}")
    known = set(schemas)
    if SCHEMA_ROOT.exists():
        for path in sorted(SCHEMA_ROOT.glob("*.json")):
            if path.name not in known:
                problems.append(f"stale (no longer generated): {path.name}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if schemas/ is out of date")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    schemas = build_schemas()
    if args.check:
        problems = check_schemas(schemas)
        if problems:
            print("schema drift detected:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            print("\nRun `make schemas` and commit the result.", file=sys.stderr)
            return 1
        if not args.quiet:
            print(f"schemas up to date ({len(schemas)} files)")
        return 0

    written = write_schemas(schemas)
    if not args.quiet:
        print(f"wrote {len(written)} schema files to {SCHEMA_ROOT}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
