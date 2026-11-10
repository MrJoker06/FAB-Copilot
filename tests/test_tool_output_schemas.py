"""Exercise declared data schemas against actual native handlers and refusals."""

from datetime import date
import unittest

from jsonschema import Draft202012Validator, ValidationError

from app.agent_runtime.tools.contracts import ToolExecutionContext
from app.bootstrap.tool_sources import create_tool_bindings
from app.bootstrap.tool_sources_demo import AS_OF, _Principal, _arguments, build_fake_sources
from app.demo_data.tool_sources.equipment_health import FakeEquipmentHealthAdapter
from app.tools.equipment_health.binding import create_equipment_health_binding
from app.tools.equipment_health.contracts import EquipmentHealthDataError, EquipmentHealthInputError, EquipmentHealthQuery


class ToolOutputSchemaTests(unittest.TestCase):
    def test_declared_schemas_validate_real_handlers(self):
        bindings = create_tool_bindings(
            build_fake_sources(AS_OF), as_of=AS_OF, default_tenant_id="demo",
            include_equipment_health_summary=True,
        )
        for binding in bindings:
            if binding.definition.output_schema is None:
                continue  # Remaining families acquire schemas in their migration batch.
            with self.subTest(tool=binding.definition.name):
                schema = binding.definition.output_schema
                Draft202012Validator.check_schema(schema)
                value = binding.definition.parse(_arguments(binding.definition.name))
                result = binding.handler(value, ToolExecutionContext(_Principal(), "schema-run", "schema-call", binding.dependencies))
                self.assertEqual(result.status.value, "succeeded")
                Draft202012Validator(schema).validate(result.data)
                with self.assertRaises(ValidationError):
                    Draft202012Validator(schema).validate({"unexpected": True})

    def test_empty_health_and_rejected_requests_do_not_become_success_data(self):
        query = EquipmentHealthQuery(date(2026, 7, 27), AS_OF)
        port = FakeEquipmentHealthAdapter("demo", {query: ()})
        binding = create_equipment_health_binding(port, today=lambda: AS_OF)
        result = binding.handler(binding.definition.parse({}), ToolExecutionContext(_Principal(), "r", "c", binding.dependencies))
        Draft202012Validator(binding.definition.output_schema).validate(result.data)
        self.assertEqual(result.data, [])
        with self.assertRaises(EquipmentHealthInputError):
            binding.handler(binding.definition.parse({"start": "bad-date"}), ToolExecutionContext(_Principal(), "r", "c", binding.dependencies))
        self.assertEqual(len(port.calls), 1)
        other = _Principal(tenant_id="other")
        with self.assertRaises(EquipmentHealthDataError):
            binding.handler(binding.definition.parse({}), ToolExecutionContext(other, "r", "c", binding.dependencies))
        self.assertEqual(len(port.calls), 1)
