"""公共配置和本机配置递归合并；数组和非字典值整体覆盖。"""
import copy
import json
from pathlib import Path


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
