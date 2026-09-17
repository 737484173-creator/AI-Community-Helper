from __future__ import annotations

from pathlib import Path


def file_fingerprint(path: str | Path) -> tuple[int, int]:
    file_path = Path(path)
    try:
        stat = file_path.stat()
    except FileNotFoundError:
        return (0, 0)
    return (int(stat.st_mtime_ns), int(stat.st_size))
