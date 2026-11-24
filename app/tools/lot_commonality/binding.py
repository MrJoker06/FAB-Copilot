"""Agent tools over the lot commonality service, exposed only on the lot_commonality route.

The tools reuse :class:`LotCommonalityService`, so an ``analysis_ref`` created by
the page API or by a tool reads back the same version through either entry.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.agent_runtime.tools.contracts import (
    ToolExecutionContext,
    ToolExecutionState,
    ToolResult,
    ToolScope,
    ToolSource,
    ToolSourceKind,
    ToolStatus,
    make_tool_error,
)
from app.agent_runtime.tools.definition import (
    ToolBinding,
    ToolDefinition,
    ToolPreparation,
)
from app.tools.lot_commonality.contracts import (
    DIMENSIONS,
    ROLES,
    LotCommonalityAccessError,
    LotCommonalityInputError,
    parse_create_request,
)
from app.tools.lot_commonality.service import (
    ANALYSIS_REF_RE,
    LotCommonalityResultError,
    LotCommonalityService,
)

CREATE_TOOL = "create_lot_commonality_analysis"
MEMBERS_TOOL = "read_lot_commonality_members"
RECORDS_TOOL = "read_lot_commonality_records"
_VERSION = "1.0.0"
_ADAPTER_ID = "lot_commonality"
_SOURCE_KINDS = {
    "sqlite": ToolSourceKind.SQLITE,
    "synthetic": ToolSourceKind.FAKE,
    "database": ToolSourceKind.DATABASE,
    "report_api": ToolSourceKind.REPORT_API,
}
# Input codes the model can act on; other input rejections share INVALID_ARGUMENTS.
_SPECIFIC_INPUT_CODES = frozenset({"ANALYSIS_LIMIT_EXCEEDED", "CUTOFF_AMBIGUOUS"})


def _arguments(arguments: object) -> dict[str, object]:
    if not isinstance(arguments, Mapping):
        raise LotCommonalityInputError("参数必须是对象。")
    return dict(arguments)


def _read_arguments(arguments: object) -> tuple[str, dict[str, object]]:
    values = _arguments(arguments)
    analysis_ref = values.pop("analysis_ref", None)
    if not isinstance(analysis_ref, str) or not ANALYSIS_REF_RE.fullmatch(analysis_ref):
        raise LotCommonalityInputError("analysis_ref 必须是已有分析引用。")
    return analysis_ref, values


def _schema(properties: dict[str, object], required: list[str]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


_ANALYSIS_REF = {"type": "string", "pattern": ANALYSIS_REF_RE.pattern}
_LIMIT = {"type": "integer", "minimum": 1, "maximum": 200}
_CURSOR = {"type": "string"}
_OFFSET_TIME = {"type": "string", "description": "带时区偏移的 ISO 时间，例如 2026-11-20T08:00:00+08:00"}
_CONDITION = {
    "type": "object",
    "description": "{candidate_id} 或 {attribute: rework, value: true/false}",
    "properties": {
        "candidate_id": {"type": "string"},
        "attribute": {"type": "string", "enum": ["rework"]},
        "value": {"type": "boolean"},
    },
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class CreateAnalysisInput:
    body: Mapping[str, object]

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]) -> CreateAnalysisInput:
        return cls(_arguments(arguments))

    @classmethod
    def json_schema(cls) -> dict[str, object]:
        group = _schema(
            {
                "group_id": {"type": "string", "pattern": "^[a-z][a-z0-9_-]{0,31}$"},
                "name": {"type": "string", "maxLength": 64},
                "role": {"type": "string", "enum": sorted(ROLES)},
                "lot_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 200},
            },
            ["group_id", "name", "role", "lot_ids"],
        )
        cutoff = {
            "type": ["object", "null"],
            "description": "异常截止；不设截止时为 null，仅用户明确要求截止时间或工序时才设置。mode=time 时给 at；mode=operation 时给 operation_key，可选 occurrence",
            "properties": {
                "mode": {"type": "string", "enum": ["time", "operation"]},
                "at": _OFFSET_TIME,
                "operation_key": {"type": "string"},
                "occurrence": {"type": "integer", "minimum": 1},
                "per_lot": {"type": "object"},
            },
            "required": ["mode"],
            "additionalProperties": False,
        }
        time_range = {
            "type": ["object", "null"],
            "description": "加工时间范围（含开始、不含结束）；不限时间时为 null",
            "properties": {"start": _OFFSET_TIME, "end": _OFFSET_TIME},
            "required": ["start", "end"],
            "additionalProperties": False,
        }
        return _schema(
            {
                "groups": {"type": "array", "items": group, "minItems": 1, "maxItems": 4},
                "dimensions": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(DIMENSIONS)},
                    "minItems": 1,
                    "uniqueItems": True,
                },
                "scope": _schema({"time_range": time_range, "cutoff": cutoff}, ["time_range", "cutoff"]),
                "timezone": {"type": "string", "description": "例如 Asia/Shanghai"},
                "description": {"type": "string"},
            },
            ["groups", "dimensions", "scope", "timezone"],
        )


@dataclass(frozen=True, slots=True)
class ReadMembersInput:
    analysis_ref: str
    query: Mapping[str, object]

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]) -> ReadMembersInput:
        return cls(*_read_arguments(arguments))

    @classmethod
    def json_schema(cls) -> dict[str, object]:
        return _schema(
            {
                "analysis_ref": _ANALYSIS_REF,
                "group_id": {"type": "string"},
                "conditions": {"type": "array", "items": _CONDITION, "minItems": 1, "maxItems": 8},
                "match_scope": {"type": "string", "enum": ["any_pass", "same_pass"]},
                "status": {"type": "string", "enum": ["hit", "miss", "unknown"]},
                "limit": _LIMIT,
                "cursor": _CURSOR,
            },
            ["analysis_ref", "group_id", "conditions"],
        )


@dataclass(frozen=True, slots=True)
class ReadRecordsInput:
    analysis_ref: str
    query: Mapping[str, object]

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]) -> ReadRecordsInput:
        return cls(*_read_arguments(arguments))

    @classmethod
    def json_schema(cls) -> dict[str, object]:
        return _schema(
            {
                "analysis_ref": _ANALYSIS_REF,
                "group_id": {"type": "string"},
                "lot_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 200},
                "candidate_id": {"type": "string"},
                "limit": _LIMIT,
                "cursor": _CURSOR,
            },
            ["analysis_ref", "group_id", "lot_ids"],
        )


def _validate_output(value: object) -> None:
    if not isinstance(value, Mapping) or not ANALYSIS_REF_RE.fullmatch(str(value.get("analysis_ref"))):
        raise ValueError("lot commonality output requires an analysis_ref")


LOT_COMMONALITY_DEFINITIONS = {
    CREATE_TOOL: ToolDefinition(
        CREATE_TOOL,
        _VERSION,
        "按用户明确给出的 lot 分组创建 Lot 共性分析：至少一个 role=primary 的主组，可加对照组；只用用户写出的 lot，不推断、不补全 lot，不生成 SQL。返回固定版本引用 analysis_ref、各组计数与排序靠前的共同设备/腔体/recipe/路径候选。用户未明确给出时间范围或异常截止时，scope.time_range 和 scope.cutoff 都必须为 null，不要自行附加截止条件。",
        CreateAnalysisInput,
        _validate_output,
        title="创建 Lot 相关性分析",
    ),
    MEMBERS_TOOL: ToolDefinition(
        MEMBERS_TOOL,
        _VERSION,
        "按 analysis_ref 回读某组在候选条件下的命中、未命中和未知成员，带精确计数与分页游标。",
        ReadMembersInput,
        _validate_output,
        title="读取 Lot 相关性成员",
    ),
    RECORDS_TOOL: ToolDefinition(
        RECORDS_TOOL,
        _VERSION,
        "按 analysis_ref 回读指定 lot 在分析范围内的原始过站记录，带分页游标。",
        ReadRecordsInput,
        _validate_output,
        title="读取 Lot 相关性过站明细",
    ),
}


@dataclass(frozen=True, slots=True)
class LotCommonalityToolDependencies:
    service: LotCommonalityService
    # Server-owned; analyses created by the tool are bound to this Session.
    session_id: str | None


def _create_scope(body: Mapping[str, object], tenant_id: str) -> ToolScope:
    request = parse_create_request(body)
    lots = sorted({lot for group in request["groups"] for lot in group["lot_ids"]})
    return ToolScope(tenant_id, lot_ids=tuple(lots))


def _prepare(input_value, context) -> ToolPreparation:
    tenant_id = context.principal.tenant_id
    if isinstance(input_value, CreateAnalysisInput):
        try:
            return ToolPreparation(input_value, _create_scope(input_value.body, tenant_id))
        except LotCommonalityInputError:
            # The handler re-validates and reports the specific rejection.
            pass
    return ToolPreparation(input_value, ToolScope(tenant_id))


def _error(context, name, status, state, code) -> ToolResult:
    return ToolResult(context.call_id, name, _VERSION, status, state, error=make_tool_error(code))


def _rejection(context, name, exc: Exception) -> ToolResult:
    not_started = ToolExecutionState.NOT_STARTED
    if isinstance(exc, LotCommonalityInputError):
        code = exc.error_code if exc.error_code in _SPECIFIC_INPUT_CODES else "INVALID_ARGUMENTS"
        return _error(context, name, ToolStatus.INVALID_ARGUMENTS, not_started, code)
    if isinstance(exc, LotCommonalityAccessError):
        return _error(context, name, ToolStatus.DENIED, not_started, "SCOPE_DENIED")
    code = exc.error_code  # type: ignore[attr-defined]
    if code == "RESULT_UNAVAILABLE":
        return _error(context, name, ToolStatus.DENIED, not_started, code)
    if code == "RESULT_CURSOR_INVALID":
        return _error(context, name, ToolStatus.INVALID_ARGUMENTS, not_started, code)
    if code == "RESULT_STORAGE_LIMIT":
        return _error(context, name, ToolStatus.BLOCKED, not_started, code)
    state = ToolExecutionState.UNKNOWN if name == CREATE_TOOL else ToolExecutionState.COMPLETED
    return _error(context, name, ToolStatus.FAILED, state, "RESULT_READ_FAILED")


def _handler(input_value, context: ToolExecutionContext[LotCommonalityToolDependencies]) -> ToolResult:
    service, principal = context.dependencies.service, context.principal
    sources: tuple[ToolSource, ...] = ()
    if isinstance(input_value, CreateAnalysisInput):
        name = CREATE_TOOL
    else:
        name = MEMBERS_TOOL if isinstance(input_value, ReadMembersInput) else RECORDS_TOOL
    try:
        if name == CREATE_TOOL:
            data = service.create(input_value.body, principal, session_id=context.dependencies.session_id)
            kind = _SOURCE_KINDS.get(str(data["source"]["kind"]), ToolSourceKind.FAKE)
            scope = _create_scope(input_value.body, principal.tenant_id)
            sources = (ToolSource(str(data["analysis_ref"]), _ADAPTER_ID, kind, scope),)
        elif name == MEMBERS_TOOL:
            data = service.members(input_value.analysis_ref, dict(input_value.query), principal)
        else:
            data = service.records(input_value.analysis_ref, dict(input_value.query), principal)
    except (LotCommonalityInputError, LotCommonalityAccessError, LotCommonalityResultError) as exc:
        return _rejection(context, name, exc)
    return ToolResult(
        context.call_id, name, _VERSION, ToolStatus.SUCCEEDED, ToolExecutionState.COMPLETED,
        data=data, sources=sources,
    )


def create_lot_commonality_bindings(
    service: LotCommonalityService, *, session_id: str | None
) -> tuple[ToolBinding, ...]:
    dependencies = LotCommonalityToolDependencies(service, session_id)
    return tuple(
        ToolBinding(definition, _handler, dependencies, _prepare)
        for definition in LOT_COMMONALITY_DEFINITIONS.values()
    )
