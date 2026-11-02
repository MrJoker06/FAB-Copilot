"""Small cross-platform, non-blocking runtime-instance locks."""

from __future__ import annotations

import os
import typing
from contextlib import AbstractContextManager
from pathlib import Path


def lock_path(instance_root: Path, runtime_root: Path | None = None) -> Path:
    if os.name == "nt":
        return (
            (runtime_root or instance_root.parent)
            / ".locks"
            / f"{instance_root.name}.lock"
        )
    return instance_root / "service.lock"


class InstanceLock(AbstractContextManager["InstanceLock"]):
    def __init__(self, instance_root: Path, runtime_root: Path | None = None) -> None:
        self.path = lock_path(instance_root, runtime_root)
        self._file: typing.IO[bytes] | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a+b")
        self._file.seek(0, 2)
        if not self._file.tell():
            self._file.write(b"0")
            self._file.flush()
        try:
            if os.name == "nt":
                import msvcrt

                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            self._file.close()
            self._file = None
            return False
        return True

    def release(self) -> None:
        if self._file is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()
            self._file = None

    def __enter__(self) -> typing.Self:
        if not self.acquire():
            raise BlockingIOError(self.path)
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


def is_locked(instance_root: Path, runtime_root: Path | None = None) -> bool:
    lock = InstanceLock(instance_root, runtime_root)
    if not lock.acquire():
        return True
    lock.release()
    return False
