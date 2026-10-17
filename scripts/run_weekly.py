#!/usr/bin/env python3
"""跨平台周报入口；分析与渲染均在本进程执行，支持冻结程序。"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# -I 不包含脚本目录；同时让 PyInstaller 能发现下面的静态模块导入。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config_utils import load_config, require_handle
from file_utils import atomic_write_text, ensure_utf8_stdio
from run_lock import LockBusyError, RunLock


class ChineseParser(argparse.ArgumentParser):
    def format_usage(self):
        return super().format_usage().replace("usage:", "用法：", 1)

    def error(self, message):
        for source, target in (("unrecognized arguments:", "无法识别的参数："),
                               ("expected one argument", "缺少参数值"),
                               ("invalid choice:", "无效选项："),
                               ("choose from", "可选值"), ("argument ", "参数 ")):
            message = message.replace(source, target)
        self.print_usage(sys.stderr)
        self.exit(2, f"参数错误：{message}\n")


def report_date(value):
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError("日期必须是有效的 YYYY-MM-DD") from None


def parse_args(argv=None):
    parser = ChineseParser(description="只读采集 X 数据并生成周报", add_help=False)
    parser.add_argument("-h", "--help", action="help", help="显示帮助并退出")
    parser.add_argument("--date", type=report_date, default=date.today().isoformat(), help="报告日期 YYYY-MM-DD")
    parser.add_argument("--skip-collect", action="store_true", help="使用已有原始数据")
    parser.add_argument("--backend", choices=("auto", "ego", "playwright"), help="覆盖 collector.backend")
    parser.add_argument("--login", action="store_true", help="仅打开 Playwright 专用浏览器，手动登录后退出")
    parser.add_argument("--root", type=Path,
                        default=Path(os.environ.get("XWB_ROOT") or Path(__file__).resolve().parents[1]),
                        help="数据根目录；默认 XWB_ROOT 或脚本上级目录")
    args = parser.parse_args(argv)
    if args.login and args.skip_collect:
        parser.error("--login 不能与 --skip-collect 同时使用")
    args.root = args.root.expanduser().resolve()
    return args


def find_ego():
    found = shutil.which("ego-browser")
    fallback = Path.home() / ".local" / "bin" / "ego-browser"
    return found or (str(fallback) if fallback.is_file() and os.access(fallback, os.X_OK) else None)


def select_backend(requested):
    if requested not in ("auto", "ego", "playwright"):
        raise ValueError("collector.backend 必须是 auto、ego 或 playwright")
    if requested == "auto":
        return "ego" if platform.system() == "Darwin" and find_ego() else "playwright"
    return requested


def collection_exit_code(returncode, meta):
    if meta.get("reason") == "not_logged_in":
        return 3
    return 0 if returncode == 0 and meta.get("ok") is True else 4


def read_meta(raw):
    try:
        meta = json.loads((raw / "meta.json").read_text(encoding="utf-8"))
        return meta if isinstance(meta, dict) else {}
    except (OSError, ValueError):
        return {}


def collect_ego(raw, handle):
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "meta.json").unlink(missing_ok=True)
    prefix = f"const OUT_DIR = {json.dumps(str(raw))};\nconst HANDLE = {json.dumps(handle)};\n"
    try:
        ego = find_ego()
        if not ego:
            raise FileNotFoundError("找不到 ego-browser，请启动或安装 ego lite")
        source = (Path(__file__).resolve().parent / "collect.mjs").read_text(encoding="utf-8")
        result = subprocess.run([ego, "nodejs"], input=prefix + source, text=True, encoding="utf-8")
        meta = read_meta(raw)
        if not meta:
            raise OSError(f"ego-browser 退出码 {result.returncode}，未生成有效的 meta.json")
        return collection_exit_code(result.returncode, meta)
    except OSError as error:
        now = datetime.now(timezone.utc).isoformat()
        atomic_write_text(raw / "meta.json", json.dumps({
            "started_at": now, "finished_at": now, "handle": handle, "backend": "ego",
            "files": {}, "warnings": [], "ok": False, "reason": "error",
            "error": str(error), "step": "启动 ego-browser",
        }, ensure_ascii=False, indent=2))
        print(f"采集失败：{error}", file=sys.stderr)
        return 4


def analyze_and_render(root, day):
    # 必须在任何写入前检查依赖，冻结环境不调用 sys.executable 子进程。
    import analyze
    import render
    argv = ["--root", str(root), "--date", day]
    analyze.main(argv)
    render.main(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        config = load_config(args.root)
        collector = config.get("collector", {})
        if not isinstance(collector, dict):
            raise ValueError("collector 必须是对象")
        backend = select_backend(args.backend or collector.get("backend", "auto"))
        handle = require_handle(config)
        if args.login or (not args.skip_collect and backend == "playwright"):
            from collect_playwright import browser_settings
            browser_settings(args.root, collector, args.login)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f"配置错误：{error}", file=sys.stderr)
        return 2

    try:
        with RunLock(args.root / "data" / ".run.lock"):
            if args.login:
                from collect_playwright import login
                return login(args.root, handle, collector)
            try:
                import markdown  # 在采集前发现缺失，避免生成一半成品。
            except ImportError:
                print("缺少 markdown 依赖，请运行 pip install -r requirements.txt", file=sys.stderr)
                return 5
            raw = args.root / "data" / "raw" / args.date
            if not args.skip_collect:
                if backend == "ego":
                    code = collect_ego(raw, handle)
                else:
                    from collect_playwright import collect
                    code = collect(args.root, raw, handle, collector)
                if code:
                    if code == 3:
                        where = "ego 浏览器" if backend == "ego" else "专用浏览器（先运行 --login）"
                        print(f"X 未登录：请在{where}里登录 @{handle} 后重试", file=sys.stderr)
                    elif code == 4:
                        print(f"采集失败：请检查 {raw / 'meta.json'} 和浏览器运行状态", file=sys.stderr)
                    return code
            analyze_and_render(args.root, args.date)
        return 0
    except LockBusyError as error:
        print(str(error), file=sys.stderr)
        return 7
    except SystemExit as error:
        print(f"分析/渲染失败：{error}", file=sys.stderr)
        return 4
    except Exception as error:
        print(f"运行失败：{error}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    ensure_utf8_stdio()
    sys.exit(main())
