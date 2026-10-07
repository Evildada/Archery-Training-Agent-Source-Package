"""The tool registry: the model's only way to perceive or change the world.

Design rules (docs/04-tool-contracts.md):

* **Narrow and namespaced.** ``sim.arrow_setup``, never ``calculate()``.
* **Risk is declared, not requested.** A tool's risk level is data, and the dispatcher enforces
  it — a subagent cannot escalate by asking nicely in a prompt.
* **Uniform envelope.** Every result carries assumptions, a confidence label and provenance, so
  the orchestrator never has to guess how much to trust a number.
* **Failures are values.** A tool that raises returns ``ok=False`` with a readable reason. Stack
  traces must never enter the model's context, and silent successes must never hide a partial
  failure.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from archery_agent import HARNESS_VERSION
from archery_agent.domain.enums import Confidence, RiskLevel

JsonValue = dict[str, Any] | list[Any] | str | int | float | bool | None


class Provenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_version: str = HARNESS_VERSION
    harness_version: str = HARNESS_VERSION
    data_snapshot_hash: str = ""


class ToolResult(BaseModel):
    """The uniform result envelope — see docs/04 §10."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    data: JsonValue = None
    units: dict[str, str] = Field(default_factory=dict)
    assumptions: tuple[str, ...] = ()
    confidence: Confidence = Confidence.INSUFFICIENT_DATA
    n: int | None = None
    artifact_ref: str | None = None
    warnings: tuple[str, ...] = ()
    error: str = ""
    provenance: Provenance = Field(default_factory=Provenance)

    @classmethod
    def success(
        cls,
        data: JsonValue,
        *,
        confidence: Confidence = Confidence.MEASURED,
        units: Mapping[str, str] | None = None,
        assumptions: tuple[str, ...] = (),
        warnings: tuple[str, ...] = (),
        n: int | None = None,
        snapshot_hash: str = "",
    ) -> ToolResult:
        return cls(
            ok=True,
            data=data,
            confidence=confidence,
            units=dict(units or {}),
            assumptions=assumptions,
            warnings=warnings,
            n=n,
            provenance=Provenance(data_snapshot_hash=snapshot_hash),
        )

    @classmethod
    def failure(cls, error: str, *, warnings: tuple[str, ...] = ()) -> ToolResult:
        return cls(
            ok=False,
            error=error,
            confidence=Confidence.INSUFFICIENT_DATA,
            warnings=warnings,
        )

    def context_block(self, *, char_budget: int = 1200) -> str:
        """Compact, token-efficient rendering for the model's context."""
        if not self.ok:
            return f"ERROR: {self.error}"
        parts = [f"ok ({self.confidence.value})"]
        if self.n is not None:
            parts.append(f"n={self.n}")
        if self.units:
            parts.append("units: " + ", ".join(f"{k}={v}" for k, v in self.units.items()))
        rendered = f"{' | '.join(parts)}\n"
        rendered += str(self.data)
        if self.assumptions:
            rendered += "\nassumptions: " + "; ".join(self.assumptions)
        if self.warnings:
            rendered += "\nwarnings: " + "; ".join(self.warnings)
        if self.artifact_ref:
            rendered += f"\nfull result: {self.artifact_ref}"
        if len(rendered) > char_budget:
            rendered = (
                rendered[:char_budget] + f"\n[...truncated, full result: {self.artifact_ref}]"
            )
        return rendered


@dataclass
class ToolContext:
    """Everything a tool may know about the run it is executing inside."""

    run_id: str
    archer_id: str
    store: Any = None
    approved_tools: set[str] = field(default_factory=set)
    settings: dict[str, Any] = field(default_factory=dict)
    data_snapshot_hash: str = ""


ToolHandler = Callable[[BaseModel, ToolContext], ToolResult]


@dataclass(frozen=True)
class ToolSpec:
    """A tool's contract. ``input_model`` doubles as the JSON schema shown to the model."""

    name: str
    summary: str
    risk: RiskLevel
    input_model: type[BaseModel]
    handler: ToolHandler
    tags: tuple[str, ...] = ()
    output_hint: str = ""
    post_check: Callable[[ToolResult], tuple[str, ...]] | None = None

    @property
    def requires_approval(self) -> bool:
        return self.risk in {RiskLevel.WRITE_DRAFT, RiskLevel.PUBLISH}

    def schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()

    def prompt_stub(self) -> dict[str, Any]:
        """Compact form for the prompt: name, summary, risk, args. Full schemas load on demand."""
        return {
            "name": self.name,
            "summary": self.summary,
            "risk": self.risk.value,
            "args": {
                name: {
                    "type": field.get("type", field.get("anyOf", "object")),
                    "description": field.get("description", ""),
                }
                for name, field in self.schema().get("properties", {}).items()
            },
        }


class ToolNotFoundError(KeyError):
    def __init__(self, name: str, known: tuple[str, ...]) -> None:
        super().__init__(
            f"unknown tool {name!r}. Available: {', '.join(known)}. "
            "If the task needs something not listed, say so rather than approximating it with "
            "an unrelated tool."
        )
        self.name = name


class ApprovalRequiredError(PermissionError):
    def __init__(self, name: str) -> None:
        super().__init__(
            f"{name!r} changes durable records and requires explicit approval before it runs. "
            "Show the archer exactly what would be written, then call it again with "
            "`approved=True`."
        )


class ToolRegistry:
    """Holds the tool specs and dispatches calls with enforcement."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._denied: set[str] = set()

    # ---------------------------------------------------------------- registration
    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"tool {spec.name!r} is already registered")
        if spec.risk is RiskLevel.DENY:
            # DENY tools are documented so the model knows they exist *and are unavailable* —
            # that is more informative than pretending they do not exist.
            self._denied.add(spec.name)
            return
        self._specs[spec.name] = spec

    def register_all(self, specs: tuple[ToolSpec, ...]) -> None:
        for spec in specs:
            self.register(spec)

    def restrict_to(self, names: tuple[str, ...]) -> ToolRegistry:
        """Build a subagent's view: only these tools exist. Used by the agent dispatcher."""
        view = ToolRegistry()
        for name in names:
            if name in self._denied:
                raise ValueError(f"{name!r} is a DENY tool and can never be granted to a subagent")
            view._specs[name] = self.get(name)
        return view

    # ---------------------------------------------------------------- inspection
    def get(self, name: str) -> ToolSpec:
        if name in self._denied:
            raise PermissionError(
                f"{name!r} is permanently denied to the model layer (docs/04 §9). If the task "
                "genuinely needs it, the harness must expose a narrower, auditable tool instead."
            )
        try:
            return self._specs[name]
        except KeyError:
            raise ToolNotFoundError(name, self.names()) from None

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def denied_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._denied))

    def prompt_stubs(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._specs[name].prompt_stub() for name in self.names())

    # ---------------------------------------------------------------- dispatch
    def dispatch(
        self,
        name: str,
        arguments: Mapping[str, Any] | None,
        ctx: ToolContext,
        *,
        approved: bool = False,
    ) -> ToolResult:
        spec = self.get(name)

        if spec.requires_approval and not approved and name not in ctx.approved_tools:
            return ToolResult.failure(str(ApprovalRequiredError(name)))

        try:
            payload = spec.input_model.model_validate(dict(arguments or {}))
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in error['loc']) or '(root)'}: {error['msg']}"
                for error in exc.errors()[:6]
            )
            return ToolResult.failure(
                f"invalid arguments for {name}: {problems}. Fix the arguments rather than "
                "retrying with the same values, or ask the archer for the missing input."
            )

        try:
            result = spec.handler(payload, ctx)
        except Exception as exc:
            return ToolResult.failure(
                f"{name} raised {type(exc).__name__}: {exc}. This is a harness defect or "
                "unexpected input; report it with the arguments used rather than retrying blindly."
            )

        if spec.post_check is not None:
            extra = spec.post_check(result)
            if extra:
                result = result.model_copy(update={"warnings": (*result.warnings, *extra)})
        if not result.provenance.data_snapshot_hash:
            result = result.model_copy(
                update={
                    "provenance": result.provenance.model_copy(
                        update={"data_snapshot_hash": ctx.data_snapshot_hash}
                    )
                }
            )
        return result
