from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from app.agent_runtime.tools.contracts import ToolExecutionContext
from app.bootstrap.tool_definitions import BUSINESS_TOOL_DEFINITIONS
from app.bootstrap.tool_sources import ToolSources, create_tool_bindings
from app.demo_data.tool_sources.equipment_health import (
    FakeEquipmentHealthAdapter,
)
from app.tools.equipment_health.contracts import (
    EquipmentHealthAggregate,
    EquipmentHealthQuery,
)

AS_OF = date(2026, 10, 24)


class _Principal:
    tenant_id = "demo"
    user_id = "analyst"
    roles = ("analyst",)


class ToolSourceCompositionTests(unittest.TestCase):
    def test_each_family_is_opt_in_and_never_constructed_by_composition(self) -> None:
        health = object()
        bindings = create_tool_bindings(
            ToolSources(equipment_health=health), as_of=AS_OF, default_tenant_id="demo"
        )
        self.assertEqual(
            [item.definition.name for item in bindings], ["get_equipment_health"]
        )
        self.assertIs(bindings[0].dependencies.port, health)
        self.assertEqual(
            create_tool_bindings(ToolSources(), as_of=AS_OF, default_tenant_id="demo"),
            (),
        )

    def test_full_explicit_profile_has_existing_twenty_one_canonical_names(
        self,
    ) -> None:
        marker = object()
        bindings = create_tool_bindings(
            ToolSources(marker, marker, marker, marker, marker, marker, marker),
            as_of=AS_OF,
            default_tenant_id="demo",
        )
        names = [binding.definition.name for binding in bindings]
        self.assertEqual(len(names), 21)
        self.assertEqual(len(set(names)), 21)
        self.assertNotIn("get_equipment_health_summary", names)
        self.assertIn("search_knowledge", names)
        self.assertIn("get_lot_wafer_map_patterns", names)
        self.assertEqual(
            tuple(item.definition for item in bindings), BUSINESS_TOOL_DEFINITIONS
        )

    def test_datetime_is_not_an_ambiguous_as_of_date(self) -> None:
        with self.assertRaises(TypeError):
            create_tool_bindings(
                ToolSources(),
                as_of=datetime(2026, 10, 24, tzinfo=timezone.utc),
                default_tenant_id="demo",
            )

    def test_summary_is_explicit_and_reuses_health_source_scope_and_classification(
        self,
    ) -> None:
        query = EquipmentHealthQuery(AS_OF - timedelta(days=89), AS_OF)
        port = FakeEquipmentHealthAdapter(
            "demo",
            {
                query: (
                    EquipmentHealthAggregate("A", 8, 8, 0.1, 98.0, 0, 1.0),
                    EquipmentHealthAggregate("B", 5, 3, 0.1, 98.0, 0, 1.0),
                    EquipmentHealthAggregate("C", 5, 0, 0.1, 98.0, 0, 1.0),
                )
            },
        )
        binding = create_tool_bindings(
            ToolSources(equipment_health=port),
            as_of=AS_OF,
            default_tenant_id="demo",
            include_equipment_health_summary=True,
        )[-1]
        result = binding.handler(
            binding.definition.parse({}),
            ToolExecutionContext(_Principal(), "r", "c", binding.dependencies),
        )
        self.assertEqual(
            result.data, {"equipment_count": 3, "critical": 1, "watch": 1, "healthy": 1}
        )
        self.assertEqual(result.sources[0].source_ref, "fake:equipment-health")
        self.assertEqual(result.sources[0].scope.grain, "equipment")
        self.assertEqual(port.calls, [query])

    def test_summary_without_its_only_source_and_invalid_tenant_are_rejected_without_fallback(
        self,
    ) -> None:
        with self.assertRaises(ValueError):
            create_tool_bindings(
                ToolSources(),
                as_of=AS_OF,
                default_tenant_id="demo",
                include_equipment_health_summary=True,
            )
        with self.assertRaises(ValueError):
            create_tool_bindings(ToolSources(), as_of=AS_OF, default_tenant_id=" ")
