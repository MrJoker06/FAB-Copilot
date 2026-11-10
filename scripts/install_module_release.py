"""Standalone installer for a complete MOD-024 source cohort."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

MANIFEST = "module-release.json"
PART = "module-artifact.json"
MAX_FILES = 1024
MAX_BYTES = 8_000_000


def fail(message: str) -> None:
    raise ValueError("module release is invalid: " + message)


def safe(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        fail("unsafe path")
    p = PurePosixPath(value)
    allowed = {".py", ".md", ".json"} | (
        {".css", ".html", ".js"} if p.parts[:2] == ("app", "static") else set()
    )
    if (
        p.is_absolute()
        or p.parts[:1] != ("app",)
        or str(p) != value
        or ".." in p.parts
        or p.suffix not in allowed
        or any(
            x in {".pth", ".env", "data", "logs", "runtime", "credentials"}
            for x in p.parts
        )
    ):
        fail("unsafe member")
    return p


def read(
    delivery: Path, profiles: list[str]
) -> tuple[dict, list[tuple[PurePosixPath, bytes]]]:
    release = json.loads((delivery / MANIFEST).read_text(encoding="utf-8"))
    if release.get("schema_version") != 1 or not isinstance(
        release.get("profiles"), dict
    ):
        fail("metadata")
    if not profiles or any(p not in release["profiles"] for p in profiles):
        fail("unknown profile")
    wanted = {
        a["filename"]: a
        for a in release.get("archives", [])
        if isinstance(a, dict)
        and isinstance(a.get("filename"), str)
        and PurePosixPath(a["filename"]).name == a["filename"]
        and "\\" not in a["filename"]
        and ":" not in a["filename"]
        and a["filename"].endswith(".zip")
    }
    if len(wanted) != len(release.get("archives", [])):
        fail("unsafe or duplicate archive filename")
    artifacts = [part.get("artifact") for part in wanted.values()]
    if not all(isinstance(item, str) and item for item in artifacts) or len(
        set(artifacts)
    ) != len(artifacts):
        fail("duplicate or invalid artifact")
    ownership = release.get("ownership", {})
    if not isinstance(ownership, dict) or not ownership:
        fail("missing ownership")
    for profile in release["profiles"].values():
        sources = profile.get("source_files", [])
        resources = profile.get("resource_files", [])
        if (
            not isinstance(sources, list)
            or not isinstance(resources, list)
            or not sources
        ):
            fail("invalid profile members")
        selected = sources + resources
        if len(set(selected)) != len(selected):
            fail("duplicate profile member")
        for name in selected:
            path = safe(name)
            if name not in ownership:
                fail("unknown profile member")
            if name in sources and path.suffix != ".py":
                fail("non Python source")
            if name in sources:
                for parent in path.parents:
                    if parent == PurePosixPath("."):
                        break
                    if str(parent / "__init__.py") not in sources:
                        fail("missing package anchor")
    required = {
        x
        for p in profiles
        for x in release["profiles"][p].get("required_artifacts", [])
    }
    if required != {a.get("artifact") for a in wanted.values()}:
        fail("incomplete cohort")
    result = []
    seen = set()
    folded = set()
    for filename, part in wanted.items():
        with zipfile.ZipFile(delivery / filename) as z:
            infos = z.infolist()
            names = [x.filename for x in infos]
            if (
                len(infos) > MAX_FILES
                or sum(x.file_size for x in infos) > MAX_BYTES
                or len(names) != len(set(names))
                or PART not in names
            ):
                fail("archive shape")
            meta = json.loads(z.read(PART).decode("utf-8"))
            mode = z.getinfo(PART).external_attr >> 16
            if stat.S_IFMT(mode) != stat.S_IFREG or stat.S_IMODE(mode) != 0o644:
                fail("unsafe metadata member")
            if (
                meta.get("cohort") != release.get("cohort")
                or meta.get("version") != release.get("version")
                or meta.get("artifact") != part.get("artifact")
                or meta.get("members") != part.get("members")
            ):
                fail("cohort mismatch")
            if set(names) != {PART, *part["members"]}:
                fail("member mismatch")
            for name in part["members"]:
                p = safe(name)
                info = z.getinfo(name)
                mode = info.external_attr >> 16
                if (
                    stat.S_ISLNK(mode)
                    or stat.S_IFMT(mode) != stat.S_IFREG
                    or stat.S_IMODE(mode) != 0o644
                    or name in seen
                    or name.casefold() in folded
                    or release.get("ownership", {}).get(name) != part.get("artifact")
                ):
                    fail("unsafe or duplicate member")
                data = z.read(name)
                if b"\r" in data or not data.endswith(b"\n"):
                    fail("non LF source")
                data.decode("utf-8")
                if p.suffix == ".py":
                    compile(data, name, "exec")
                seen.add(name)
                folded.add(name.casefold())
                result.append((p, data))
    if seen != set(release.get("ownership", {})):
        fail("ownership mismatch")
    return release, result


def preflight_lock(
    release: dict,
    profiles: list[str],
    wheelhouse: Path | None,
    python: Path | None,
    target: Path | None = None,
) -> list[str]:
    locks = release.get("environment_locks", {})
    if python is None or not python.is_file():
        fail("--target-python is required")
    probe = subprocess.check_output(
        [
            str(python),
            "-I",
            "-c",
            "import json,platform,sys,sysconfig;print(json.dumps([sys.platform,platform.machine(),sys.implementation.name,sys.version.split()[0],sysconfig.get_config_var('SOABI'),sysconfig.get_paths()['purelib'],sys.prefix,sys.base_prefix]))",
        ],
        text=True,
    )
    platform, machine, implementation, version, abi, purelib, prefix, base_prefix = (
        json.loads(probe)
    )
    if prefix == base_prefix:
        fail("target Python must belong to a fresh virtual environment")
    configuration = (Path(prefix) / "pyvenv.cfg").read_text(encoding="utf-8").lower()
    if "include-system-site-packages = false" not in configuration:
        fail("target virtual environment inherits system packages")
    if target is not None and Path(purelib).resolve() != target.resolve():
        fail("target site-packages does not belong to target Python")
    current = f"{platform}|{version}"
    lock = next(
        (
            x
            for x in locks.values()
            if x.get("platform") == platform
            and x.get("machine") == machine
            and x.get("python_version") == version
            and x.get("python_implementation") == "CPython"
            and implementation == "cpython"
            and x.get("abi") == abi
        ),
        None,
    )
    if lock is None:
        fail("unsupported target lock: " + current)
    deps = set()
    for profile in profiles:
        locked = lock.get("profiles", {}).get(profile)
        expected = release["profiles"][profile].get("external_dependencies")
        if (
            not isinstance(locked, list)
            or not isinstance(expected, list)
            or set(locked) != set(expected)
        ):
            fail("missing or inconsistent profile dependency lock")
        if any(
            not isinstance(item, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+", item)
            for item in locked
        ):
            fail("dependencies require exact pins")
        deps.update(locked)
    packages = [re.sub(r"[-_.]+", "-", item.split("==")[0]).lower() for item in deps]
    if len(set(packages)) != len(packages):
        fail("conflicting dependency pins")
    if deps:
        if python is None or not python.is_file():
            fail("target Python is required for external dependencies")
        if wheelhouse is None or not wheelhouse.is_dir():
            fail("offline wheelhouse is required")
        names = {x.name.lower() for x in wheelhouse.glob("*.whl")}
        for dep in deps:
            package, version = dep.split("==", 1)
            prefixes = {
                package.lower() + "-" + version + "-",
                package.replace("_", "-").lower() + "-" + version + "-",
            }
            if not any(any(n.startswith(prefix) for prefix in prefixes) for n in names):
                fail("missing offline wheel: " + dep)
    return sorted(deps)


def _pip(
    python: Path, target: Path, wheelhouse: Path, deps: list[str], dry_run: bool
) -> None:
    command = [
        str(python),
        "-I",
        "-m",
        "pip",
        "--isolated",
        "install",
        "--no-index",
        "--find-links",
        str(wheelhouse),
        "--ignore-installed",
        "--only-binary",
        ":all:",
        "--no-cache-dir",
        "--disable-pip-version-check",
    ]
    try:
        with tempfile.TemporaryDirectory(prefix="module-pip-report-") as raw:
            report = Path(raw) / "report.json"
            if dry_run:
                command.extend(["--dry-run", "--report", str(report)])
            else:
                command.extend(["--no-deps", "--target", str(target)])
            command.extend(deps)
            subprocess.run(
                command,
                check=True,
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
                    "WINDIR": os.environ.get("WINDIR", ""),
                },
            )
            if dry_run:
                resolved = json.loads(report.read_text(encoding="utf-8"))["install"]
                normalize = lambda name: re.sub(r"[-_.]+", "-", name).lower()
                actual = {
                    normalize(item["metadata"]["name"])
                    + "=="
                    + item["metadata"]["version"]
                    for item in resolved
                }
                expected = {
                    normalize(item.split("==")[0]) + "==" + item.split("==")[1]
                    for item in deps
                }
                if actual != expected or len(resolved) != len(deps):
                    fail("offline resolved dependencies differ from locked BOM")
                if any(
                    not item["download_info"]["url"].startswith("file:")
                    for item in resolved
                ):
                    fail("nonlocal dependency source")
    except (OSError, subprocess.CalledProcessError) as exc:
        fail("offline dependency resolution failed: " + str(exc))


def install(
    delivery: Path,
    target: Path,
    profiles: list[str],
    wheelhouse: Path | None = None,
    python: Path | None = None,
) -> None:
    release, members = read(delivery, profiles)
    target = target.resolve()
    deps = preflight_lock(release, profiles, wheelhouse, python, target)
    existing = {x.name for x in target.iterdir()} if target.is_dir() else set()
    if (
        not target.is_dir()
        or (target / "app").exists()
        or any(
            not (
                x
                in {
                    "pip",
                    "setuptools",
                    "pkg_resources",
                    "_distutils_hack",
                    "distutils-precedence.pth",
                }
                or x.startswith(("pip-", "setuptools-"))
            )
            for x in existing
        )
    ):
        fail("target site-packages has foreign install")
    if deps:
        _pip(python, target, wheelhouse, deps, True)  # type: ignore[arg-type]
    stage = Path(tempfile.mkdtemp(prefix="module-release-", dir=target))
    try:
        selected = {
            item
            for profile in profiles
            for item in release["profiles"][profile]["source_files"]
        }
        selected.update(
            item
            for profile in profiles
            for item in release["profiles"][profile].get("resource_files", [])
        )
        for p, data in members:
            if str(p) not in selected:
                continue
            out = stage / p
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
        if deps:
            _pip(python, stage, wheelhouse, deps, False)  # type: ignore[arg-type]
        children = list(stage.iterdir())
        if any((target / x.name).exists() for x in children):
            fail("destination collision")
        moved = []
        try:
            for child in children:
                child.rename(target / child.name)
                moved.append(target / child.name)
        except Exception:
            for child in reversed(moved):
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def main() -> int:
    q = argparse.ArgumentParser()
    q.add_argument("--delivery", type=Path, required=True)
    q.add_argument("--target-site-packages", type=Path)
    q.add_argument("--target-python", type=Path)
    q.add_argument("--profiles", nargs="+", required=True)
    q.add_argument("--wheelhouse", type=Path)
    q.add_argument("--verify", action="store_true")
    a = q.parse_args()
    if not a.target_site_packages and not a.verify:
        q.error("--target-site-packages is required for installation")
    if a.verify:
        release, members = read(a.delivery, a.profiles)
        deps = preflight_lock(
            release, a.profiles, a.wheelhouse, a.target_python, a.target_site_packages
        )
        if deps:
            _pip(a.target_python, a.target_site_packages, a.wheelhouse, deps, True)
    else:
        install(
            a.delivery,
            a.target_site_packages,
            a.profiles,
            a.wheelhouse,
            a.target_python,
        )
        _, members = read(a.delivery, a.profiles)
    print(json.dumps({"members": len(members), "profiles": a.profiles}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
