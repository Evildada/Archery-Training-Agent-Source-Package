"""AI Archery Assistant — a harness-engineered training agent for compound archery.

Layering (enforced by `.importlinter`, see `docs/01-harness-architecture.md`):

    domain < sim < sensors < store < tools < agents < runtime < interfaces

Nothing in this package calls a model provider outside `archery_agent.runtime`.
"""

from __future__ import annotations

__version__ = "0.0.1"

HARNESS_VERSION = "0.0.1"
PROMPT_VERSION = "none"  # becomes a real version at milestone M3 (docs/06-roadmap.md)

__all__ = ["HARNESS_VERSION", "PROMPT_VERSION", "__version__"]
