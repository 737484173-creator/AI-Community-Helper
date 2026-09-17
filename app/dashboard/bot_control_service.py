from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from app.utils.single_instance import SingleInstanceLock
from config.settings import BASE_DIR, Settings


@dataclass(frozen=True)
class BotStatus:
    is_running: bool
    can_start: bool
    can_stop: bool
    pid: int | None
    label: str
    detail: str


class BotControlService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.lock_path = settings.db_path.parent / "discord_bot.lock"
        self.pid_path = settings.db_path.parent / "discord_bot.pid"
        self.stdout_path = BASE_DIR / "logs" / "discord_bot.out.log"
        self.stderr_path = BASE_DIR / "logs" / "discord_bot.err.log"

    def status(self) -> BotStatus:
        pid = self._read_pid()
        pid_running = pid is not None and self._pid_exists(pid)
        if pid is not None and not pid_running:
            self._remove_stale_pid()
        lock_running = self._lock_is_held()
        is_running = pid_running or lock_running

        if not self.settings.discord_bot_token:
            return BotStatus(
                is_running=is_running,
                can_start=False,
                can_stop=pid_running,
                pid=pid if pid_running else None,
                label="未配置",
                detail="缺少 DISCORD_BOT_TOKEN，无法启动 Discord Bot。",
            )

        if pid_running:
            return BotStatus(
                is_running=True,
                can_start=False,
                can_stop=True,
                pid=pid,
                label="运行中",
                detail=f"Dashboard 启动的 Bot 正在运行，PID {pid}。",
            )

        if lock_running:
            return BotStatus(
                is_running=True,
                can_start=False,
                can_stop=False,
                pid=None,
                label="运行中",
                detail="检测到 Discord Bot 单实例锁，可能由终端或其他进程启动。",
            )

        return BotStatus(
            is_running=False,
            can_start=True,
            can_stop=False,
            pid=None,
            label="已停止",
            detail="Discord Bot 当前未运行。",
        )

    def start(self) -> BotStatus:
        current = self.status()
        if not current.can_start:
            return current

        self.stdout_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        stdout = open(self.stdout_path, "a", encoding="utf-8")
        stderr = open(self.stderr_path, "a", encoding="utf-8")
        process = subprocess.Popen(
            [sys.executable, "manage.py", "bot"],
            cwd=BASE_DIR,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            close_fds=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
        )
        self.pid_path.write_text(str(process.pid), encoding="utf-8")
        time.sleep(1)
        if process.poll() is not None:
            self._remove_stale_pid()
            return BotStatus(
                is_running=False,
                can_start=True,
                can_stop=False,
                pid=None,
                label="启动失败",
                detail=self._latest_error_detail(),
            )
        return self.status()

    def stop(self) -> BotStatus:
        current = self.status()
        if not current.can_stop or current.pid is None:
            return current

        subprocess.run(
            ["taskkill", "/PID", str(current.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        if self.pid_path.exists():
            self.pid_path.unlink()
        return self.status()

    def _read_pid(self) -> int | None:
        if not self.pid_path.exists():
            return None
        try:
            return int(self.pid_path.read_text(encoding="utf-8-sig").strip())
        except ValueError:
            return None

    def _remove_stale_pid(self) -> None:
        try:
            if self.pid_path.exists():
                self.pid_path.unlink()
        except OSError:
            pass

    def _latest_error_detail(self) -> str:
        if not self.stderr_path.exists():
            return "Discord Bot 启动后立即退出，请检查网络、Token 和权限。"
        try:
            lines = [
                line.strip()
                for line in self.stderr_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                if line.strip()
            ]
        except OSError:
            return "Discord Bot 启动后立即退出，请检查网络、Token 和权限。"
        for line in reversed(lines):
            if "Cannot connect to host discord.com:443" in line:
                return "无法连接 discord.com:443，当前网络或系统权限阻止 Bot 登录 Discord。"
            if "LoginFailure" in line or "Improper token" in line:
                return "Discord Bot Token 无效，请检查 DISCORD_BOT_TOKEN。"
        return lines[-1] if lines else "Discord Bot 启动后立即退出，请检查网络、Token 和权限。"

    def _pid_exists(self, pid: int) -> bool:
        if os.name == "nt":
            # Starting PowerShell for every dashboard rerun costs roughly a
            # second on Windows. Query the process through the Win32 API so
            # sidebar navigation does not wait on a child process.
            import ctypes
            from ctypes import wintypes

            process_query_limited_information = 0x1000
            still_active = 259
            error_access_denied = 5
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel32.CloseHandle.restype = wintypes.BOOL

            handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
            if not handle:
                # Protected processes can deny a query even though they exist.
                return ctypes.get_last_error() == error_access_denied
            try:
                exit_code = wintypes.DWORD()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return exit_code.value == still_active
            finally:
                kernel32.CloseHandle(handle)

        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _lock_is_held(self) -> bool:
        lock = SingleInstanceLock(self.lock_path)
        acquired = lock.acquire()
        if acquired:
            lock.release()
            return False
        return True
