"""Process-wide single-instance locks so duplicate bots/listeners cannot run side by side."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl


DEFAULT_LOCK_DIR = Path(__file__).resolve().parents[1] / "data"


class InstanceAlreadyRunning(RuntimeError):
    pass


def _try_lock(handle):
    try:
        if os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(handle):
    try:
        if os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


@contextmanager
def single_instance(name, lock_dir=None):
    """Hold an OS-level lock for the life of the block; the OS releases it if the process dies."""
    directory = Path(lock_dir or DEFAULT_LOCK_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / f"{name}.lock"
    pid_path = directory / f"{name}.pid"
    handle = open(lock_path, "a+b")
    try:
        if not _try_lock(handle):
            try:
                owner = pid_path.read_text(encoding="ascii").strip()
            except OSError:
                owner = "unknown"
            raise InstanceAlreadyRunning(
                f"Another {name} instance is already running (PID {owner or 'unknown'}). "
                "Stop it before starting a new one."
            )
        try:
            pid_path.write_text(str(os.getpid()), encoding="ascii")
            yield
        finally:
            _unlock(handle)
    finally:
        handle.close()
