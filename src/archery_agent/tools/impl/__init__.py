"""Tool implementations, grouped by namespace.

Every handler is a thin adapter: it validates the arguments, calls a deterministic function in
``sim``/``sensors``/``domain``, and packages the answer in a
:class:`~archery_agent.tools.registry.ToolResult`. Business logic does not live here — if a
handler grows a calculation, that calculation belongs one layer down where it can be unit-tested
without a tool context.
"""

from __future__ import annotations
