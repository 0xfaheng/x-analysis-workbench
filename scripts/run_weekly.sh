#!/bin/zsh
# macOS 兼容入口：选择可用的 Python 后交给跨平台入口。
set -euo pipefail
SCRIPT_ROOT="${0:A:h:h}"

# 选一个能导入 markdown 的 Python（桌面应用启动时 PATH 里可能先是系统自带的 3.9）
PY=""
for cand in "${XWB_PYTHON:-}" /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
            /opt/homebrew/bin/python3 /usr/local/bin/python3 "$(command -v python3 || true)"; do
  [[ -n "$cand" && -x "$cand" ]] || continue
  if "$cand" -I -c 'import markdown' 2>/dev/null; then PY="$cand"; break; fi
done
if [[ -z "$PY" ]]; then
  echo "找不到装有 markdown 模块的 Python 3（可 pip3 install markdown，或设置 XWB_PYTHON）" >&2
  exit 5
fi

exec "$PY" -I "$SCRIPT_ROOT/scripts/run_weekly.py" "$@"
