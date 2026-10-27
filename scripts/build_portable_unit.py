"""Build and verify transitional, source-compatible portable unit ZIP bundles."""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = PROJECT_DIR / "evaluations" / "portable_units_v1.json"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "runtime" / "portable"
ARCHIVE_MANIFEST = "portable-unit.json"
FORBIDDEN_TOP_LEVEL = {"data", "logs", "runtime", "backups", ".git"}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".jsonl", ".pem", ".key"}


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("units"), dict):
        raise ValueError("portable unit manifest must use schema_version 1 and define units")
    return data


def safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or ".." in path.parts
        or path.parts[0] in FORBIDDEN_TOP_LEVEL
    ):
        raise ValueError(f"unsafe portable unit path: {value}")
    if path.name == ".env" or path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise ValueError(f"forbidden portable unit path: {value}")
    return path


def safe_archive_component(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "/" in value
        or "\\" in value
        or ".." in value
    ):
        raise ValueError(f"unsafe portable unit {label}: {value}")
    return value


def module_name(relative: PurePosixPath) -> str | None:
    if relative.suffix != ".py" or relative.parts[0] != "app":
        return None
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def resolve_relative(module: str | None, level: int, package: str) -> str:
    base = package.split(".")[: len(package.split(".")) - level + 1]
    suffix = module.split(".") if module else []
    return ".".join([*base, *suffix])


def imported_app_modules(path: Path, relative: PurePosixPath) -> set[str]:
    """Find statically declared app imports, resolving relative import statements."""
    source_module = module_name(relative)
    if source_module is None:
        return set()
    package = source_module if path.name == "__init__.py" else source_module.rsplit(".", 1)[0]
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names if alias.name == "app" or alias.name.startswith("app."))
        elif isinstance(node, ast.ImportFrom):
            target = resolve_relative(node.module, node.level, package) if node.level else node.module
            if target == "app" or (target and target.startswith("app.")):
                imports.add(target)
    return imports


def validate_unit(name: str, definition: Any, project_dir: Path = PROJECT_DIR) -> list[tuple[PurePosixPath, Path]]:
    safe_archive_component(name, "name")
    if not isinstance(definition, dict) or not isinstance(definition.get("version"), str):
        raise ValueError(f"portable unit {name} must define a string version")
    safe_archive_component(definition["version"], "version")
    values = definition.get("files")
    if not isinstance(values, list) or not values or not all(isinstance(value, str) for value in values):
        raise ValueError(f"portable unit {name} must declare a non-empty file list")
    paths = [safe_relative_path(value) for value in values]
    if len(set(paths)) != len(paths):
        raise ValueError(f"portable unit {name} declares duplicate files")
    files: list[tuple[PurePosixPath, Path]] = []
    declared_modules: set[str] = set()
    resolved_project_dir = project_dir.resolve()
    for relative in paths:
        source = project_dir.joinpath(*relative.parts)
        if not source.is_file():
            raise ValueError(f"portable unit {name} is missing declared file: {relative}")
        resolved_source = source.resolve()
        try:
            resolved_source.relative_to(resolved_project_dir)
        except ValueError as exc:
            raise ValueError(
                f"portable unit {name} declared file escapes project root: {relative}"
            ) from exc
        files.append((relative, resolved_source))
        module = module_name(relative)
        if module:
            declared_modules.add(module)
    if "app" not in declared_modules:
        raise ValueError(f"portable unit {name} must include app/__init__.py")
    for relative, source in files:
        for imported in imported_app_modules(source, relative):
            declared = imported == "app" or imported in declared_modules
            if not declared:
                raise ValueError(
                    f"portable unit {name} has undeclared app import {imported} in {relative}"
                )
    return files


def archive_manifest(name: str, definition: dict[str, Any], files: list[tuple[PurePosixPath, Path]]) -> bytes:
    payload = {
        "schema_version": 1,
        "unit": name,
        "version": definition["version"],
        "files": [str(relative) for relative, _source in files],
    }
    dependencies = definition.get("external_dependencies")
    if dependencies is not None:
        payload["external_dependencies"] = dependencies
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_member(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data)


def build_unit(name: str, definition: dict[str, Any], output_dir: Path) -> Path:
    files = validate_unit(name, definition)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{name}-{definition['version']}.zip"
    temporary = destination.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        write_member(archive, ARCHIVE_MANIFEST, archive_manifest(name, definition, files))
        for relative, source in files:
            write_member(archive, str(relative), source.read_bytes())
    temporary.replace(destination)
    return destination


def assert_bundle_imports(root: Path, module: str) -> None:
    source = (
        "import importlib, pathlib, sys\n"
        "root = pathlib.Path.cwd().resolve()\n"
        f"importlib.import_module({module!r})\n"
        "for name, loaded in tuple(sys.modules.items()):\n"
        "    if name == 'app' or name.startswith('app.'):\n"
        "        location = getattr(loaded, '__file__', None)\n"
        "        if location and root not in pathlib.Path(location).resolve().parents and pathlib.Path(location).resolve() != root:\n"
        "            raise SystemExit('app import escaped bundle: ' + name + '=' + location)\n"
    )
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    subprocess.run([sys.executable, "-c", source], cwd=root, env=environment, check=True)


def verify_bundle(archive_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="portable-unit-") as temporary:
        root = Path(temporary)
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            member_names = [member.filename for member in members]
            if len(member_names) != len(set(member_names)):
                raise ValueError("bundle contains duplicate member names")
            for member_name in member_names:
                safe_relative_path(member_name)
            if ARCHIVE_MANIFEST not in member_names:
                raise ValueError("bundle is missing portable-unit.json")
            metadata = json.loads(archive.read(ARCHIVE_MANIFEST).decode("utf-8"))
            if metadata.get("schema_version") != 1:
                raise ValueError("bundle manifest must use schema_version 1")
            if not isinstance(metadata.get("unit"), str) or not isinstance(metadata.get("version"), str):
                raise ValueError("bundle manifest must define unit and version")
            files = metadata.get("files")
            if not isinstance(files, list) or not all(isinstance(path, str) for path in files):
                raise ValueError("bundle manifest must define a file list")
            declared_files = [safe_relative_path(path) for path in files]
            if len(declared_files) != len(set(declared_files)):
                raise ValueError("bundle manifest contains duplicate file paths")
            expected_members = {ARCHIVE_MANIFEST, *(str(path) for path in declared_files)}
            if set(member_names) != expected_members:
                raise ValueError("bundle members do not exactly match portable-unit.json")
            archive.extractall(root)
        unit = metadata["unit"]
        for relative in declared_files:
            if not root.joinpath(*relative.parts).is_file():
                raise ValueError(f"bundle is missing declared file: {relative}")
        if unit == "memory_core":
            assert_bundle_imports(root, "app.memory_system.service")
            environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
            smoke = (
                "import runpy, sys\n"
                "sys.path.insert(0, '.')\n"
                "runpy.run_path('tests/test_memory_system_history.py', run_name='__main__')\n"
            )
            subprocess.run([sys.executable, "-c", smoke], cwd=root, env=environment, check=True)
        elif unit == "decision_core":
            assert_bundle_imports(root, "app.planning_runtime.service")
            smoke = (
                "from scripts import evaluate_playbooks as evaluator\n"
                "report = evaluator.evaluate(evaluator.DEFAULT_DATASET)\n"
                "assert report['passed'] and report['cases'] == 12, report\n"
            )
            environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
            subprocess.run([sys.executable, "-c", smoke], cwd=root, env=environment, check=True)
        elif unit == "model_transport":
            assert_bundle_imports(root, "app.model_gateway.streaming")
            environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
            smoke = (
                "import runpy, sys\n"
                "sys.path.insert(0, '.')\n"
                "runpy.run_path('tests/test_model_transport_portable.py', run_name='__main__')\n"
            )
            subprocess.run([sys.executable, "-c", smoke], cwd=root, env=environment, check=True)
        elif unit == "enterprise_data_contract":
            assert_bundle_imports(root, "app.manufacturing.data_contracts")
            environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
            smoke = (
                "import runpy, sys\n"
                "sys.path.insert(0, '.')\n"
                "runpy.run_path('tests/test_enterprise_data_contract_portable.py', run_name='__main__')\n"
            )
            subprocess.run([sys.executable, "-c", smoke], cwd=root, env=environment, check=True)
        elif unit == "retrieval_policy":
            assert_bundle_imports(root, "app.knowledge.ranking")
            environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
            smoke = (
                "import runpy, sys\n"
                "sys.path.insert(0, '.')\n"
                "runpy.run_path('tests/test_retrieval_policy_portable.py', run_name='__main__')\n"
            )
            subprocess.run([sys.executable, "-c", smoke], cwd=root, env=environment, check=True)
        elif unit == "factory_search_contract":
            assert_bundle_imports(root, "app.knowledge.search_contracts")
            environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
            smoke = (
                "import runpy, sys\n"
                "sys.path.insert(0, '.')\n"
                "runpy.run_path('tests/test_factory_search_contract_portable.py', run_name='__main__')\n"
            )
            subprocess.run([sys.executable, "-c", smoke], cwd=root, env=environment, check=True)
        elif unit == "identity_contract":
            assert_bundle_imports(root, "app.core.identity_contracts")
            environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
            smoke = (
                "import runpy, sys\n"
                "sys.path.insert(0, '.')\n"
                "runpy.run_path('tests/test_identity_contract_portable.py', run_name='__main__')\n"
            )
            subprocess.run([sys.executable, "-c", smoke], cwd=root, env=environment, check=True)
        else:
            raise ValueError(f"unknown portable unit verification: {unit}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("units", nargs="*", help="portable unit names; defaults to every declared unit")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--verify", action="store_true", help="extract each bundle into an isolated temporary directory and smoke test it")
    args = parser.parse_args(argv)
    manifest = load_manifest(args.manifest)
    units = manifest["units"]
    assert isinstance(units, dict)
    names = args.units or sorted(units)
    unknown = sorted(set(names) - set(units))
    if unknown:
        parser.error("unknown portable units: " + ", ".join(unknown))
    for name in names:
        definition = units[name]
        assert isinstance(definition, dict)
        bundle = build_unit(name, definition, args.output_dir)
        if args.verify:
            verify_bundle(bundle)
        print(bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
