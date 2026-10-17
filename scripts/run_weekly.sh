#!/bin/zsh
# 每周采集 + 分析。用法：
#   scripts/run_weekly.sh                 # 采集今天的数据并生成报告草稿
#   scripts/run_weekly.sh --skip-collect  # 只用今天已采集的数据重新分析
#   scripts/run_weekly.sh --date 2026-10-20 --skip-collect
# 之后由助手在 reports/<日期>/report.md 中填写「下周调整建议」，再运行 scripts/render.py 生成网页。
set -euo pipefail

ROOT="${0:A:h:h}"
DATE="$(date +%F)"
COLLECT=1
while (( $# )); do
  case "$1" in
    --date) DATE="$2"; shift 2 ;;
    --skip-collect) COLLECT=0; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

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

RAW="$ROOT/data/raw/$DATE"
HANDLE="$("$PY" -I -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["handle"])' "$ROOT/config.json")"
EGO="$(command -v ego-browser || echo "$HOME/.local/bin/ego-browser")"

if (( COLLECT )); then
  mkdir -p "$RAW"
  rm -f "$RAW/meta.json"
  set +e
  {
    printf 'const OUT_DIR = %s;\nconst HANDLE = %s;\n' \
      "$("$PY" -I -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$RAW")" \
      "$("$PY" -I -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$HANDLE")"
    cat "$ROOT/scripts/collect.mjs"
  } | "$EGO" nodejs
  rc=$?
  set -e
  # 退出码约定：3 = X 未登录，4 = 采集失败（工作台应用据此提示）
  if "$PY" -I -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1], encoding="utf-8")).get("reason") == "not_logged_in" else 1)' "$RAW/meta.json" 2>/dev/null; then
    echo "X 未登录：请在 ego 浏览器里登录 @$HANDLE 后重试" >&2
    exit 3
  fi
  if (( rc != 0 )); then
    echo "采集失败（ego-browser 退出码 $rc），请检查 $RAW/meta.json 和 ego lite 运行状态" >&2
    exit 4
  fi
fi

"$PY" -I "$ROOT/scripts/analyze.py" --root "$ROOT" --date "$DATE"
"$PY" -I "$ROOT/scripts/render.py" --root "$ROOT" --date "$DATE"
