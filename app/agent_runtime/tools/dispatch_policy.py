"""Small explicit demo policy; deployments supply their own ToolPolicy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from .contracts import ToolScope
from .dispatch_contracts import PolicyDecision


@dataclass(frozen=True, slots=True)
class DemoToolPolicy:
    """Tenant/role/capability allow-list policy for the dispatcher demonstration."""

    capabilities: frozenset[str]
    required_roles: frozenset[str] = frozenset()
    tenant_id: str | None = None
    equipment_ids: frozenset[str] | None = None
    start_date: date | None = None
    end_date: date | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.capabilities, frozenset) or any(
            not isinstance(value, str) or not value.strip() or value == "*"
            for value in self.capabilities
        ):
            raise ValueError("capabilities must be a frozenset of names")
        if not isinstance(self.required_roles, frozenset) or any(
            not isinstance(value, str) or not value.strip()
            for value in self.required_roles
        ):
            raise ValueError("required_roles must be a frozenset of names")
        if self.tenant_id is not None and (
            not isinstance(self.tenant_id, str) or not self.tenant_id.strip()
        ):
            raise ValueError("tenant_id must be a non-empty string or None")
        if self.equipment_ids is not None and (
            not isinstance(self.equipment_ids, frozenset)
            or any(
                not isinstance(value, str) or not value.strip()
                for value in self.equipment_ids
            )
        ):
            raise ValueError("equipment_ids must be a frozenset of names or None")
        if (
            self.start_date is not None
            and (
                isinstance(self.start_date, datetime)
                or not isinstance(self.start_date, date)
            )
        ) or (
            self.end_date is not None
            and (
                isinstance(self.end_date, datetime)
                or not isinstance(self.end_date, date)
            )
        ):
            raise TypeError("date bounds must be date values or None")
        if (self.start_date is None) != (self.end_date is None) or (
            self.start_date is not None and self.start_date > self.end_date
        ):
            raise ValueError("date bounds must be paired and ordered")

    def authorize(
        self, principal: object, name: str, scope: ToolScope
    ) -> PolicyDecision:
        if name not in self.capabilities:
            return PolicyDecision(
                False, "CAPABILITY_DENIED", "This tool is not authorized."
            )
        if getattr(principal, "tenant_id", None) != scope.tenant_id or (
            self.tenant_id is not None and scope.tenant_id != self.tenant_id
        ):
            return PolicyDecision(
                False, "SCOPE_DENIED", "This scope is not authorized."
            )
        roles = getattr(principal, "roles", ())
        if self.required_roles and not self.required_roles.intersection(roles):
            return PolicyDecision(
                False, "ROLE_DENIED", "This principal is not authorized."
            )
        if self.equipment_ids is not None and (
            not scope.equipment_ids
            or not set(scope.equipment_ids) <= self.equipment_ids
        ):
            return PolicyDecision(
                False, "SCOPE_DENIED", "This scope is not authorized."
            )
        if self.start_date is not None and (
            scope.start_date is None
            or scope.start_date < self.start_date
            or scope.end_date is None
            or scope.end_date > self.end_date
        ):
            return PolicyDecision(
                False, "SCOPE_DENIED", "This scope is not authorized."
            )
        return PolicyDecision(True)
