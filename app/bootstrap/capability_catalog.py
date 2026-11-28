"""Installed capabilities and instance-local registration for the duty assistant."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from importlib.metadata import entry_points
from pathlib import Path

from app.agent_runtime.tools.definition import ToolBinding, ToolDefinition
from app.agent_runtime.tools.projection import mcp_tool_view
from app.core.settings import PROJECT_DIR, get_settings
from app.skills.contracts import SkillPackageError
from app.skills.standard import inspect_skill
from app.skills.versions import parse_version_requirement
from app.tools.lot_commonality.binding import LOT_COMMONALITY_DEFINITIONS

from .tool_definitions import BUSINESS_TOOL_DEFINITIONS

_BUILTIN_DEFINITIONS = (*BUSINESS_TOOL_DEFINITIONS, *LOT_COMMONALITY_DEFINITIONS.values())
_BUILTIN_NAMES = frozenset(definition.name for definition in _BUILTIN_DEFINITIONS)


@dataclass(frozen=True)
class InstalledTool:
    definition: ToolDefinition
    routes: frozenset[str]
    bind: Callable[[object, object], ToolBinding]


def bind_trend(settings, principal):
    from app.tools.capability_trend.sqlite_source import SQLiteCapabilityTrendSource
    from app.tools.capability_trend.tool import create_capability_trend_binding

    port = SQLiteCapabilityTrendSource(
        settings.manufacturing_database_path,
        demo_tenant_id=settings.enterprise_default_tenant_id,
    )
    return create_capability_trend_binding(
        port, today=lambda: datetime.now(timezone.utc).date()
    )


@lru_cache(maxsize=1)
def plugin_tools():
    from app.tools.capability_trend.tool import CAPABILITY_TREND_DEFINITION as trend

    tools = {
        trend.name: InstalledTool(
            trend, frozenset({"capability_excursion"}), bind_trend
        )
    }
    reserved = _BUILTIN_NAMES | {
        "submit_analysis",
        "read_tool_result",
        "query_manufacturing_data",
        "safe_select",
    }
    for entry in entry_points(group="fab_agent.tools"):
        for tool in entry.load()():
            if (
                not isinstance(tool, InstalledTool)
                or not tool.routes
                or not callable(tool.bind)
            ):
                raise ValueError("invalid installed tool provider")
            name = tool.definition.name
            if name in reserved or name in tools:
                raise ValueError("duplicate installed tool")
            tools[name] = tool
    return tools


def db_path():
    return get_settings().agent_database_path.parent / "capability_directory.db"


def policies():
    path = db_path()
    if not path.exists():
        return {}
    with closing(sqlite3.connect(path)) as conn:
        # A concurrent first registration can have opened the file but not yet committed.
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='registrations'"
        ).fetchone():
            return {}
        return {
            (kind, name): json.loads(body)
            for kind, name, body in conn.execute(
                "SELECT kind,name,body FROM registrations"
            )
        }


def save(kind, name, registration):
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS registrations(kind TEXT,name TEXT,body TEXT NOT NULL,PRIMARY KEY(kind,name))"
        )
        conn.execute(
            "INSERT OR REPLACE INTO registrations VALUES (?,?,?)",
            (kind, name, json.dumps(registration, ensure_ascii=False)),
        )


def permitted(rule, modules):
    access = rule["access"]
    return rule["enabled"] and (
        access is None
        or access["owner"] in modules
        or not set(modules).isdisjoint(access["readers"])
    )


def skill_allowed(name, principal, rules=None):
    rules = policies() if rules is None else rules
    rule = rules.get(("skill", name))
    return rule is not None and permitted(rule, getattr(principal, "modules", ()))


def skills_root():
    return Path(os.getenv("FAB_SKILLS_ROOT") or PROJECT_DIR / "app/skills")


def tool_allowed(name, principal, rules=None):
    rules = policies() if rules is None else rules
    rule = rules.get(("tool", name))
    if rule is None:
        return name in _BUILTIN_NAMES
    return permitted(rule, getattr(principal, "modules", ()))


def inventory():
    entries = {}
    for definition in [
        *_BUILTIN_DEFINITIONS,
        *(p.definition for p in plugin_tools().values()),
    ]:
        entries["tool", definition.name] = dict(
            mcp_tool_view(definition),
            version=definition.version,
            builtin=definition.name in _BUILTIN_NAMES,
        )
    root = skills_root()
    for file in sorted(root.glob("*/SKILL.md")):
        if file.parent.is_symlink() or file.is_symlink():
            continue
        try:
            skill = inspect_skill(file.parent)
        except SkillPackageError as exc:
            name = file.parent.name
            entries["skill", name] = {
                "name": name,
                "description": "技能包校验失败",
                "builtin": False,
                "availability_issue": exc.code,
            }
            continue
        manifest = skill.manifest
        name = skill.document.name
        if ("skill", name) in entries:
            raise ValueError("duplicate installed skill")
        entries["skill", name] = {
            "name": name,
            "description": skill.document.description,
            "title": manifest.title if manifest else name,
            "version": manifest.version if manifest else None,
            "instructions": skill.instructions,
            "workflow": bool(manifest and manifest.workflow),
            "availability_issue": manifest.status
            if manifest and manifest.status != "published"
            else None,
            "requires": {t.name: t.version for t in manifest.tools} if manifest else {},
            "builtin": False,
        }
    return entries


def directory(principal, *, admin=False):
    entries, rules = inventory(), policies()
    result = []
    for (kind, name), data in entries.items():
        rule = rules.get((kind, name))
        registered = rule is not None or data["builtin"]
        if rule is None:
            rule = {"access": None, "enabled": data["builtin"], "groups": []}
        if not admin and (
            data.get("availability_issue")
            or not registered
            or not permitted(rule, getattr(principal, "modules", ()))
        ):
            continue
        missing = []
        for tool_name, version in data.get("requires", {}).items():
            tool = entries.get(("tool", tool_name))
            tool_rule = rules.get(("tool", tool_name))
            if admin:
                enabled = (
                    tool_rule["enabled"]
                    if tool_rule
                    else bool(tool and tool["builtin"])
                )
            else:
                enabled = tool_allowed(tool_name, principal, rules)
            if (
                not tool
                or not enabled
                or not parse_version_requirement(version).matches(tool["version"])
            ):
                missing.append(tool_name)
        item = dict(
            data,
            kind=kind,
            registered=registered,
            groups=rule["groups"],
            missing=missing,
        )
        if admin:
            item.update(rule)
        else:
            item.pop("missing")
            item.pop("requires", None)
            item["owner"] = rule["access"]["owner"] if rule["access"] else None
            item["dependencies_ready"] = not missing
            if missing:
                item.pop("instructions", None)
        result.append(item)
    return result
