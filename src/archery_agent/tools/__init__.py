"""Tool layer: the only way anything outside the process can act on the system.

* ``registry`` — :class:`~archery_agent.tools.registry.ToolSpec` and the enforcing registry.
* ``impl`` — one module per namespace, each a pure-ish function plus its input model.
* ``builtin`` — assembles the default registry and the per-subagent action spaces.

The model layer never calls a function directly: it emits a tool call, the runtime validates the
arguments against the tool's input model, checks the risk level, runs the handler, and hands back
a :class:`~archery_agent.tools.registry.ToolResult`. Everything in ``docs/04-tool-contracts.md``
is a promise made by this layer.
"""

from archery_agent.tools.registry import (
    ApprovalRequiredError,
    ToolContext,
    ToolNotFoundError,
    ToolRegistry,
    ToolResult,
    ToolSpec,
)

__all__ = [
    "ApprovalRequiredError",
    "ToolContext",
    "ToolNotFoundError",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
]
