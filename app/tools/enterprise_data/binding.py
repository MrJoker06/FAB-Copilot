"""Unregistered native definitions for enterprise data tools."""

from __future__ import annotations

from app.agent_runtime.tools.contracts import ToolExecutionContext
from app.agent_runtime.tools.definition import (
    ToolBinding,
    ToolDefinition,
    ToolPreparation,
)
from app.tools.enterprise_data.contracts import (
    ENTERPRISE_OUTPUT_SCHEMAS,
    EnterpriseDataPort,
    EnterpriseManifestInput,
    EnterpriseSampleInput,
    EnterpriseSummaryInput,
    EnterpriseWindow,
    enterprise_scope,
    validate_enterprise_manifest_output,
    validate_enterprise_sample_output,
    validate_enterprise_summary_output,
)
from app.tools.enterprise_data.handler import (
    EnterpriseToolsDependencies,
    enterprise_manifest_handler,
    enterprise_sample_handler,
    enterprise_summary_handler,
)

ENTERPRISE_MANIFEST_DEFINITION = ToolDefinition(
    "get_enterprise_data_manifest",
    "1.0.0",
    "查询企业数据目录与保留策略",
    EnterpriseManifestInput,
    validate_enterprise_manifest_output,
    title="企业数据目录",
    output_schema=ENTERPRISE_OUTPUT_SCHEMAS["manifest"],
)
ENTERPRISE_SUMMARY_DEFINITION = ToolDefinition(
    "get_enterprise_fab_summary",
    "1.0.0",
    "查询企业晶圆厂汇总",
    EnterpriseSummaryInput,
    validate_enterprise_summary_output,
    title="企业晶圆厂汇总",
    output_schema=ENTERPRISE_OUTPUT_SCHEMAS["summary"],
)
ENTERPRISE_SAMPLE_DEFINITION = ToolDefinition(
    "query_enterprise_data",
    "1.0.0",
    "查询企业数据样本",
    EnterpriseSampleInput,
    validate_enterprise_sample_output,
    title="企业数据样本",
    output_schema=ENTERPRISE_OUTPUT_SCHEMAS["sample"],
)


def _prepare(
    value: EnterpriseManifestInput | EnterpriseSummaryInput | EnterpriseSampleInput,
    context: ToolExecutionContext[EnterpriseToolsDependencies],
) -> ToolPreparation[
    EnterpriseManifestInput | EnterpriseSummaryInput | EnterpriseSampleInput
]:
    return ToolPreparation(
        value,
        enterprise_scope(value.resolve(context.dependencies.window), context.principal),
    )


def create_enterprise_manifest_binding(
    port: EnterpriseDataPort, *, window: EnterpriseWindow
) -> ToolBinding[EnterpriseManifestInput, EnterpriseToolsDependencies, object]:
    return ToolBinding(
        ENTERPRISE_MANIFEST_DEFINITION,
        enterprise_manifest_handler,
        EnterpriseToolsDependencies(port, window),
        _prepare,
    )


def create_enterprise_summary_binding(
    port: EnterpriseDataPort, *, window: EnterpriseWindow
) -> ToolBinding[EnterpriseSummaryInput, EnterpriseToolsDependencies, object]:
    return ToolBinding(
        ENTERPRISE_SUMMARY_DEFINITION,
        enterprise_summary_handler,
        EnterpriseToolsDependencies(port, window),
        _prepare,
    )


def create_enterprise_sample_binding(
    port: EnterpriseDataPort, *, window: EnterpriseWindow
) -> ToolBinding[EnterpriseSampleInput, EnterpriseToolsDependencies, object]:
    return ToolBinding(
        ENTERPRISE_SAMPLE_DEFINITION,
        enterprise_sample_handler,
        EnterpriseToolsDependencies(port, window),
        _prepare,
    )
