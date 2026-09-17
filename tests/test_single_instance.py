from __future__ import annotations

from app.utils.single_instance import SingleInstanceLock


def test_single_instance_lock_blocks_second_holder(tmp_path) -> None:
    lock_path = tmp_path / "bot.lock"
    first = SingleInstanceLock(lock_path)
    second = SingleInstanceLock(lock_path)

    try:
        assert first.acquire() is True
        assert second.acquire() is False
    finally:
        first.release()
        second.release()
