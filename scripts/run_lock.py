"""运行记录与跨进程互斥；短暂的系统锁保护陈旧记录回收。"""
import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from file_utils import atomic_write_text

STALE_SECONDS = 2 * 60 * 60


class LockBusyError(RuntimeError):
    pass


def pid_exists(pid):
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name == "nt":
        # Windows 的 os.kill(pid, 0) 可能终止进程，必须使用只查询的原生 API。
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if handle:
            kernel.CloseHandle(handle)
            return True
        return ctypes.get_last_error() == 5  # 无查询权限时保守视为仍运行。
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextmanager
def metadata_guard(path):
    # guard 文件一直保留，避免删除已加锁文件后出现两套独立的系统锁。
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


class RunLock:
    def __init__(self, path, message="已有采集/分析任务在运行"):
        self.path = Path(path)
        self.guard = self.path.with_name(self.path.name + ".guard")
        self.message = message
        self.token = uuid.uuid4().hex

    def _read(self):
        try:
            record = json.loads(self.path.read_text(encoding="utf-8"))
            return record if isinstance(record, dict) else {}
        except (FileNotFoundError, ValueError):
            return {}

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with metadata_guard(self.guard):
            record = self._read()
            try:
                started = datetime.fromisoformat(record["started_at"]).timestamp()
            except (KeyError, TypeError, ValueError):
                started = 0
            if time.time() - started < STALE_SECONDS and pid_exists(record.get("pid")):
                raise LockBusyError(self.message)
            atomic_write_text(self.path, json.dumps({
                "pid": os.getpid(), "started_at": datetime.now(timezone.utc).isoformat(),
                "token": self.token,
            }, ensure_ascii=False, indent=2))
        return self

    def __exit__(self, *exc):
        with metadata_guard(self.guard):
            # 超时被新任务接替后，旧任务不能删除新任务的锁。
            if self._read().get("token") == self.token:
                self.path.unlink(missing_ok=True)
