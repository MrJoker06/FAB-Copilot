"""Check the REF-027 module ownership baseline and import directions."""
from __future__ import annotations

import argparse
import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = PROJECT_DIR / "evaluations" / "module_boundaries_v1.json"


@dataclass(frozen=True)
class ImportEdge:
    source: str
    target: str
    line: int


def module_name(path: Path, app_dir: Path) -> str:
    relative = path.relative_to(app_dir).with_suffix("")
    parts = relative.parts[:-1] if relative.name == "__init__" else relative.parts
    return "app" + ("." + ".".join(parts) if parts else "")


def imported_modules(path: Path, app_dir: Path) -> list[ImportEdge]:
    """Return statically knowable app imports, including literal importlib calls."""
    source = module_name(path, app_dir)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = source if path.name == "__init__.py" else source.rsplit(".", 1)[0]
    edges: list[ImportEdge] = []

    def add(target: str, line: int) -> None:
        edges.append(ImportEdge(source, target, line))

    def is_app_module(target: str) -> bool:
        if not target.startswith("app."):
            return False
        relative = Path(*target.split("."))
        return (app_dir.parent / relative).with_suffix(".py").is_file() or (app_dir.parent / relative / "__init__.py").is_file()

    def resolve_relative(module: str | None, level: int) -> str:
        base = package.split(".")[: len(package.split(".")) - level + 1]
        return ".".join([*base, *module.split(".")]) if module else ".".join(base)

    def resolve_from_package(relative: str, supplied_package: str) -> str:
        levels = len(relative) - len(relative.lstrip("."))
        suffix = relative.lstrip(".")
        base = supplied_package.split(".")[: len(supplied_package.split(".")) - levels + 1]
        return ".".join([*base, *suffix.split(".")]) if suffix else ".".join(base)

    importlib_aliases = {"importlib"}
    import_module_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            importlib_aliases.update(
                alias.asname or alias.name for alias in node.names if alias.name == "importlib"
            )
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            import_module_aliases.update(
                alias.asname or alias.name for alias in node.names if alias.name == "import_module"
            )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.name, node.lineno)
        elif isinstance(node, ast.ImportFrom):
            target = resolve_relative(node.module, node.level) if node.level else node.module
            if target:
                add(target, node.lineno)
            # ``from . import main`` and ``from app import main`` refer to a
            # concrete submodule when the imported name is a module path.
            if target and target.startswith("app"):
                for alias in node.names:
                    child_target = f"{target}.{alias.name}"
                    if is_app_module(child_target):
                        add(child_target, node.lineno)
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            function = node.func
            is_import_module = (
                isinstance(function, ast.Name) and function.id in import_module_aliases
            ) or (
                isinstance(function, ast.Attribute)
                and function.attr == "import_module"
                and isinstance(function.value, ast.Name)
                and function.value.id in importlib_aliases
            ) or (isinstance(function, ast.Name) and function.id == "__import__")
            if is_import_module:
                target = node.args[0].value
                if target.startswith("."):
                    package_arg = next((keyword.value.value for keyword in node.keywords if keyword.arg == "package" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str)), None)
                    if package_arg is None and len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                        package_arg = node.args[1].value
                    target = resolve_from_package(target, package_arg or package)
                add(target, node.lineno)
    return edges


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, object]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("module boundary manifest schema_version must be 1")
    if not isinstance(manifest.get("root_modules"), dict):
        raise TypeError("module boundary manifest root_modules must be an object")
    return manifest


def is_allowed_exception(edge: ImportEdge, exceptions: list[dict[str, str]]) -> bool:
    return any(
        exception.get("source") == edge.source and exception.get("target") == edge.target
        for exception in exceptions
    )


def boundary_errors(app_dir: Path, manifest: dict[str, object]) -> list[str]:
    root_modules = manifest["root_modules"]
    assert isinstance(root_modules, dict)
    actual_roots = {path.stem for path in app_dir.glob("*.py") if path.name != "__init__.py"}
    errors = [f"root ownership missing: {name}" for name in sorted(actual_roots - set(root_modules))]
    errors.extend(f"stale root ownership: {name}" for name in sorted(set(root_modules) - actual_roots))
    def has_consumer_paths(entry: object) -> bool:
        if not isinstance(entry, dict):
            return False
        consumers = entry.get("consumers")
        return (
            isinstance(consumers, dict)
            and set(consumers) == {"production", "scripts", "tests", "patches"}
            and all(
                isinstance(paths, list)
                and all(isinstance(path, str) and path for path in paths)
                for paths in consumers.values()
            )
        )

    package_ownership = manifest.get("package_ownership")
    if not isinstance(package_ownership, dict) or not all(package_ownership.get(field) for field in ("target", "compatibility", "exit_condition")) or not has_consumer_paths(package_ownership):
        errors.append("package ownership incomplete: app.__init__")
    for name, entry in root_modules.items():
        if not isinstance(entry, dict) or not all(entry.get(field) for field in ("target", "compatibility", "exit_condition")) or not has_consumer_paths(entry):
            errors.append(f"root ownership incomplete: {name}")

    policy = manifest.get("policy", {})
    assert isinstance(policy, dict)
    forbidden_targets = set(policy.get("forbidden_targets", []))
    pure_modules = set(policy.get("pure_modules", []))
    pure_forbidden = set(policy.get("pure_forbidden_targets", []))
    pure_forbidden_prefixes = tuple(policy.get("pure_forbidden_prefixes", []))
    assembly_modules = set(policy.get("assembly_modules", []))
    canonical_value = manifest.get("canonical_modules", {})
    allowed_dependencies_value = manifest.get("allowed_domain_dependencies", {})
    canonical: dict[str, object] = {}
    allowed_dependencies: dict[str, object] = {}
    allowed_dependencies_valid = False
    if not isinstance(canonical_value, dict):
        errors.append("canonical module mapping must be an object")
    elif not all(isinstance(source, str) and source and isinstance(target, str) and target for source, target in canonical_value.items()):
        errors.append("canonical module mapping must use non-empty string keys and values")
    else:
        canonical = canonical_value
    if not isinstance(allowed_dependencies_value, dict):
        errors.append("allowed domain dependencies must be an object")
    elif not all(
        isinstance(domain, str)
        and domain
        and isinstance(dependencies, list)
        and all(isinstance(dependency, str) and dependency for dependency in dependencies)
        for domain, dependencies in allowed_dependencies_value.items()
    ):
        errors.append("allowed domain dependencies must map non-empty domains to string lists")
    else:
        allowed_dependencies = allowed_dependencies_value
        allowed_dependencies_valid = True
    if canonical and allowed_dependencies_valid:
        canonical_domains = {target.split(".", 1)[0] for target in canonical.values() if isinstance(target, str)}
        for domain in sorted(canonical_domains - set(allowed_dependencies)):
            errors.append(f"allowed domain dependencies missing policy for: {domain}")
    exceptions_value = manifest.get("existing_edge_exceptions", [])
    exceptions: list[dict[str, str]] = []
    if not isinstance(exceptions_value, list):
        errors.append("edge exceptions must be a list")
    else:
        for exception in exceptions_value:
            if not isinstance(exception, dict) or set(exception) != {"source", "target", "reason", "exit_condition"}:
                errors.append("edge exception must contain exact source, target, reason and exit_condition fields")
                continue
            source = exception["source"]
            target = exception["target"]
            if not all(isinstance(value, str) and value and "*" not in value for value in (source, target, exception["reason"], exception["exit_condition"])):
                errors.append("edge exception must use concrete non-empty values")
                continue
            exceptions.append(exception)
    edges = [edge for path in sorted(app_dir.rglob("*.py")) for edge in imported_modules(path, app_dir)]
    actual_edge_pairs = {(edge.source, edge.target) for edge in edges}
    for exception in exceptions:
        source = exception["source"]
        target = exception["target"]
        if (source, target) not in actual_edge_pairs:
            errors.append(f"stale edge exception: {source} -> {target}")
    for edge in edges:
        if is_allowed_exception(edge, exceptions):
            continue
        if edge.source in pure_modules and (edge.target in pure_forbidden or edge.target.startswith(pure_forbidden_prefixes)):
            errors.append(f"{edge.source}:{edge.line}: pure module imports forbidden {edge.target}")
        elif any(edge.target == target or edge.target.startswith(f"{target}.") for target in forbidden_targets) and edge.source not in assembly_modules:
            errors.append(f"{edge.source}:{edge.line}: domain module imports forbidden {edge.target}")
        else:
            source_domain = canonical_domain(edge.source, canonical)
            target_domain = canonical_domain(edge.target, canonical)
            allowed = allowed_dependencies.get(source_domain)
            if source_domain and target_domain and isinstance(allowed, list) and target_domain not in allowed:
                errors.append(f"{edge.source}:{edge.line}: {source_domain} may not depend on {target_domain}")
    return errors


def canonical_domain(module: str, canonical: dict[str, object]) -> str | None:
    """Map legacy and migrated module paths to the manifest's canonical domain."""
    for legacy in sorted(canonical, key=len, reverse=True):
        if module == legacy or module.startswith(f"{legacy}."):
            value = canonical[legacy]
            if isinstance(value, str):
                return value.split(".", 1)[0]
    if module.startswith("app."):
        candidate = module.removeprefix("app.").split(".", 1)[0]
        return candidate if candidate in {str(value).split(".", 1)[0] for value in canonical.values()} else None
    return None


def consumer_inventory(project_dir: Path = PROJECT_DIR) -> dict[str, dict[str, list[str]]]:
    """Read-only inventory of import and literal patch consumers for every root facade."""
    roots = sorted(path.stem for path in (project_dir / "app").glob("*.py") if path.stem != "__init__")
    inventory = {name: {"production": [], "scripts": [], "tests": [], "patches": []} for name in roots}
    app_dir = project_dir / "app"
    def literal_app_targets(path: Path) -> list[str]:
        """Find absolute app imports in scripts/tests, including literal dynamics."""
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        targets: list[str] = []
        importlib_aliases = {"importlib"}
        import_module_aliases: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                importlib_aliases.update(
                    alias.asname or alias.name for alias in node.names if alias.name == "importlib"
                )
            elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
                import_module_aliases.update(
                    alias.asname or alias.name for alias in node.names if alias.name == "import_module"
                )
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app."):
                        targets.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    if node.module.startswith("app."):
                        targets.append(node.module)
                    elif node.module == "app":
                        targets.extend(f"app.{alias.name}" for alias in node.names)
            elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                function = node.func
                is_import_module = (
                    isinstance(function, ast.Name) and function.id in import_module_aliases
                ) or (
                    isinstance(function, ast.Attribute)
                    and function.attr == "import_module"
                    and isinstance(function.value, ast.Name)
                    and function.value.id in importlib_aliases
                ) or (isinstance(function, ast.Name) and function.id == "__import__")
                if is_import_module:
                    target = node.args[0].value
                    if target.startswith("."):
                        package = next(
                            (keyword.value.value for keyword in node.keywords if keyword.arg == "package" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str)),
                            None,
                        )
                        if package is None and len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                            package = node.args[1].value
                        if package:
                            levels = len(target) - len(target.lstrip("."))
                            base = package.split(".")[: len(package.split(".")) - levels + 1]
                            target = ".".join([*base, target.lstrip(".")])
                    if target.startswith("app."):
                        targets.append(target)
        return targets

    for directory, bucket in ((app_dir, "production"), (project_dir / "scripts", "scripts"), (project_dir / "tests", "tests")):
        for path in sorted(directory.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            relative = str(path.relative_to(project_dir))
            if bucket == "production":
                targets = [edge.target for edge in imported_modules(path, app_dir)]
            else:
                targets = literal_app_targets(path)
            for target in targets:
                parts = target.split(".")
                if len(parts) > 1 and parts[0] == "app" and parts[1] in inventory:
                    inventory[parts[1]][bucket].append(relative)
            for name in roots:
                if re.search(rf"(?:patch|patch\.object)\([^\n]*[\"']app\.{re.escape(name)}(?:\.|[\"'])", text) and relative not in inventory[name]["patches"]:
                    inventory[name]["patches"].append(relative)
    for consumers in inventory.values():
        for bucket, paths in consumers.items():
            consumers[bucket] = sorted(set(paths))
    return inventory


def facade_inventory_errors(project_dir: Path, manifest: dict[str, object]) -> list[str]:
    """Reject internal re-introduction of audited transitional root facades."""
    policy = manifest.get("policy", {})
    if not isinstance(policy, dict) or "internal_facades" not in policy:
        return []
    facades = policy["internal_facades"]
    if not isinstance(facades, list) or not all(isinstance(name, str) and name for name in facades):
        return ["internal facade policy must be a list of non-empty root names"]
    roots = manifest.get("root_modules", {})
    if not isinstance(roots, dict):
        return ["internal facade policy requires root modules"]
    inventory = consumer_inventory(project_dir)
    errors: list[str] = []
    for name in facades:
        entry = roots.get(name)
        if not isinstance(entry, dict) or not isinstance(entry.get("consumers"), dict):
            errors.append(f"internal facade policy missing root ownership: {name}")
            continue
        expected = entry["consumers"]
        actual = inventory.get(name)
        if actual and (actual["production"] or actual["scripts"]):
            errors.append(f"internal facade has production or script consumers: {name}")
        if actual != expected:
            errors.append(f"internal facade consumer inventory stale: {name}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--app-dir", type=Path, default=PROJECT_DIR / "app")
    parser.add_argument("--print-inventory", action="store_true", help="print the read-only consumer and patch audit")
    arguments = parser.parse_args(argv)
    if arguments.print_inventory:
        print(json.dumps(consumer_inventory(arguments.app_dir.parent), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    manifest = load_manifest(arguments.manifest)
    errors = boundary_errors(arguments.app_dir, manifest)
    errors.extend(facade_inventory_errors(arguments.app_dir.parent, manifest))
    if errors:
        print("module boundary check failed:\n" + "\n".join(errors))
        return 1
    print("Module boundary baseline passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
