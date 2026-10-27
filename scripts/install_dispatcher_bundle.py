"""Install the declared dispatcher pilot source bundle into an empty site-packages."""

from __future__ import annotations

import argparse
import json
import shutil
import stat
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

_MANIFEST = "portable-unit.json"
_UNIT = "dispatcher_pilot"
_VERSION = "1.0.0"
_MAX_FILES = 128
_MAX_BYTES = 2_000_000


def _fail() -> None:
    raise ValueError("dispatcher bundle is invalid")


def _path(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        _fail()
    path = PurePosixPath(value)
    if (
        str(path) != value
        or path.is_absolute()
        or ".." in path.parts
        or path.parts[:1] != ("app",)
        or path.suffix != ".py"
        or any(not part.isidentifier() for part in path.parts[:-1])
        or not path.stem.isidentifier()
    ):
        _fail()
    if (
        any(part in {".env", "data", "logs"} for part in path.parts)
        or path.name == ".pth"
    ):
        _fail()
    return path


def _read_bundle(bundle: Path) -> list[tuple[PurePosixPath, bytes]]:
    try:
        with zipfile.ZipFile(bundle) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if (
                len(infos) > _MAX_FILES + 1
                or sum(item.file_size for item in infos) > _MAX_BYTES
                or len(names) != len(set(names))
                or _MANIFEST not in names
            ):
                _fail()
            manifest_info = archive.getinfo(_MANIFEST)
            manifest_mode = manifest_info.external_attr >> 16
            if (
                stat.S_ISLNK(manifest_mode)
                or stat.S_IFMT(manifest_mode) != stat.S_IFREG
                or stat.S_IMODE(manifest_mode) != 0o644
            ):
                _fail()
            metadata = json.loads(archive.read(_MANIFEST).decode("utf-8"))
            if (
                not isinstance(metadata, dict)
                or type(metadata.get("schema_version")) is not int
                or metadata.get("schema_version") != 1
                or metadata.get("unit") != _UNIT
                or metadata.get("version") != _VERSION
                or metadata.get("external_dependencies") != []
            ):
                _fail()
            files = metadata.get("files")
            if not isinstance(files, list) or not files or len(files) > _MAX_FILES:
                _fail()
            declared = [_path(item) for item in files]
            anchors = {PurePosixPath("app/__init__.py")}
            for item in declared:
                parent = item.parent
                while parent != PurePosixPath("."):
                    anchors.add(parent / "__init__.py")
                    parent = parent.parent
            if (
                not anchors <= set(declared)
                or len(declared) != len(set(declared))
                or set(names) != {_MANIFEST, *(str(item) for item in declared)}
            ):
                _fail()
            output: list[tuple[PurePosixPath, bytes]] = []
            total = 0
            for relative in declared:
                info = archive.getinfo(str(relative))
                mode = info.external_attr >> 16
                if (
                    stat.S_ISLNK(mode)
                    or stat.S_IFMT(mode) != stat.S_IFREG
                    or stat.S_IMODE(mode) != 0o644
                ):
                    _fail()
                data = archive.read(info)
                total += len(data)
                if total > _MAX_BYTES or b"\r" in data:
                    _fail()
                text = data.decode("utf-8")
                compile(text, str(relative), "exec")
                output.append((relative, data))
            return output
    except (
        OSError,
        RuntimeError,
        TypeError,
        AttributeError,
        UnicodeDecodeError,
        SyntaxError,
        json.JSONDecodeError,
        zipfile.BadZipFile,
        KeyError,
        ValueError,
    ):
        raise ValueError("dispatcher bundle is invalid") from None


def install(bundle: Path, target: Path) -> int:
    files = _read_bundle(bundle)
    target = target.resolve()
    if not target.is_dir() or target == target.parent:
        raise ValueError("installation target is invalid")
    destination = target / "app"
    if destination.exists() or destination.is_symlink():
        raise ValueError("installation target already contains app")
    stage = Path(tempfile.mkdtemp(prefix="dispatcher-bundle-", dir=target))
    try:
        root = stage / "app"
        for relative, data in files:
            output = stage.joinpath(*relative.parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
            output.chmod(0o644)
        if destination.exists() or destination.is_symlink():
            raise ValueError("installation target already contains app")
        root.rename(destination)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    print(f"installed {_UNIT} {_VERSION} ({len(files)} files)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        return install(args.bundle, args.target)
    except (OSError, RuntimeError, TypeError, AttributeError, ValueError):
        print("dispatcher bundle installation failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
