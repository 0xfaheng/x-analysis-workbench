"""可脱离界面测试的路径、报告、任务与只读文件服务。"""
import json
import mimetypes
import os
import re
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

EXIT_MESSAGES = {
    0: "数据、统计与程序建议已更新；人工编辑的建议会保留。",
    2: "参数或配置错误：请检查 config.json，详情见运行日志。",
    3: "X 未登录：请登录 @{handle} 后重试。",
    4: "采集或分析失败：请检查浏览器运行状态，详情见运行日志。",
    5: "缺少 markdown 依赖：请安装依赖或重新安装工作台，详情见运行日志。",
    6: "缺少浏览器依赖：请安装 Microsoft Edge 或 Google Chrome；仍失败时重新安装工作台，详情见运行日志。",
    7: "已有任务在运行：请等待采集、分析或登录任务结束后重试。",
}


def frozen():
    return bool(getattr(sys, "frozen", False))


def resource_root():
    return Path(sys._MEIPASS) if frozen() else Path(__file__).resolve().parents[1]


def resolve_root(*, environ=None, is_frozen=None, executable=None, source=None, home=None):
    env = os.environ if environ is None else environ
    if env.get("XWB_ROOT"):
        return Path(env["XWB_ROOT"]).expanduser().resolve()
    is_frozen = frozen() if is_frozen is None else is_frozen
    beside = Path(executable or sys.executable).resolve().parent
    if is_frozen and (beside / "config.json").is_file():
        return beside
    if not is_frozen:
        return Path(source or resource_root()).resolve()
    return (Path(home or Path.home()) / "Documents" / "X分析工作台").resolve()


def initialize_root(root, resources=None):
    """只补缺失文件；升级不覆盖任何用户配置或文档。"""
    root = Path(root)
    resources = Path(resources or resource_root())
    for name in ("data", "reports", "docs"):
        (root / name).mkdir(parents=True, exist_ok=True)
    sources = [(resources / "config.json", root / "config.json")]
    sources += [(p, root / "docs" / p.relative_to(resources / "docs"))
                for p in (resources / "docs").rglob("*.md")
                if "开发记录" not in p.relative_to(resources / "docs").parts and p.name != "策略基线.md"]
    sources.append((resources / "docs/策略基线.template.md", root / "docs/策略基线.md"))
    for src, dst in sources:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.resolve() == dst.resolve() or dst.exists():
            continue
        content = src.read_bytes()
        try:
            with dst.open("xb") as stream:
                stream.write(content)
        except FileExistsError:
            pass


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def list_reports(root):
    root = Path(root)
    rows = read_json(root / "data/history.json", [])
    history = {r["report_date"]: r for r in rows if isinstance(r, dict) and "report_date" in r} if isinstance(rows, list) else {}
    items = []
    for folder in sorted((root / "reports").glob("*"), reverse=True):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", folder.name) or folder.is_symlink() or not (folder / "analysis.json").is_file():
            continue
        h = history.get(folder.name, {})
        try:
            pending = "（待助手填写" in (folder / "report.md").read_text(encoding="utf-8")
        except OSError:
            pending = False
        page = folder / "report.html"
        try:
            modified = page.stat().st_mtime_ns
        except OSError:
            modified = None
        value = h.get("eligibility_verified_home_90d")
        items.append({"id": folder.name, "eligibility": value,
                      "progress": min(value / 500000, 1) if isinstance(value, (int, float)) else None,
                      "targets_met": h.get("targets_met"), "targets_total": h.get("targets_total"),
                      "pending": pending, "modified": modified,
                      "url": f"reports/{folder.name}/report.html"})
    return items


def select_report(items, selection=None, latest=False):
    ids = [item["id"] for item in items]
    return selection if not latest and selection in ids else next(iter(ids), None)


def exit_message(code, handle="", kind="collect"):
    if code == 0 and kind == "login":
        return f"已确认登录 @{handle}，现在可以点「更新数据与建议」。"
    if code == 0 and kind == "render":
        return "报告网页已重新生成。"
    message = EXIT_MESSAGES.get(code, f"运行失败（退出码 {code}），详情见运行日志。")
    if code == 6 and sys.platform == "darwin":
        message = message.replace("Microsoft Edge 或 Google Chrome", "Google Chrome 或 Microsoft Edge")
    return message.format(handle=handle)


def job_command(root, kind, day=None, *, is_frozen=None, executable=None, entry=None, log_path=None):
    if kind not in ("collect", "login", "render"):
        raise ValueError("未知任务")
    is_frozen = frozen() if is_frozen is None else is_frozen
    command = [str(executable or sys.executable)]
    if not is_frozen:
        command.append(str(entry or Path(__file__).with_name("app.py")))
    if log_path:
        command += ["--job-log", str(log_path)]
    command += ["--run-weekly", "--root", str(root)]
    if kind == "login":
        command.append("--login")
    if kind == "render":
        if not day or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError("请选择要重新生成的报告日期")
        command += ["--skip-collect", "--date", day]
    return command


def subprocess_options(system=None):
    return {"creationflags": 0x08000000} if (system or sys.platform) == "win32" else {}


def safe_static_path(url_path, root, ui):
    """限定目录且解析符号链接；禁止编码穿越、Windows 盘符和目录列举。"""
    path = unquote(urlsplit(url_path).path)
    parts = path.lstrip("/").split("/")
    if any(p in ("", ".", "..") or "\\" in p or ":" in p or "\0" in p or p.startswith(".") for p in parts):
        return None
    bases = {"ui": Path(ui), "reports": Path(root) / "reports", "docs": Path(root) / "docs"}
    base = bases.get(parts[0])
    if base is None or "开发记录" in parts:
        return None
    candidate = base.joinpath(*parts[1:]).resolve()
    if not candidate.is_relative_to(base.resolve()) or not candidate.is_file():
        return None
    if parts[0] == "ui" and candidate.suffix not in (".html", ".css", ".js"):
        return None
    return candidate


def static_handler(root, ui, prefix):
    # 独立生成处理器，受限环境可直接测试响应，无需监听端口。
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.serve(False)

        def do_HEAD(self):
            self.serve(True)

        def serve(self, head):
            path = urlsplit(self.path).path
            file = safe_static_path(path[len(prefix):], root, ui) if path.startswith(prefix) else None
            if file is None:
                self.send_error(404)
                return
            try:
                data = file.read_bytes()
                if path[len(prefix):].startswith("reports/") and file.suffix == ".html":
                    # 仅改 HTTP 响应，不更改磁盘上的报告及分析输出。
                    hook = f'<script src="{prefix}ui/report.js"></script>'
                    data = data.replace(b"<head>", ("<head>" + hook).encode("utf-8"), 1)
                self.send_response(200)
                self.send_header("Content-Type", (mimetypes.guess_type(file.name)[0] or "application/octet-stream") + "; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                if not head:
                    self.wfile.write(data)
            except (OSError, BrokenPipeError):
                return

        def log_message(self, *_):
            pass

    return Handler


class StaticServer:
    def __init__(self, root, ui):
        token = secrets.token_urlsafe(24)
        prefix = f"/{token}/"
        handler = static_handler(root, ui, prefix)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_port}{prefix}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
