#!/usr/bin/env python3
"""桌面入口；命令行模式先分流，绝不初始化 WebView。"""
import io
import os
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import core
from config_utils import load_config, require_handle, save_local_config
from version import __version__


def prepare_stdio(log_path=None):
    """windowed exe 没有 Python 标准流；优先显式日志，再接继承的管道。"""
    if log_path:
        sys.stdout = sys.stderr = open(log_path, "w", encoding="utf-8", buffering=1)
    for name, std_id in (("stdout", -11), ("stderr", -12)):
        stream = getattr(sys, name)
        if stream is None and sys.platform == "win32":
            try:
                import ctypes
                import msvcrt
                from ctypes import wintypes
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.GetStdHandle.argtypes = [wintypes.DWORD]
                kernel.GetStdHandle.restype = wintypes.HANDLE
                kernel.GetCurrentProcess.restype = wintypes.HANDLE
                kernel.DuplicateHandle.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
                                                   ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
                                                   wintypes.BOOL, wintypes.DWORD]
                duplicate = wintypes.HANDLE()
                process = kernel.GetCurrentProcess()
                handle = kernel.GetStdHandle(std_id & 0xffffffff)
                if not kernel.DuplicateHandle(process, handle, process, ctypes.byref(duplicate), 0, False, 2):
                    raise OSError("没有继承的输出管道")
                fd = msvcrt.open_osfhandle(duplicate.value, os.O_WRONLY | os.O_BINARY)
                stream = os.fdopen(fd, "w", encoding="utf-8", buffering=1)
            except (OSError, ValueError):
                stream = None
        if stream is None:
            stream = open(os.devnull, "w", encoding="utf-8")
        elif isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        setattr(sys, name, stream)
    if sys.stdin is None:
        sys.stdin = open(os.devnull, "r", encoding="utf-8")


class API:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.Lock()
        self.running = False
        self.log = ""
        self.status = "数据来自 X Creator Studio 与 Analytics"
        self.code = None
        self.kind = None
        self.generation = 0

    def list_reports(self):
        config = load_config(self.root)
        return {"reports": core.list_reports(self.root), "handle": config.get("handle", ""),
                "version": __version__}

    def job_status(self, offset=0):
        with self.lock:
            offset = max(0, int(offset))
            return {"running": self.running, "status": self.status, "code": self.code,
                    "log": self.log[offset:], "offset": len(self.log), "generation": self.generation,
                    "kind": self.kind}

    def set_handle(self, value):
        handle = value.strip().removeprefix("@") if isinstance(value, str) else value
        handle = require_handle({"handle": handle})
        with self.lock:
            if self.running:
                raise ValueError("请等待任务结束后再修改 X 用户名")
            save_local_config(self.root, {"handle": handle})
        return {"ok": True, "handle": handle}

    def start_job(self, kind, day=None):
        config = load_config(self.root)
        require_handle(config)
        if kind == "render" and day not in [r["id"] for r in core.list_reports(self.root)]:
            raise ValueError("请选择已有报告")
        command = core.job_command(self.root, kind, day)
        with self.lock:
            if self.running:
                return {"ok": False, "message": core.exit_message(7)}
            self.running, self.code, self.kind = True, None, kind
            self.generation += 1
            self.log = "$ " + subprocess.list2cmdline(command) + "\n"
            login_hint = ("正在检查日常 Chrome 中的 X 登录账号…" if config.get("collector", {}).get("backend") == "opencli"
                          else "请在弹出的专用浏览器窗口手动登录 X，最多等待 15 分钟…")
            self.status = {"login": login_hint,
                           "collect": "正在读取 X 数据，大约 1–2 分钟…",
                           "render": "正在使用已有数据重新生成网页…"}[kind]
        threading.Thread(target=self._run, args=(kind, day), daemon=True).start()
        return {"ok": True}

    def _append(self, text):
        with self.lock:
            self.log += text

    def _run(self, kind, day):
        code = 4
        try:
            # Windows 无控制台启动器对继承句柄的处理有差异，显式日志保证不丢输出。
            with tempfile.TemporaryDirectory(prefix="xwb-job-") as temp:
                log_path = Path(temp) / "stdout.log" if core.frozen() and sys.platform == "win32" else None
                command = core.job_command(self.root, kind, day, log_path=log_path)
                with subprocess.Popen(command, cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                                      env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
                                      **core.subprocess_options()) as process:
                    if log_path:
                        while not log_path.exists() and process.poll() is None:
                            time.sleep(0.1)
                        if log_path.exists():
                            with log_path.open(encoding="utf-8", errors="replace") as stream:
                                while True:
                                    self._append(stream.read())
                                    if process.poll() is not None:
                                        self._append(stream.read())
                                        break
                                    time.sleep(0.1)
                        self._append(process.stdout.read())
                    else:
                        for line in process.stdout:
                            self._append(line)
                    code = process.wait()
        except Exception as error:
            self._append(f"无法运行任务：{error}\n")
        try:
            handle = load_config(self.root).get("handle", "")
        except (OSError, ValueError):
            handle = ""
        with self.lock:
            self.status = core.exit_message(code, handle, kind)
            self.code, self.running = code, False

    def open_url(self, url):
        parts = urlsplit(str(url))
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("只允许打开 http/https 链接")
        webbrowser.open(str(url))
        return True

    def open_path(self, name, day=None):
        paths = {"root": self.root, "data": self.root / "data", "config": self.root / "config.json",
                 "strategy": self.root / "docs/策略基线.md", "workflow": self.root / "docs/周报流程.md"}
        if name == "report" and day in [r["id"] for r in core.list_reports(self.root)]:
            paths["report"] = self.root / "reports" / day / "report.md"
        path = paths.get(name)
        if path is None or not path.exists() or not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("文件不存在或不允许打开")
        if sys.platform == "win32":
            os.startfile(str(path))
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)], **core.subprocess_options())
        return True


def install_edge_navigation_guard(window, api, origin):
    """Edge WebView2 原生层也拦截 iframe 的程序化跳转。"""
    if sys.platform != "win32":
        return
    from System import Action

    def install():
        if getattr(api, "_edge_guard", None):
            return
        native = window.native.webview.CoreWebView2

        def navigation(sender, args):
            url = str(args.Uri)
            if url.startswith(origin) or url == "about:blank":
                return
            args.Cancel = True
            if urlsplit(url).scheme in ("http", "https"):
                threading.Thread(target=api.open_url, args=(url,), daemon=True).start()

        native.NavigationStarting += navigation
        native.FrameNavigationStarting += navigation
        api._edge_guard = navigation

    window.native.Invoke(Action(install))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    log_path = None
    if len(argv) >= 2 and argv[0] == "--job-log":
        log_path, argv = argv[1], argv[2:]
    prepare_stdio(log_path)
    if argv and argv[0] == "--run-weekly":
        import run_weekly
        args = argv[1:]
        if "--root" not in args and not any(a.startswith("--root=") for a in args):
            args += ["--root", str(core.resolve_root())]
        parsed = run_weekly.parse_args(args)
        try:
            core.initialize_root(parsed.root)
            return run_weekly.main(args)
        except (OSError, ValueError) as error:
            print(f"初始化失败：{error}", file=sys.stderr)
            return 2
    if argv:
        print("参数错误：请使用 --run-weekly <周报参数>", file=sys.stderr)
        return 2
    root = core.resolve_root()
    core.initialize_root(root)
    import webview
    server = core.StaticServer(root, core.resource_root() / "desktop/ui").start()
    api = API(root)
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    window = webview.create_window(f"X 分析工作台 v{__version__}", server.url + "ui/index.html",
                                  js_api=api, width=1380, height=900, min_size=(1000, 680))
    window.events.loaded += lambda: install_edge_navigation_guard(window, api, server.url)

    def closing():
        if api.job_status()["running"]:
            window.create_confirmation_dialog("任务正在运行", "请等待任务完成后再退出工作台。")
            return False
    window.events.closing += closing
    try:
        webview.start(gui="edgechromium" if sys.platform == "win32" else None, private_mode=True)
    finally:
        server.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
