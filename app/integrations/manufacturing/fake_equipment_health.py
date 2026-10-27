"""Explicit fixture-backed adapter for the equipment-health pilot."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta

from ...agent_runtime.tools.contracts import (
    ToolPrincipal,
    ToolScope,
    ToolSource,
    ToolSourceKind,
)
from ...manufacturing.equipment_health.contracts import (
    EquipmentHealthAggregate,
    EquipmentHealthDataError,
    EquipmentHealthQuery,
    EquipmentHealthSnapshot,
)


@dataclass
class FakeEquipmentHealthAdapter:
    demo_tenant_id: str
    fixtures: Mapping[EquipmentHealthQuery, tuple[EquipmentHealthAggregate, ...]]
    calls: list[EquipmentHealthQuery] = field(default_factory=list)

    def fetch(
        self, query: EquipmentHealthQuery, principal: ToolPrincipal
    ) -> EquipmentHealthSnapshot:
        if principal.tenant_id != self.demo_tenant_id:
            raise EquipmentHealthDataError("equipment-health source is unavailable")
        self.calls.append(query)
        try:
            rows = self.fixtures[query]
        except KeyError as exc:
            raise EquipmentHealthDataError(
                "no equipment-health fixture for requested scope"
            ) from exc
        scope = ToolScope(
            principal.tenant_id,
            query.start,
            query.end,
            (query.equipment_id,) if query.equipment_id else (),
            (query.process_step,) if query.process_step else (),
            grain="equipment",
        )
        return EquipmentHealthSnapshot(
            query,
            tuple(rows),
            ToolSource(
                "fake:equipment-health",
                "fake-equipment-health",
                ToolSourceKind.FAKE,
                scope,
            ),
        )


def demo_fake_adapter(
    *, demo_tenant_id: str, as_of: date
) -> FakeEquipmentHealthAdapter:
    """A visibly synthetic row used only by the standalone demo CLI."""
    from ...manufacturing.equipment_health.contracts import EquipmentHealthQuery

    query = EquipmentHealthQuery(as_of - timedelta(days=89), as_of)
    return FakeEquipmentHealthAdapter(
        demo_tenant_id,
        {query: (EquipmentHealthAggregate("DEMO-01", 12, 1, 0.123, 98.5, 2, 15.0),)},
    )
