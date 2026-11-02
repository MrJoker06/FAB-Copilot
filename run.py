"""Native Windows/Linux launcher for an isolated Fab Insight Agent instance."""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import uuid
from pathlib import Path

from scripts.instance_lock import InstanceLock

PROJECT = Path(__file__).resolve().parent
ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
COPY_TOP_LEVEL = ("app", "knowledge", "cases", "evaluations", "scripts")
COPY_FILES = (
    "requirements.txt",
    "requirements-test.txt",
    ".gitattributes",
    ".editorconfig",
)


def _safe_id(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    return value or "fab"


def _overlaps_source(instance: Path, root: Path) -> bool:
    return (
        instance == root
        or instance in root.parents
        or any(
            directory == instance or directory in instance.parents
            for directory in (root / name for name in COPY_TOP_LEVEL)
        )
    )


def _git_commit(root: Path) -> str | None:
    try:
        top_level = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if Path(top_level).resolve() != root.resolve():
            return None
        return subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _archive_git(root: Path, commit: str, target: Path) -> None:
    result = subprocess.run(
        ["git", "archive", "--format=tar", commit],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("git archive failed")
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
        for member in archive.getmembers():
            path = Path(member.name)
            if (
                member.issym()
                or member.islnk()
                or path.is_absolute()
                or ".." in path.parts
            ):
                raise RuntimeError("unsafe member in source archive")
        for member in archive.getmembers():
            destination = target / member.name
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
            elif member.isreg():
                destination.parent.mkdir(parents=True, exist_ok=True)
                with (
                    archive.extractfile(member) as source,
                    destination.open("wb") as output,
                ):
                    if source is None:
                        raise RuntimeError("archive member has no content")
                    shutil.copyfileobj(source, output)
            else:
                raise RuntimeError("unsafe special file in source archive")


def _copy_export(root: Path, target: Path) -> None:
    for name in COPY_TOP_LEVEL:
        source = root / name
        if source.exists():
            if source.is_symlink():
                raise RuntimeError(f"refusing symlinked source: {name}")
            if any(path.is_symlink() for path in source.rglob("*")):
                raise RuntimeError(f"refusing symlink inside source: {name}")
            shutil.copytree(
                source,
                target / name,
                symlinks=False,
                ignore=shutil.ignore_patterns(
                    "__pycache__", ".pytest_cache", ".ruff_cache"
                ),
            )
    for name in COPY_FILES:
        source = root / name
        if source.is_symlink():
            raise RuntimeError(f"refusing symlinked source file: {name}")
        if source.is_file():
            shutil.copy2(source, target / name)


def _publish_snapshot(staging: Path, source: Path, identity: str) -> None:
    """Publish a complete staging tree, with a DrvFS-safe fallback for directory rename."""
    marker = ".fab-git-commit"
    (staging / marker).write_text(identity + "\n", encoding="utf-8")
    try:
        staging.replace(source)
        return
    except PermissionError:
        if source.exists():
            raise
        created_source = False
        try:
            source.mkdir()
            created_source = True
            for entry in staging.iterdir():
                if entry.name == marker:
                    continue
                destination = source / entry.name
                if entry.is_dir():
                    shutil.copytree(entry, destination, symlinks=False)
                else:
                    shutil.copy2(entry, destination)
            (source / marker).write_text(identity + "\n", encoding="utf-8")
        except Exception:
            if (
                created_source
                and source.exists()
                and source.resolve().parent == source.parent.resolve()
                and source.parent.resolve() == staging.parent.resolve()
            ):
                shutil.rmtree(source, ignore_errors=True)
            raise
    finally:
        if staging.exists() and staging.resolve().parent == source.parent.resolve():
            shutil.rmtree(staging, ignore_errors=True)


def _snapshot(root: Path, instance: Path, commit: str | None) -> tuple[Path, str]:
    source, marker = instance / "source", instance / "source" / ".fab-git-commit"
    identity = commit or "unversioned"
    if source.exists():
        if source.is_symlink() or source.resolve().parent != instance.resolve():
            raise RuntimeError("Source snapshot is outside its instance")
        if not marker.is_file():
            raise RuntimeError("Source snapshot is incomplete")
        if marker.read_text(encoding="utf-8").strip() != identity:
            raise ValueError("Source snapshot commit does not match requested commit")
        return source.resolve(), identity
    instance.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".source-", dir=instance))
    try:
        _archive_git(root, commit, temp) if commit else _copy_export(root, temp)
        _publish_snapshot(temp, source, identity)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return source.resolve(), identity


def _environment(
    root: Path, instance: Path, instance_id: str, source: Path, identity: str, mode: str
) -> dict[str, str]:
    departments = instance / "data" / "departments"
    env = os.environ.copy()
    env.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "FAB_INSTANCE_ID": instance_id,
            "FAB_INSTANCE_ROOT": str(instance),
            "FAB_SOURCE_ROOT": str(source),
            "FAB_GIT_COMMIT": identity,
            "FAB_SOURCE_MODE": mode,
            "FAB_WORKSPACE_ENV_FILE": env.get(
                "FAB_WORKSPACE_ENV_FILE", str(root.parent.parent / ".env")
            ),
            "FAB_PROJECT_ENV_FILE": env.get("FAB_PROJECT_ENV_FILE", str(root / ".env")),
            "FAB_DATABASE_PATH": str(instance / "data" / "fab_history.db"),
            "FAB_DATABASE_DIR": str(departments),
            "FAB_MANUFACTURING_DATABASE_PATH": str(
                departments / "manufacturing_operations.db"
            ),
            "FAB_EQUIPMENT_DATABASE_PATH": str(
                departments / "equipment_engineering.db"
            ),
            "FAB_QUALITY_DATABASE_PATH": str(departments / "yield_quality.db"),
            "FAB_KNOWLEDGE_DATABASE_PATH": str(departments / "process_knowledge.db"),
            "FAB_AGENT_DATABASE_PATH": str(departments / "ai_operations.db"),
            "FAB_PERSONAL_KNOWLEDGE_STORAGE_PATH": str(
                instance / "data" / "personal_knowledge"
            ),
            "AGENT_LOG_PATH": str(instance / "logs" / "agent_events.jsonl"),
            "AGENT_RUN_LOG_DIR": str(instance / "logs" / "agent"),
        }
    )
    return env


def _run_child(command: list[str], source: Path, environment: dict[str, str]) -> int:
    watched = [signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):
        watched.append(signal.SIGBREAK)
    previous = {item: signal.getsignal(item) for item in watched}

    def cancel(_: int, __: object) -> None:
        raise KeyboardInterrupt

    child: subprocess.Popen[bytes] | None = None
    try:
        for item in watched:
            signal.signal(item, cancel)
        child = subprocess.Popen(command, cwd=source, env=environment)
        return child.wait()
    except BaseException:
        if child is not None and child.poll() is None:
            child.terminate()
        try:
            if child is not None:
                child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if child is not None:
                child.kill()
                child.wait()
        if isinstance(sys.exc_info()[1], KeyboardInterrupt):
            return 130
        raise
    finally:
        for item, handler in previous.items():
            signal.signal(item, handler)


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 11):
        print(
            "Python 3.11+ is required. Set FAB_PYTHON or create a project virtual environment.",
            file=sys.stderr,
        )
        return 2
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=os.getenv("PORT", "8888"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--source-mode", choices=("snapshot", "worktree"), default="snapshot"
    )
    parser.add_argument("--seed-days", type=int, default=730)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535 or args.seed_days <= 0 or not args.host:
        print("port, host and seed-days are invalid", file=sys.stderr)
        return 2
    required = (
        "fastapi",
        "uvicorn",
        "httpx",
        "pydantic",
        "multipart",
        "pypdf",
        "docx",
        "openpyxl",
        "rapidocr",
        "onnxruntime",
        "fitz",
        "PIL",
    )
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE VIRTUAL TABLE probe USING fts5(value, tokenize='trigram')"
        )
    except sqlite3.Error:
        missing.append("SQLite FTS5 trigram")
    finally:
        if connection is not None:
            connection.close()
    if missing:
        print(
            f"Missing runtime dependencies: {', '.join(missing)}. Install requirements.txt in the selected Python environment.",
            file=sys.stderr,
        )
        return 2
    root, commit = PROJECT.resolve(), _git_commit(PROJECT)
    requested_root = os.getenv("FAB_INSTANCE_ROOT")
    instance_id = os.getenv("FAB_INSTANCE_ID") or (
        _safe_id(Path(requested_root).name)
        if requested_root
        else f"{_safe_id(root.name)}-{commit or 'unversioned-' + uuid.uuid4().hex[:12]}-{args.port}-{os.name}"
    )
    if not ID_RE.fullmatch(instance_id):
        print(
            "FAB_INSTANCE_ID only allows letters, numbers, dots, underscores and hyphens.",
            file=sys.stderr,
        )
        return 2
    instance = Path(requested_root or root / "runtime" / instance_id).resolve()
    if _overlaps_source(instance, root):
        print("FAB_INSTANCE_ROOT must not overlap the project source.", file=sys.stderr)
        return 2
    if args.check:
        print(
            json.dumps(
                {
                    "python": sys.executable,
                    "python_version": sys.version.split()[0],
                    "platform": os.name,
                    "project": str(root),
                    "instance_root": str(instance),
                    "git_commit": commit,
                    "source_mode": args.source_mode,
                },
                ensure_ascii=False,
            )
        )
        return 0
    lock = InstanceLock(instance, instance.parent)
    if not lock.acquire():
        print(
            f"Instance '{instance_id}' is already running: {instance}", file=sys.stderr
        )
        return 3
    try:
        manifest = instance / "instance.json"
        if manifest.exists():
            try:
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise TypeError("manifest must be an object")
                if payload.get("platform", "posix") != os.name:
                    print("Instance belongs to a different platform.", file=sys.stderr)
                    return 2
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                print("Instance manifest is invalid.", file=sys.stderr)
                return 4
        try:
            if args.source_mode == "snapshot":
                source, identity = _snapshot(root, instance, commit)
            else:
                instance.mkdir(parents=True, exist_ok=True)
                source, identity = root, commit or "worktree"
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 5
        except (OSError, RuntimeError, shutil.Error, tarfile.TarError) as error:
            print(f"Failed to create source snapshot: {error}", file=sys.stderr)
            return 4
        for directory in (
            instance / "data" / "departments",
            instance / "data" / "personal_knowledge",
            instance / "logs" / "agent",
        ):
            directory.mkdir(parents=True, exist_ok=True)
        env = _environment(
            root, instance, instance_id, source, identity, args.source_mode
        )
        manifest.write_text(
            json.dumps(
                {
                    "instance_id": instance_id,
                    "git_commit": identity,
                    "port": args.port,
                    "worktree": str(root),
                    "source_root": str(source),
                    "platform": os.name,
                    "source_mode": args.source_mode,
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"Python: {sys.executable}")
        print(f"Runtime root: {instance}")
        print(f"Source mode: {args.source_mode}")
        print(f"Source root: {source}")
        print(f"URL: http://{args.host}:{args.port}")
        result = _run_child(
            [
                sys.executable,
                "-m",
                "app.manufacturing.seed",
                "--days",
                str(args.seed_days),
            ],
            source,
            env,
        )
        if result:
            return result
        return _run_child(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                args.host,
                "--port",
                str(args.port),
            ],
            source,
            env,
        )
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
