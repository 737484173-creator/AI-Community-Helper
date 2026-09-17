from __future__ import annotations

from pathlib import Path


class SingleInstanceLock:
    def __init__(self, lock_path: str | Path) -> None:
        self.lock_path = Path(lock_path)
        self._handle = None

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        if self.lock_path.exists():
            handle = self.lock_path.open("r+b")
        else:
            handle = self.lock_path.open("w+b")

        try:
            if _lock_file(handle):
                handle.seek(0)
                handle.write(b"1")
                handle.truncate(1)
                handle.flush()
                self._handle = handle
                return True
        except OSError:
            pass

        handle.close()
        return False

    def release(self) -> None:
        if not self._handle:
            return

        try:
            _unlock_file(self._handle)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> "SingleInstanceLock":
        if not self.acquire():
            raise RuntimeError(f"Another instance is already running: {self.lock_path}")
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()


def _lock_file(handle) -> bool:
    if _is_windows():
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return True

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    return True


def _unlock_file(handle) -> None:
    if _is_windows():
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _is_windows() -> bool:
    import os

    return os.name == "nt"
