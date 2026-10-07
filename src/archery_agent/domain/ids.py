"""Identifier helpers. Ids are prefixed by entity so a stray id is self-describing in logs."""

from __future__ import annotations

import uuid

PREFIXES: dict[str, str] = {
    "archer": "arc_",
    "equipment": "equ_",
    "bow": "bow_",
    "release": "rel_",
    "arrow": "arr_",
    "template": "tmpl_",
    "session": "sess_",
    "end": "end_",
    "shot": "shot_",
    "observation": "obs_",
    "standard": "std_",
    "evaluation": "stdv_",
    "insight": "ins_",
    "run": "run_",
    "plan": "plan_",
}


def new_id(entity: str) -> str:
    """``new_id("session") -> "sess_1f0c..."``."""
    try:
        prefix = PREFIXES[entity]
    except KeyError:
        raise ValueError(
            f"unknown entity {entity!r} for id generation; known: {sorted(PREFIXES)}"
        ) from None
    return f"{prefix}{uuid.uuid4().hex[:16]}"
