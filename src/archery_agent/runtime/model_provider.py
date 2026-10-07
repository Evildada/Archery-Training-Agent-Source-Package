"""The model boundary — the only place a provider SDK may be imported (llm-isolation contract).

Nothing above this file knows which model is in use, and nothing below it cares. The provider
interface is intentionally small: messages in, text plus tool calls out, with usage reported.
Anything richer (streaming, reasoning traces, provider-specific caching) is added here and
nowhere else.

M0 ships :class:`NullProvider`, which refuses with instructions. That is not a placeholder for
laziness: the entire deterministic spine — schemas, sensors, simulator, ledger, standards, the
loop itself — runs and is tested with no provider configured, which is what keeps the eval
suites honest once a model *is* attached.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None
    name: str | None = None


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    input_tokens: int = 0
    output_tokens: int = 0
    model_id: str = "unknown"
    finish_reason: str = "stop"

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ModelNotConfiguredError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "no model provider is configured. The deterministic harness runs without one "
            "(`make demo`). To enable model-driven turns, set the provider in "
            "runtime/model_provider.py behind the ARCHERY_MODEL_* environment variables "
            "(see .env.example and docs/07-open-questions.md Q4)."
        )


@runtime_checkable
class ModelProvider(Protocol):
    """What the loop requires. Deliberately minimal."""

    name: str

    def complete(
        self,
        messages: list[Message],
        *,
        tools: tuple[dict[str, Any], ...] = (),
        temperature: float = 0.0,
        max_output_tokens: int | None = None,
    ) -> ModelResponse: ...


class NullProvider:
    """Default provider: refuses, with instructions, instead of pretending to think."""

    name = "none"

    def complete(
        self,
        messages: list[Message],
        *,
        tools: tuple[dict[str, Any], ...] = (),
        temperature: float = 0.0,
        max_output_tokens: int | None = None,
    ) -> ModelResponse:
        del messages, tools, temperature, max_output_tokens
        raise ModelNotConfiguredError


class ScriptedProvider:
    """Replays a fixed script. Used by tests and by the deterministic demo.

    A scripted provider is not a mock of a model — it is a *fixed plan*, which is exactly what
    makes a full-loop test possible before any model exists.
    """

    name = "scripted"

    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[Message]] = []

    def complete(
        self,
        messages: list[Message],
        *,
        tools: tuple[dict[str, Any], ...] = (),
        temperature: float = 0.0,
        max_output_tokens: int | None = None,
    ) -> ModelResponse:
        del tools, temperature, max_output_tokens
        self.calls.append(list(messages))
        if not self._responses:
            raise ModelNotConfiguredError
        return self._responses.pop(0)
