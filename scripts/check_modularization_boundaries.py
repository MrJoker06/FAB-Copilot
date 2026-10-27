"""Validate the MOD-003 ownership, migration-debt, and boundary inventory.

This is intentionally an AST-only gate: it never imports ``app`` (and therefore
does not load settings, open SQLite, or contact a provider).  Dynamic expressions
and external consumers remain a manual-review concern.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter
from pathlib import Path

try:  # Works both as ``python scripts/...`` and as an imported test module.
    from check_module_boundaries import imported_modules
except ModuleNotFoundError:
    from scripts.check_module_boundaries import imported_modules


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = PROJECT_DIR / "evaluations" / "mod_003_boundaries_v1.json"
MODULES = {
    "runtime",
    "tool_system",
    "business_tools",
    "orchestration",
    "models",
    "context_memory",
    "knowledge",
    "evidence",
    "manufacturing_domain",
    "integrations",
    "persistence",
    "simulation",
    "observability",
    "application_bootstrap",
    "core_contracts_configuration",
    "static_ui",
}
REQUIRED_COMPATIBILITY_FIELDS = {
    "entrypoint",
    "owner",
    "strategy",
    "exit_task",
    "exit_condition",
    "target_checkpoint",
    "validation",
    "consumer_scope",
}
DEFAULT_ARTIFACT_GROUPS = {
    "platform_core",
    "manufacturing_capability",
    "enterprise_adapters",
    "simulation_fixtures",
    "application_bundle",
}


def canonical_path(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("app/")
        and "\\" not in value
        and "//" not in value
        and "/./" not in value
        and ".." not in Path(value).parts
        and Path(value).as_posix() == value
    )


def app_files(project_dir: Path) -> set[str]:
    root = project_dir / "app"
    paths: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.suffix == ".py" or "static" in path.relative_to(root).parts:
            paths.add(path.relative_to(project_dir).as_posix())
    return paths


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"manifest unreadable: {error}") from error
    if (
        not isinstance(value, dict)
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
    ):
        raise ValueError("manifest schema_version must be 1")
    return value


def _entries(value: object, name: str, errors: list[str]) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        errors.append(f"{name} must be a list of objects")
        return []
    return value


def ownership_errors(project_dir: Path, manifest: dict[str, object]) -> list[str]:
    errors: list[str] = []
    entries = _entries(manifest.get("files"), "files", errors)
    groups = manifest.get("artifact_groups", sorted(DEFAULT_ARTIFACT_GROUPS))
    if (
        not isinstance(groups, list)
        or not groups
        or not all(isinstance(item, str) and item for item in groups)
    ):
        errors.append("artifact_groups must be a non-empty string list")
        groups = []
    actual = app_files(project_dir)
    if not (project_dir / "app").is_dir():
        errors.append("application directory missing: app")
    for path in (project_dir / "app").rglob("*"):
        if path.is_symlink():
            errors.append(
                f"symlink rejected: {path.relative_to(project_dir).as_posix()}"
            )
    seen: set[str] = set()
    for entry in entries:
        path, module, artifact = (
            entry.get("path"),
            entry.get("primary_module"),
            entry.get("artifact_group"),
        )
        if not canonical_path(path):
            errors.append(f"non-canonical ownership path: {path!r}")
            continue
        if path in seen:
            errors.append(f"duplicate ownership: {path}")
        seen.add(path)
        if not isinstance(module, str) or module not in MODULES:
            errors.append(f"unknown logical module for {path}: {module}")
        if not isinstance(artifact, str) or artifact not in groups:
            errors.append(f"missing artifact owner for {path}")
        status = entry.get("status", "owned")
        if not isinstance(status, str) or status not in {"owned", "transitional"}:
            errors.append(f"invalid ownership status: {path}")
        if entry.get("status") == "transitional" and (
            not isinstance(entry.get("split_targets"), list)
            or not entry["split_targets"]
            or any(
                not isinstance(target, str) or target not in MODULES
                for target in entry["split_targets"]
            )
            or not entry.get("reason")
            or not entry.get("exit_task")
        ):
            errors.append(f"transitional ownership incomplete: {path}")
    errors.extend(f"ownership missing: {path}" for path in sorted(actual - seen))
    errors.extend(f"stale ownership: {path}" for path in sorted(seen - actual))
    return errors


def _module_for(source: str, entries: list[dict[str, object]]) -> str | None:
    path = "app/" + source.removeprefix("app").lstrip(".").replace(".", "/") + ".py"
    if source == "app":
        path = "app/__init__.py"
    for entry in entries:
        if entry.get("path") == path:
            module = entry.get("primary_module")
            return module if isinstance(module, str) else None
    package_path = path.removesuffix(".py") + "/__init__.py"
    for entry in entries:
        if entry.get("path") == package_path:
            module = entry.get("primary_module")
            return module if isinstance(module, str) else None
    return None


def dependency_errors(project_dir: Path, manifest: dict[str, object]) -> list[str]:
    errors: list[str] = []
    entries = _entries(manifest.get("files"), "files", errors)
    allowed = manifest.get("allowed_dependencies")
    if not isinstance(allowed, dict) or set(allowed) != MODULES:
        return errors + ["allowed_dependencies must define every known logical module"]
    if any(
        not isinstance(value, list)
        or "*" in value
        or any(not isinstance(item, str) or item not in MODULES for item in value)
        for value in allowed.values()
    ):
        return errors + [
            "allowed_dependencies must use concrete known modules without '*'"
        ]
    debts = _entries(manifest.get("dependency_debt"), "dependency_debt", errors)
    debt_pairs: set[tuple[str, str]] = set()
    for debt in debts:
        pair = (debt.get("source"), debt.get("target"))
        if not all(
            isinstance(item, str) and item
            for item in (*pair, debt.get("reason"), debt.get("exit_task"))
        ):
            errors.append(
                "dependency debt requires source, target, reason and exit_task"
            )
        elif pair in debt_pairs:
            errors.append(f"duplicate dependency debt: {pair[0]} -> {pair[1]}")
        else:
            debt_pairs.add(pair)  # type: ignore[arg-type]
    app_dir = project_dir / "app"
    actual_pairs: set[tuple[str, str]] = set()
    for path in app_dir.rglob("*.py"):
        if path.is_symlink():
            errors.append(
                f"symlink source rejected: {path.relative_to(project_dir).as_posix()}"
            )
            continue
        for edge in imported_modules(path, app_dir):
            source, target = (
                _module_for(edge.source, entries),
                _module_for(edge.target, entries),
            )
            if source and target and target not in allowed[source]:
                actual_pairs.add((edge.source, edge.target))
                if (edge.source, edge.target) not in debt_pairs:
                    errors.append(
                        f"new dependency debt: {edge.source}:{edge.line} -> {edge.target}"
                    )
    errors.extend(
        f"stale dependency debt: {source} -> {target}"
        for source, target in sorted(debt_pairs - actual_pairs)
    )
    return errors


def portable_errors(project_dir: Path, manifest: dict[str, object]) -> list[str]:
    errors: list[str] = []
    portable = json.loads(
        (project_dir / "evaluations" / "portable_units_v1.json").read_text(
            encoding="utf-8"
        )
    )
    if not isinstance(portable, dict) or not isinstance(portable.get("units"), dict):
        return ["portable manifest units must be an object"]
    counts: Counter[str] = Counter()
    for name, unit in portable["units"].items():
        if not isinstance(unit, dict) or not isinstance(unit.get("files"), list):
            errors.append(f"portable unit files invalid: {name}")
            continue
        for path in unit["files"]:
            if not isinstance(path, str):
                errors.append(f"portable unit path invalid: {name}")
            elif path.startswith("app/"):
                counts[path] += 1
    actual = {path for path, count in counts.items() if count > 1}
    records = _entries(manifest.get("portable_overlaps"), "portable_overlaps", errors)
    declared = {
        record.get("path") for record in records if isinstance(record.get("path"), str)
    }
    if actual != declared:
        errors.append(
            f"portable overlap drift: expected {sorted(actual)}, got {sorted(declared)}"
        )
    for record in records:
        path = record.get("path")
        if (
            not isinstance(path, str)
            or not record.get("reason")
            or not isinstance(record.get("unique_owner"), str)
        ):
            errors.append(f"portable overlap incomplete: {record.get('path')}")
            continue
        owner = next(
            (
                entry.get("artifact_group")
                for entry in manifest.get("files", [])
                if isinstance(entry, dict) and entry.get("path") == path
            ),
            None,
        )
        if owner != record["unique_owner"]:
            errors.append(f"portable overlap owner mismatch: {path}")
    if len(declared) != len(records):
        errors.append("duplicate or invalid portable overlap path")
    return errors


def _literal_consumers(project_dir: Path, symbols: set[str]) -> list[dict[str, str]]:
    """Inventory only statically resolvable imports and common mock patch forms."""
    consumers: set[tuple[str, str, str]] = set()

    def register(file: str, target: str, kind: str) -> None:
        for symbol in symbols:
            if target == symbol or target.startswith(f"{symbol}."):
                consumers.add((file, symbol, kind))

    def dotted(node: ast.AST, aliases: dict[str, str]) -> str | None:
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id if node.id == "__import__" else None)
        if isinstance(node, ast.Attribute):
            base = dotted(node.value, aliases)
            return f"{base}.{node.attr}" if base else None
        return None

    def relative_module(module: str | None, level: int, current: str) -> str:
        package = (
            current.removesuffix(".__init__")
            if current.endswith(".__init__")
            else current.rsplit(".", 1)[0]
        )
        pieces = package.split(".")[: len(package.split(".")) - level + 1]
        return ".".join([*pieces, *(module or "").split(".")]).strip(".")

    for base in ("app", "scripts", "tests"):
        folder = project_dir / base
        if not folder.exists():
            continue
        for path in folder.rglob("*.py"):
            if path.name == Path(__file__).name:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            aliases: dict[str, str] = {}
            relative = path.relative_to(project_dir).with_suffix("")
            current = ".".join(relative.parts)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        bound = alias.asname or alias.name.split(".")[0]
                        aliases[bound] = alias.name if alias.asname else bound
                elif isinstance(node, ast.ImportFrom):
                    module = (
                        relative_module(node.module, node.level, current)
                        if node.level
                        else node.module
                    )
                    if module:
                        for alias in node.names:
                            aliases[alias.asname or alias.name] = (
                                f"{module}.{alias.name}"
                            )
            for node in ast.walk(tree):
                file = path.relative_to(project_dir).as_posix()
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        register(file, alias.name, "import")
                elif isinstance(node, ast.ImportFrom):
                    module = (
                        relative_module(node.module, node.level, current)
                        if node.level
                        else node.module
                    )
                    if not module:
                        continue
                    for alias in node.names:
                        register(file, f"{module}.{alias.name}", "import")
                        register(file, module, "import")
                elif isinstance(node, ast.Call):
                    func = node.func
                    function = dotted(func, aliases)
                    is_mock_patch = function == "unittest.mock.patch"
                    is_mock_method = function in {
                        "unittest.mock.patch.object",
                        "unittest.mock.patch.dict",
                    }
                    if (
                        is_mock_patch
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)
                    ):
                        register(file, node.args[0].value, "patch")
                    elif is_mock_method and node.args:
                        target = dotted(node.args[0], aliases)
                        if target:
                            method = function.rsplit(".", 1)[1]
                            register(file, target, f"patch.{method}")
                            if (
                                method == "object"
                                and len(node.args) > 1
                                and isinstance(node.args[1], ast.Constant)
                                and isinstance(node.args[1].value, str)
                            ):
                                register(
                                    file,
                                    f"{target}.{node.args[1].value}",
                                    "patch.object",
                                )
                    elif (
                        function in {"importlib.import_module", "__import__"}
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)
                    ):
                        register(file, node.args[0].value, "dynamic_import")
    return [
        {"file": file, "symbol": symbol, "kind": kind}
        for file, symbol, kind in sorted(consumers)
    ]


def compatibility_errors(project_dir: Path, manifest: dict[str, object]) -> list[str]:
    errors: list[str] = []
    entries = _entries(
        manifest.get("compatibility_ledger"), "compatibility_ledger", errors
    )
    symbols = {
        entry.get("entrypoint")
        for entry in entries
        if isinstance(entry.get("entrypoint"), str)
    }
    seen: set[str] = set()
    for entry in entries:
        if set(entry) != REQUIRED_COMPATIBILITY_FIELDS:
            errors.append(
                f"compatibility ledger fields invalid: {entry.get('entrypoint')}"
            )
            continue
        entrypoint = entry["entrypoint"]
        if not all(
            isinstance(entry[field], str) and entry[field]
            for field in REQUIRED_COMPATIBILITY_FIELDS
        ):
            errors.append(f"compatibility ledger values invalid: {entrypoint}")
        elif entrypoint in seen:
            errors.append(f"duplicate compatibility ledger entry: {entrypoint}")
        elif entry["owner"] not in MODULES:
            errors.append(f"unknown compatibility owner: {entrypoint}")
        if isinstance(entrypoint, str):
            seen.add(entrypoint)
    expected = manifest.get("compatibility_consumers")
    if not isinstance(expected, list):
        return errors + ["compatibility_consumers must be a list"]
    actual = _literal_consumers(project_dir, symbols)
    if actual != expected:
        new = [item for item in actual if item not in expected]
        stale = [item for item in expected if item not in actual]
        errors.append(
            "compatibility consumer drift (new or stale consumer): "
            f"new={new} stale={stale}"
        )
    return errors


def database_candidates(project_dir: Path) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    methods = {
        "execute",
        "executemany",
        "executescript",
        "connect",
        "initialize",
        "migrate",
        "seed",
        "initialize_databases",
        "ensure_department_databases",
        "db_session",
        "generate_database",
    }
    for path in sorted((project_dir / "app").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        calls: list[str] = []
        imports: list[str] = []
        tables: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(
                    alias.name for alias in node.names if alias.name == "sqlite3"
                )
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.extend(
                    f"{node.module}.{alias.name}"
                    for alias in node.names
                    if alias.name in {"db_session", "connect", "sqlite3"}
                )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and (node.func.attr in methods or node.func.attr.startswith("seed_"))
            ):
                calls.append(ast.unparse(node.func))
                if (
                    node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    tables.update(
                        value
                        for value in re.findall(
                            r"(?:FROM|INTO|UPDATE|TABLE)\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?([A-Za-z_][\w.]*)",
                            node.args[0].value,
                            re.IGNORECASE,
                        )
                        if value.upper() not in {"SET", "IF", "SELECT"}
                    )
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and (node.func.id in methods or node.func.id.startswith("seed_"))
            ):
                calls.append(node.func.id)
        if calls or imports:
            candidates.append(
                {
                    "source_file": path.relative_to(project_dir).as_posix(),
                    "imports": sorted(set(imports)),
                    "calls": sorted(set(calls)),
                    "table_hints": sorted(tables),
                    "manual_review": "SQL hints are incomplete; dynamic SQL and injected callables require review",
                }
            )
    return candidates


def database_errors(project_dir: Path, manifest: dict[str, object]) -> list[str]:
    expected = manifest.get("database_candidates")
    if not isinstance(expected, list):
        return ["database_candidates must be a list"]
    errors = (
        []
        if database_candidates(project_dir) == expected
        else ["database candidate drift"]
    )
    ledger = manifest.get("database_ledger")
    if not isinstance(ledger, dict) or not isinstance(ledger.get("sources"), list):
        return errors + ["database_ledger.sources must be a list"]
    records = ledger["sources"]
    sources = {
        item["source_file"]
        for item in records
        if isinstance(item, dict) and isinstance(item.get("source_file"), str)
    }
    actual_sources = {
        item["source_file"]
        for item in expected
        if isinstance(item, dict) and isinstance(item.get("source_file"), str)
    }
    if sources != actual_sources:
        errors.append("database ledger source coverage drift")
    if len(sources) != len(records):
        errors.append("duplicate or invalid database ledger source")
    owners = {
        item["path"]: item.get("primary_module")
        for item in manifest.get("files", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    classifications = {
        "internal-store",
        "mixed-startup",
        "modelcatalog-internal",
        "mixed-diagnostic",
        "storage-binding",
        "knowledge-read",
        "bootstrap-init",
        "business-read",
        "demo-init",
        "mixed-global-init",
    }
    for item in records:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(field), str) and item[field]
            for field in (
                "source_file",
                "owner",
                "classification",
                "stores",
                "exit_task",
                "init_effects",
            )
        ):
            errors.append("database ledger record incomplete")
            continue
        if item["owner"] not in MODULES or item["owner"] != owners.get(
            item["source_file"]
        ):
            errors.append(f"database ledger owner mismatch: {item['source_file']}")
        if item["classification"] not in classifications:
            errors.append(f"unknown database classification: {item['source_file']}")
    return errors


def validate(project_dir: Path, manifest: dict[str, object]) -> list[str]:
    errors = ownership_errors(project_dir, manifest)
    if errors:
        return errors
    return (
        dependency_errors(project_dir, manifest)
        + portable_errors(project_dir, manifest)
        + compatibility_errors(project_dir, manifest)
        + database_errors(project_dir, manifest)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        errors = validate(PROJECT_DIR, manifest)
    except (ValueError, OSError, SyntaxError) as error:
        errors = [str(error)]
    report = {
        "schema_version": 1,
        "ok": not errors,
        "errors": errors,
        "counts": {"app_files": len(app_files(PROJECT_DIR))},
    }
    if args.report:
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(
        f"MOD-003 boundaries: files={report['counts']['app_files']} errors={len(errors)}"
    )
    for error in errors:
        print(f"ERROR: {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
