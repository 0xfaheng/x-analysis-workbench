#!/bin/bash
# Apple Silicon 构建；仅用 CLI 冒烟，不打开应用窗口。
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
PYTHON="${1:-${XWB_PYTHON:-python3}}"
if [[ "$(uname -s)" != "Darwin" || "$("$PYTHON" -c 'import platform; print(platform.machine())')" != "arm64" ]]; then
  echo "请在 Apple Silicon Mac 上使用 arm64 Python 构建。" >&2
  exit 2
fi
"$PYTHON" -m pip install -r packaging/requirements-macos.txt
VERSION="$("$PYTHON" scripts/version.py)"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "版本号无效" >&2; exit 2; }
"$PYTHON" -m unittest discover -s tests
"$PYTHON" -m PyInstaller --noconfirm --clean packaging/xworkbench.spec

APP="$PROJECT_ROOT/dist/XWorkbench.app"
# 带空格与中文的 root 也必须能工作，超时/非零退出/缺少产物都中止出包。
mkdir -p build
FIXTURE_ROOT="$(mktemp -d "$PROJECT_ROOT/build/Mac 合成冒烟.XXXXXX")"
trap 'rm -rf "$FIXTURE_ROOT"' EXIT
"$PYTHON" tests/make_fixture.py --out "$FIXTURE_ROOT"
FIXTURE_DATE="$("$PYTHON" tests/make_fixture.py --print-date)"
"$PYTHON" - "$APP" "$FIXTURE_ROOT" "$FIXTURE_DATE" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

app, root, day = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
log = Path("build/macos-frozen-smoke.log").resolve()
command = [str(app / "Contents/MacOS/XWorkbench"), "--job-log", str(log),
           "--run-weekly", "--skip-collect", "--root", str(root), "--date", day]
result = subprocess.run(command, capture_output=True, text=True, timeout=120)
if log.exists():
    print(log.read_text(encoding="utf-8"))
assert result.returncode == 0, f"冻结包冒烟退出码 {result.returncode}：{result.stderr}"
outputs = ["data/history.json", f"reports/{day}/analysis.json", f"reports/{day}/report.md",
           f"reports/{day}/report.html", "index.html"]
assert all((root / p).is_file() and (root / p).stat().st_size for p in outputs), "冻结包缺少输出"
Path("build/macos-smoke-result.json").write_text(json.dumps({"exit_code": result.returncode,
    "date": day, "outputs": outputs}, ensure_ascii=False, indent=2), encoding="utf-8")
print("冻结包无界面冒烟通过，5 项输出齐全。")
PY

codesign --force --deep -s - "$APP"
codesign --verify --deep --strict "$APP"
STAGING="$PROJECT_ROOT/build/macos-dmg"
rm -rf "$STAGING"
mkdir -p "$STAGING"
ditto "$APP" "$STAGING/XWorkbench.app"
ln -s /Applications "$STAGING/Applications"
NAME="XWorkbench-$VERSION-macOS-arm64"
ditto -c -k --sequesterRsrc --keepParent "$APP" "dist/$NAME.zip"
# 纯文件 HFS+ 镜像再压缩，不挂载磁盘、不依赖 hdiejectd；受限构建环境也可运行。
hdiutil makehybrid -hfs -hfs-volume-name "X分析工作台" -ov -o build/macos-uncompressed.dmg "$STAGING"
hdiutil convert build/macos-uncompressed.dmg -format UDZO -ov -o "dist/$NAME.dmg"
hdiutil verify "dist/$NAME.dmg"
shasum -a 256 "dist/$NAME.dmg" "dist/$NAME.zip"
echo "构建完成：dist/$NAME.dmg 和 dist/$NAME.zip"
