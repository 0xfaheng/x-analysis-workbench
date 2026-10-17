"""公共配置和本机配置递归合并；数组和非字典值整体覆盖。"""
import copy
import json
import re
from pathlib import Path

from file_utils import atomic_write_text

HANDLE_HINT = '请先设置 X 用户名（桌面应用首次启动会提示，或在 config.local.json 写 "handle"）'


def require_handle(config):
    handle = config.get("handle")
    if handle is None or handle == "":
        raise ValueError(HANDLE_HINT)
    if not isinstance(handle, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,15}", handle):
        raise ValueError("handle 必须是不含 @ 的 X 用户名（1–15 位字母、数字或下划线）")
    return handle


def deep_merge(base, override):
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_config(root):
    root = Path(root)
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    local = root / "config.local.json"
    override = json.loads(local.read_text(encoding="utf-8")) if local.exists() else {}
    if not isinstance(config, dict) or not isinstance(override, dict):
        raise ValueError("config.json 和 config.local.json 的顶层必须是对象")
    return deep_merge(config, override)


def save_local_config(root, override):
    """只更新指定键；损坏的本机配置须先修复，不能静默覆盖。"""
    path = Path(root) / "config.local.json"
    local = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(local, dict) or not isinstance(override, dict):
        raise ValueError("config.local.json 的顶层必须是对象")
    merged = deep_merge(local, override)
    atomic_write_text(path, json.dumps(merged, ensure_ascii=False, indent=2) + "\n")
    return merged
