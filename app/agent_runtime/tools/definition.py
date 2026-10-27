"""Small, dependency-free definitions for the next tool runtime.

These types deliberately do not register tools or execute policies.  They give
consumer-owned inputs one authoritative parser and schema until MOD-006 joins
them to the legacy runtime.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from .contracts import ToolExecutionContext, ToolResult, ToolScope


class ToolInputModel(Protocol):
    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]) -> ToolInputModel: ...

    @classmethod
    def json_schema(cls) -> dict[str, object]: ...


InputT = TypeVar("InputT", bound=ToolInputModel)
DepsT = TypeVar("DepsT")
DataT = TypeVar("DataT")
ToolHandler = Callable[[InputT, ToolExecutionContext[DepsT]], ToolResult[DataT]]
OutputValidator = Callable[[object], object]
ToolPrepare = Callable[[InputT, ToolExecutionContext[DepsT]], "ToolPreparation[InputT]"]


@dataclass(frozen=True, slots=True)
class ToolPreparation(Generic[InputT]):
    """Validated native input together with the exact server-authorized scope."""

    input_value: InputT
    scope: ToolScope

    def __post_init__(self) -> None:
        if not isinstance(self.scope, ToolScope):
            raise TypeError("tool preparation requires a ToolScope")


@dataclass(frozen=True, slots=True)
class ToolDefinition(Generic[InputT]):
    name: str
    version: str
    description: str
    input_model: type[InputT]
    output_validator: OutputValidator
    read_only: bool = True

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.name, self.version, self.description)
        ):
            raise ValueError("tool definition metadata must be non-empty strings")
        if not callable(
            getattr(self.input_model, "from_arguments", None)
        ) or not callable(getattr(self.input_model, "json_schema", None)):
            raise TypeError("input_model must provide from_arguments and json_schema")
        if not callable(self.output_validator) or not isinstance(self.read_only, bool):
            raise TypeError("tool definition requires a validator and bool read_only")

    def parse(self, arguments: Mapping[str, object]) -> InputT:
        return self.input_model.from_arguments(arguments)  # type: ignore[return-value]

    def json_schema(self) -> dict[str, object]:
        return self.input_model.json_schema()


@dataclass(frozen=True, slots=True)
class ToolBinding(Generic[InputT, DepsT, DataT]):
    definition: ToolDefinition[InputT]
    handler: ToolHandler[InputT, DepsT, DataT]
    dependencies: DepsT
    prepare: ToolPrepare[InputT, DepsT] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.definition, ToolDefinition) or not callable(
            self.handler
        ):
            raise TypeError("tool binding requires a definition and handler")
        if self.prepare is not None and not callable(self.prepare):
            raise TypeError("tool binding prepare must be callable or None")
