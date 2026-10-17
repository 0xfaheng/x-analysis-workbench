"""同目录原子写入，统一使用 UTF-8 与 LF。"""
import os
import stat
import uuid
from pathlib import Path


def atomic_write_text(path, text):
    path = Path(path)
    temp = None
    try:
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
        temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        # 普通 open 的 0666 会经过当前 umask；不要继承临时文件默认的 0600。
        with temp.open("x", encoding="utf-8", newline="\n") as f:
            if mode is not None:
                os.chmod(temp, mode)
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def ensure_utf8_stdio():
    """Windows 管道默认用 ANSI 代码页，-I 又会忽略 PYTHONUTF8，中文输出前统一切到 UTF-8。"""
    import sys
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure") \
                and (stream.encoding or "").lower().replace("-", "") != "utf8":
            stream.reconfigure(encoding="utf-8", errors="replace")
