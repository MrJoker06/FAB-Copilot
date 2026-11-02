"""Bounded, link-safe reads from an explicitly selected Skill package root."""

from __future__ import annotations

import os
import stat
import unicodedata
from pathlib import Path

from .contracts import SkillPackageError

MANIFEST_LIMIT = 128 * 1024
RESOURCE_LIMIT = 256 * 1024
AGGREGATE_LIMIT = 1024 * 1024

_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
    "COM¹",
    "COM²",
    "COM³",
    "LPT¹",
    "LPT²",
    "LPT³",
}


def validate_resource_path(value: object) -> tuple[str, ...]:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or "\\" in value
        or ":" in value
        or any(character in value for character in '<>"|?*')
        or value.startswith(("/", "//"))
    ):
        raise SkillPackageError(
            "invalid_resource_path", "resource path is not a canonical relative path"
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise SkillPackageError(
            "invalid_resource_path", "resource path contains control characters"
        )
    parts = tuple(value.split("/"))
    if any(
        not part
        or part in {".", ".."}
        or part.endswith((".", " "))
        or part.upper().split(".", 1)[0] in _RESERVED
        for part in parts
    ):
        raise SkillPackageError(
            "invalid_resource_path", "resource path is not portable"
        )
    if unicodedata.normalize("NFC", value) != value:
        raise SkillPackageError(
            "invalid_resource_path", "resource path is not normalized"
        )
    return parts


def _root(root: Path) -> Path:
    try:
        info = root.lstat()
    except OSError as error:
        raise SkillPackageError(
            "invalid_package", "package root is unavailable"
        ) from error
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise SkillPackageError(
            "invalid_package", "package root must be a real directory"
        )
    return root


def _read_fd(fd: int, limit: int) -> bytes:
    try:
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
    except OSError as error:
        raise SkillPackageError(
            "unsafe_resource", "resource cannot be read safely"
        ) from error
    finally:
        os.close(fd)
    if len(data) > limit:
        raise SkillPackageError(
            "resource_too_large", "resource exceeds the configured size limit"
        )
    return data


def _read_posix(root: Path, parts: tuple[str, ...], limit: int) -> bytes:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    if not getattr(os, "O_NOFOLLOW", None):
        raise SkillPackageError(
            "secure_read_unsupported",
            "secure resource reads are unavailable on this platform",
        )
    try:
        directory = os.open(root, flags)
    except OSError as error:
        raise SkillPackageError(
            "invalid_package", "package root cannot be opened safely"
        ) from error
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = next_fd
        leaf_flags = (
            os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
        )
        fd = os.open(parts[-1], leaf_flags, dir_fd=directory)
    except OSError as error:
        raise SkillPackageError(
            "unsafe_resource", "resource cannot be opened safely"
        ) from error
    finally:
        os.close(directory)
    try:
        info = os.fstat(fd)
    except OSError as error:
        try:
            os.close(fd)
        except OSError:
            pass
        raise SkillPackageError(
            "unsafe_resource", "resource cannot be inspected safely"
        ) from error
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(fd)
        raise SkillPackageError(
            "unsafe_resource", "resource must be a non-linked regular file"
        )
    return _read_fd(fd, limit)


def _read_windows(root: Path, parts: tuple[str, ...], limit: int) -> bytes:
    """Use an opened-handle final-path check; reject unsupported Windows APIs."""
    candidate = root.joinpath(*parts)
    try:
        for item in (root, *candidate.parents):
            if item == root.parent:
                break
            info = item.lstat()
            if (
                stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise SkillPackageError(
                    "unsafe_resource", "resource path contains a link or reparse point"
                )
        leaf_info = candidate.lstat()
        if (
            stat.S_ISLNK(leaf_info.st_mode)
            or getattr(leaf_info, "st_file_attributes", 0) & 0x400
        ):
            raise SkillPackageError(
                "unsafe_resource", "resource path contains a link or reparse point"
            )
        fd = os.open(candidate, os.O_RDONLY | os.O_BINARY)
    except SkillPackageError:
        raise
    except OSError as error:
        raise SkillPackageError(
            "unsafe_resource", "resource cannot be opened safely"
        ) from error
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        handle = msvcrt.get_osfhandle(fd)
        get_final_path = ctypes.windll.kernel32.GetFinalPathNameByHandleW
        get_final_path.argtypes = [
            wintypes.HANDLE,
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        get_final_path.restype = wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(32768)
        length = get_final_path(wintypes.HANDLE(handle), buffer, len(buffer), 0)
        if not length or length >= len(buffer):
            raise SkillPackageError(
                "secure_read_unsupported",
                "secure resource reads are unavailable on this platform",
            )
        final = Path(buffer.value.removeprefix("\\\\?\\")).resolve()
        root_final = root.resolve()
        if root_final not in (final, *final.parents):
            raise SkillPackageError(
                "unsafe_resource", "resource escapes the package root"
            )
        info = os.fstat(fd)
    except SkillPackageError:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    except Exception as error:
        try:
            os.close(fd)
        except OSError:
            pass
        raise SkillPackageError(
            "unsafe_resource", "resource cannot be inspected safely"
        ) from error
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(fd)
        raise SkillPackageError(
            "unsafe_resource", "resource must be a non-linked regular file"
        )
    return _read_fd(fd, limit)


def read_resource_text(
    root: Path, resource_path: str, *, limit: int = RESOURCE_LIMIT
) -> str:
    """Read one declared text resource without following package-local links."""
    root = _root(Path(root))
    parts = validate_resource_path(resource_path)
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or limit < 1
        or limit > AGGREGATE_LIMIT
    ):
        raise SkillPackageError("invalid_limit", "resource limit is invalid")
    data = (
        _read_windows(root, parts, limit)
        if os.name == "nt"
        else _read_posix(root, parts, limit)
    )
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SkillPackageError(
            "invalid_encoding", "resource must be UTF-8 text"
        ) from error
