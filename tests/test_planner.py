from __future__ import annotations

import asyncio
import json
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from app import agent as agent_module
from app.manufacturing.playbooks import select_playbook
from app.intent_runtime.routing import route_question
from app.planning_runtime.service import create_execution_plan


def _plan(question: str, current_date: date = date(2026, 7, 18)):
    route = route_question(question, current_date=current_date)
    return create_execution_plan(question, route, select_playbook(route))


class StructuredPlannerTests(unittest.TestCase):
    def test_six_playbooks_create_ready_serializable_plans(self):
        cases = (
            ("分析 CMP-03 最近7天 Cpk 不合格", "PB-CAPABILITY-001", {"CAP-01", "CAP-02", "CAP-04"}),
            ("最近四周良率下降", "PB-YIELD-001", {"YLD-01", "YLD-02", "YLD-03"}),
            ("检查 ETCH-04 故障报警", "PB-EQUIPMENT-001", {"EQP-01", "EQP-02", "EQP-03", "EQP-04", "EQP-05"}),
            ("追踪批次 L260708-02460", "PB-LOT-001", {"LOT-01", "LOT-02", "LOT-03", "LOT-04"}),
            ("查询 CMP 恢复量产 SOP", "PB-SOP-001", {"SOP-01", "SOP-02"}),
            ("关于目前的制造数据你有什么改进建议", "PB-FAB-001", {"FAB-01", "FAB-02", "FAB-03", "FAB-04"}),
        )
        for question, playbook_id, evidence_ids in cases:
            with self.subTest(question=question):
                plan = _plan(question)
                self.assertEqual(plan.status, "ready")
                self.assertEqual(plan.playbook_id, playbook_id)
                self.assertEqual(set(plan.required_evidence_ids), evidence_ids)
                self.assertTrue(plan.steps)
                self.assertEqual(plan.budget.planned_tool_calls, len(plan.steps))
                self.assertGreaterEqual(plan.budget.max_tool_calls, len(plan.steps))
                self.assertEqual(plan.budget.max_model_iterations, 6)
                self.assertEqual(plan.budget.enforcement, "runtime")
                self.assertEqual(plan.budget.max_identical_parameter_calls, 1)
                self.assertEqual(plan.budget.max_no_progress_rounds, 2)
                self.assertTrue(plan.budget.per_tool_limits)
                json.dumps(plan.to_dict(), ensure_ascii=False)

    def test_plan_id_and_steps_are_deterministic(self):
        first = _plan("分析 CMP-03 最近7天 Cpk 不合格")
        second = _plan("分析 CMP-03 最近7天 Cpk 不合格")

        self.assertEqual(first, second)
        self.assertRegex(first.plan_id, r"^plan-[0-9a-f]{16}$")
        self.assertEqual(first.schema_version, "1.1")
        self.assertEqual(first.planner_version, "1.1.0")

    def test_dependencies_form_an_ordered_acyclic_graph_and_cover_required_evidence(self):
        questions = (
            "分析 CMP-03 最近7天 Cpk 不合格",
            "最近四周良率下降",
            "检查 ETCH-04 故障报警",
            "追踪批次 L260708-02460",
            "查询 CMP 恢复量产 SOP",
            "关于目前的制造数据你有什么改进建议",
        )
        for question in questions:
            plan = _plan(question)
            seen: set[str] = set()
            required_coverage: set[str] = set()
            for step in plan.steps:
                with self.subTest(question=question, step=step.step_id):
                    self.assertTrue(set(step.depends_on).issubset(seen))
                    self.assertNotIn(step.step_id, step.depends_on)
                    self.assertTrue(step.evidence_ids)
                    self.assertTrue(step.success_criteria)
                    self.assertLessEqual(step.estimated_result_limit, plan.budget.max_rows_per_call)
                    if step.required:
                        required_coverage.update(step.evidence_ids)
                    seen.add(step.step_id)
            self.assertTrue(set(plan.required_evidence_ids).issubset(required_coverage))

    def test_capability_plan_binds_route_parameters_and_optional_step_does_not_block_required_step(self):
        plan = _plan("分析 CMP-03 最近7天 Cpk 不合格")
        by_tool = {step.tool: step for step in plan.steps}

        capability = by_tool["get_process_capability"]
        self.assertEqual(
            capability.parameters,
            {"start": "2026-07-12", "end": "2026-07-18", "process_step": "CMP"},
        )
        sensor = by_tool["get_sensor_summary"]
        self.assertFalse(sensor.required)
        self.assertEqual(sensor.parameters["equipment_id"], "CMP-03")
        knowledge = by_tool["search_knowledge"]
        self.assertTrue(knowledge.required)
        self.assertNotIn(sensor.step_id, knowledge.depends_on)
        self.assertIn("CAP-02", next(
            item.evidence_ids for item in plan.steps if item.step_id in knowledge.depends_on
        ))

    def test_yield_plan_deduplicates_trend_call_and_uses_fixed_read_only_sql(self):
        plan = _plan("最近四周良率下降")
        trend_steps = [step for step in plan.steps if step.tool == "get_yield_trend"]
        self.assertEqual(len(trend_steps), 1)
        self.assertEqual(set(trend_steps[0].evidence_ids), {"YLD-01", "YLD-02"})

        sql_step = next(step for step in plan.steps if step.tool == "query_manufacturing_data")
        sql = sql_step.parameters["sql"]
        self.assertTrue(sql.startswith("SELECT product, technology_nm"))
        self.assertIn("complete_time >= '2026-06-21'", sql)
        self.assertIn("complete_time < '2026-07-19'", sql)
        self.assertIn("GROUP BY product, technology_nm", sql)
        self.assertTrue(sql.endswith("LIMIT 100"))
        self.assertNotIn(";", sql)

    def test_process_route_does_not_relabel_fab_or_unfiltered_lots_evidence(self):
        plan = _plan("分析 CMP 最近一周良率下降")
        fab = next(step for step in plan.steps if step.tool == "get_fab_overview")
        lots = next(step for step in plan.steps if step.tool == "query_manufacturing_data")
        self.assertEqual(fab.evidence_scope["fab_ids"], ("FAB",))
        self.assertEqual(fab.evidence_scope["process_steps"], ())
        self.assertEqual(lots.evidence_scope["fab_ids"], ("FAB",))
        self.assertEqual(lots.evidence_scope["process_steps"], ())
        self.assertEqual(lots.scope_role, "context_only")

    def test_equipment_yield_pass_rate_uses_actual_equipment_filter(self):
        plan = _plan("分析 ETCH-01 最近一周良率下降")
        step = next(item for item in plan.steps if item.tool == "get_process_pass_rate")
        self.assertEqual(step.parameters["equipment_id"], "ETCH-01")
        self.assertEqual(step.parameters["process_step"], "ETCH")
        self.assertEqual(step.grain, "equipment")
        self.assertEqual(step.evidence_scope["equipment_ids"], ("ETCH-01",))

    def test_sop_and_product_plans_keep_actual_primary_scope(self):
        sop = _plan("查询 CMP 恢复量产 SOP")
        self.assertEqual(sop.scope_contract.primary_scope_type, "process")
        self.assertTrue(all(step.scope_role == "primary" for step in sop.steps))
        product = _plan("分析 Nova-P1 最近一周良率下降")
        trend = next(step for step in product.steps if step.tool == "get_yield_trend")
        layered = next(step for step in product.steps if step.tool == "query_manufacturing_data")
        self.assertEqual(trend.parameters["product"], "Nova-P1")
        self.assertEqual(trend.scope_role, "primary")
        self.assertEqual(layered.evidence_scope["products"], ("NOVA-P1",))
        self.assertEqual(layered.scope_role, "primary")

    def test_lot_plan_builds_identity_route_and_three_impact_queries(self):
        plan = _plan("追踪批次 L260708-02460")
        sql_steps = [step for step in plan.steps if step.tool == "query_manufacturing_data"]

        self.assertEqual(len(sql_steps), 5)
        self.assertTrue(all("L260708-02460" in step.parameters["sql"] for step in sql_steps))
        lot_03_steps = [step for step in sql_steps if "LOT-03" in step.evidence_ids]
        self.assertEqual(len(lot_03_steps), 3)
        self.assertTrue(any("FROM defect_records" in step.parameters["sql"] for step in lot_03_steps))
        self.assertTrue(any("FROM wafer_maps" in step.parameters["sql"] for step in lot_03_steps))

    def test_sop_plan_separates_formal_sources_from_cases(self):
        plan = _plan("查询 CMP 恢复量产 SOP")
        searches = [step for step in plan.steps if step.tool == "search_knowledge"]

        self.assertEqual(len(searches), 2)
        formal = next(step for step in searches if set(step.evidence_ids) == {"SOP-01", "SOP-02"})
        case = next(step for step in searches if step.evidence_ids == ("SOP-03",))
        self.assertEqual(formal.parameters["source_types"], ["personal", "knowledge"])
        self.assertEqual(case.parameters["source_types"], ["case"])
        self.assertEqual(case.depends_on, (formal.step_id,))

    def test_fab_diagnostic_plan_covers_all_improvement_dimensions(self):
        plan = _plan("关于目前的制造数据你有什么改进建议")
        by_tool = {step.tool: step for step in plan.steps}
        expected_tools = {
            "get_fab_overview", "get_yield_trend", "get_process_capability",
            "get_equipment_health", "get_equipment_productivity",
            "get_defect_pareto", "get_recent_excursions",
        }

        self.assertEqual(plan.status, "ready")
        self.assertEqual(plan.playbook_id, "PB-FAB-001")
        self.assertEqual(set(by_tool), expected_tools)
        self.assertEqual(plan.budget.planned_tool_calls, 7)
        self.assertEqual(plan.budget.max_tool_calls, 9)
        self.assertEqual(
            by_tool["get_process_capability"].parameters,
            {"start": "2026-04-20", "end": "2026-07-18"},
        )
        self.assertEqual(set(by_tool["get_fab_overview"].evidence_ids), {"FAB-01"})
        self.assertEqual(set(by_tool["get_equipment_health"].evidence_ids), {"FAB-03"})
        self.assertEqual(set(by_tool["get_defect_pareto"].evidence_ids), {"FAB-04"})

    def test_process_area_overview_scopes_supported_tools(self):
        cases = (
            ("分析最近一周光刻机台状况", "LITHO"),
            ("为我分析一下最近一周刻蚀机台的情况", "ETCH"),
            ("评估近两周CVD生产表现", "CVD"),
            ("盘点最近一周溅射设备现状", "PVD"),
            ("总结近7天炉管运行状态", "DIFFUSION"),
            ("分析最近一周离子注入生产状况", "IMPLANT"),
            ("评估过去7天CMP机台表现", "CMP"),
            ("查看近两周清洗设备情况", "CLEAN"),
            ("分析最近一周量测机台状况", "METROLOGY"),
        )
        scoped_tools = (
            "get_process_capability",
            "get_equipment_health",
            "get_equipment_productivity",
            "get_defect_pareto",
            "get_recent_excursions",
        )

        for question, process_step in cases:
            with self.subTest(question=question):
                plan = _plan(question)
                by_tool = {step.tool: step for step in plan.steps}

                self.assertEqual(plan.status, "ready")
                self.assertEqual(plan.playbook_id, "PB-FAB-001")
                self.assertEqual(
                    {tool: by_tool[tool].parameters.get("process_step") for tool in scoped_tools},
                    {tool: process_step for tool in scoped_tools},
                )
                self.assertEqual(by_tool["get_fab_overview"].scope_role, "context_only")
                self.assertEqual(by_tool["get_yield_trend"].scope_role, "context_only")
                self.assertTrue(all(by_tool[tool].scope_role == "primary" for tool in scoped_tools))
                self.assertEqual(plan.scope_contract.primary_scope_type, "process")
                self.assertEqual(plan.scope_contract.primary_scope_ids, (process_step,))

    def test_equipment_scope_is_pushed_to_supported_operational_tools(self):
        plan = _plan("检查 ETCH-04 最近一周的故障报警")
        by_tool = {step.tool: step for step in plan.steps}

        self.assertEqual(plan.scope_contract.primary_scope_type, "equipment")
        self.assertEqual(plan.scope_contract.primary_scope_ids, ("ETCH-04",))
        for tool in (
            "get_equipment_health",
            "get_equipment_productivity",
            "get_recent_excursions",
            "get_sensor_summary",
        ):
            self.assertEqual(by_tool[tool].parameters["equipment_id"], "ETCH-04")
            self.assertEqual(by_tool[tool].scope_role, "primary")

    def test_product_wide_diagnostic_stops_before_unscoped_tools(self):
        plan = _plan("分析 Nova-P1 的生产状况")

        self.assertEqual(plan.status, "clarification_required")
        self.assertEqual(plan.scope_contract.primary_scope_type, "product")
        self.assertEqual(plan.steps, ())
        self.assertEqual(plan.budget.max_tool_calls, 0)
        self.assertEqual(plan.missing_inputs, ("product_analysis_scope",))

    def test_unknown_manufacturing_scope_creates_no_tool_steps(self):
        plan = _plan("分析一下最近PH的生产状况", current_date=date(2026, 7, 20))

        self.assertEqual(plan.status, "clarification_required")
        self.assertEqual(plan.steps, ())
        self.assertEqual(plan.budget.max_tool_calls, 0)
        self.assertEqual(plan.missing_inputs, ("manufacturing_scope",))
        self.assertIn("PH", plan.clarification_questions[0])

    def test_missing_ambiguous_and_unknown_inputs_create_no_tool_steps(self):
        cases = (
            ("分析 Cpk 不合格", "process_step"),
            ("追踪这个批次", "lot_id"),
            ("设备健康和良率趋势", "primary_intent"),
            ("帮我看看这个情况", "primary_intent"),
        )
        for question, missing_input in cases:
            with self.subTest(question=question):
                plan = _plan(question)
                self.assertEqual(plan.status, "clarification_required")
                self.assertEqual(plan.steps, ())
                self.assertEqual(plan.budget.max_tool_calls, 0)
                self.assertEqual(plan.budget.max_model_iterations, 1)
                self.assertIn(missing_input, plan.missing_inputs)
                self.assertTrue(plan.clarification_questions)

    def test_unsupported_intent_keeps_generic_path_without_domain_steps(self):
        plan = _plan("分析 CMP 划伤缺陷 Pareto")

        self.assertEqual(plan.status, "unsupported")
        self.assertEqual(plan.steps, ())
        self.assertEqual(plan.budget.planned_tool_calls, 0)
        self.assertEqual(plan.budget.max_tool_calls, 10)
        self.assertEqual(plan.budget.per_tool_limits["*"], 3)

    def test_ready_plan_is_returned_but_model_receives_only_compact_synthesis_contract(self):
        captured: dict = {}
        progress_events: list[dict] = []

        async def fake_stream(client, endpoint, headers, request_payload, progress, stream_state):
            captured.update(request_payload)
            return ({"role": "assistant", "content": "Planner 测试完成"}, {"total_tokens": 5}, "planner-response")

        async def progress(event: dict) -> None:
            progress_events.append(event)

        settings = SimpleNamespace(
            model_connection=SimpleNamespace(provider="test", api_key="test-key", base_url="https://example.test", model="test-model"),
            api_timeout_seconds=5,
            model_max_retries=0,
            model_retry_base_seconds=0.05,
        )
        with (
            patch("app.agent.get_settings", return_value=settings),
            patch("app.agent._stream_completion", new=fake_stream),
        ):
            result = asyncio.run(
                agent_module._run_agent_impl(
                    "分析 CMP-03 最近7天 Cpk",
                    [],
                    "run-structured-planner-test",
                    progress,
                )
            )

        self.assertEqual(result["execution_plan"]["status"], "ready")
        plan_event = next(event for event in progress_events if event.get("stage") == "plan")
        self.assertEqual(plan_event["plan"], result["execution_plan"])

        self.assertEqual(result["execution_mode"], "deterministic_ready_plan")
        self.assertEqual(result["model_tool_selection_calls"], 0)
        self.assertEqual(
            [item["function"]["name"] for item in captured["tools"]],
            ["submit_analysis"],
        )
        self.assertFalse(any(
            "execution_plan=" in item["content"]
            for item in captured["messages"]
        ))
        synthesis_task = json.loads(captured["messages"][-1]["content"])
        self.assertEqual(synthesis_task["plan_id"], result["execution_plan"]["plan_id"])
        self.assertEqual(
            [item["tool"] for item in synthesis_task["evidence"]],
            [step["tool"] for step in result["execution_plan"]["steps"]],
        )


if __name__ == "__main__":
    unittest.main()
