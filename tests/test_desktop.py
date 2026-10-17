import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from support import ROOT, REPORT_DATE, WorkspaceTest, render

sys.path.insert(0, str(ROOT / "desktop"))
import core
import app as desktop_app


class DesktopPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="xwb-desktop-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()

    def test_root_priority_environment_portable_source_documents(self):
        home = self.base / "用户"
        exe = self.base / "便携版" / "XWorkbench.exe"
        exe.parent.mkdir()
        exe.touch()
        source = self.base / "源码"
        params = dict(executable=exe, source=source, home=home, environ={})
        self.assertEqual(core.resolve_root(is_frozen=False, **params), source)
        self.assertEqual(core.resolve_root(is_frozen=True, **params), home / "Documents/X分析工作台")
        (exe.parent / "config.json").write_text("{}")
        self.assertEqual(core.resolve_root(is_frozen=True, **params), exe.parent)
        params["environ"] = {"XWB_ROOT": str(self.base / "自定义")}
        self.assertEqual(core.resolve_root(is_frozen=True, **params), self.base / "自定义")
        self.assertEqual(core.resolve_root(is_frozen=False, **params), self.base / "自定义")

    def test_initialize_is_non_destructive_and_excludes_developer_records(self):
        target = self.base / "数据 空间"
        core.initialize_root(target, ROOT)
        self.assertTrue((target / "data").is_dir())
        self.assertTrue((target / "reports").is_dir())
        self.assertTrue((target / "docs/周报流程.md").is_file())
        self.assertEqual((target / "docs/策略基线.md").read_bytes(), (ROOT / "docs/策略基线.template.md").read_bytes())
        self.assertFalse((target / "docs/开发记录").exists())
        (target / "config.json").write_text("用户设置", encoding="utf-8")
        (target / "docs/周报流程.md").write_text("用户文档", encoding="utf-8")
        (target / "docs/策略基线.md").unlink()
        core.initialize_root(target, ROOT)
        self.assertEqual((target / "config.json").read_text(encoding="utf-8"), "用户设置")
        self.assertEqual((target / "docs/周报流程.md").read_text(encoding="utf-8"), "用户文档")
        self.assertTrue((target / "docs/策略基线.md").is_file())
        (target / "docs/策略基线.md").write_text("个人策略原样保留", encoding="utf-8")
        core.initialize_root(target, ROOT)
        self.assertEqual((target / "docs/策略基线.md").read_text(encoding="utf-8"), "个人策略原样保留")

    def test_source_initialization_keeps_config_and_docs_bytes(self):
        target = self.base / "source"
        shutil.copytree(ROOT / "docs", target / "docs")
        shutil.copy2(ROOT / "config.json", target / "config.json")
        before = {p: p.read_bytes() for p in target.rglob("*") if p.is_file()}
        core.initialize_root(target, target)
        self.assertTrue(all(p.read_bytes() == data for p, data in before.items()))

    def test_commands_use_own_entry_and_keep_spaces_as_separate_arguments(self):
        root = self.base / "中文 空间"
        self.assertEqual(core.job_command(root, "login", is_frozen=True, executable="XWorkbench.exe"),
                         ["XWorkbench.exe", "--run-weekly", "--root", str(root), "--login"])
        self.assertEqual(core.job_command(root, "render", REPORT_DATE, is_frozen=False, executable="python", entry="desktop/app.py"),
                         ["python", "desktop/app.py", "--run-weekly", "--root", str(root), "--skip-collect", "--date", REPORT_DATE])
        self.assertIn("--run-assistant", core.job_command(root, "assistant"))
        self.assertIn("--job-log", core.job_command(root, "collect", log_path="日志.log"))
        for kind, day in (("shell", None), ("render", "../bad"), ("render", None)):
            with self.assertRaises(ValueError):
                core.job_command(root, kind, day)
        self.assertEqual(core.subprocess_options("win32"), {"creationflags": 0x08000000})
        self.assertEqual(core.subprocess_options("darwin"), {})

    def test_all_exit_messages_match_swift(self):
        swift = (ROOT / "app/Sources/main.swift").read_text(encoding="utf-8")
        for code in (2, 3, 4, 5, 7):
            message = core.EXIT_MESSAGES[code].replace("{handle}", r"\(config.handle)")
            self.assertIn(message, swift)
        with mock.patch("core.sys.platform", "darwin"):
            self.assertIn(core.exit_message(6), swift)
        with mock.patch("core.sys.platform", "win32"):
            self.assertIn("请安装 Microsoft Edge 或 Google Chrome", core.exit_message(6))
        self.assertIn("登录", core.exit_message(0, "test_account", "login"))
        self.assertIn("重新生成", core.exit_message(0, kind="render"))
        self.assertIn("退出码 99", core.exit_message(99))

    def test_missing_standard_streams_are_recreated_without_window(self):
        with mock.patch.object(sys, "stdout", None), mock.patch.object(sys, "stderr", None), \
                mock.patch.object(sys, "stdin", None):
            desktop_app.prepare_stdio()
            streams = (sys.stdout, sys.stderr, sys.stdin)
            self.assertTrue(all(s is not None for s in streams))
            for stream in streams:
                stream.close()
        path = self.base / "stdout.log"
        with mock.patch.object(sys, "stdout", None), mock.patch.object(sys, "stderr", None):
            desktop_app.prepare_stdio(path)
            print("标准输出")
            print("标准错误", file=sys.stderr)
            sys.stdout.close()
        self.assertEqual(path.read_text(encoding="utf-8"), "标准输出\n标准错误\n")

    def test_edge_native_guard_cancels_external_frame_navigation(self):
        class Event:
            def __iadd__(self, callback):
                self.callback = callback
                return self
        native = SimpleNamespace(NavigationStarting=Event(), FrameNavigationStarting=Event())
        window = SimpleNamespace(native=SimpleNamespace(webview=SimpleNamespace(CoreWebView2=native), Invoke=lambda f: f()))
        api = mock.Mock()
        del api._edge_guard
        origin = "http://127.0.0.1:123/secret/"
        with mock.patch("app.sys.platform", "win32"), \
                mock.patch.dict(sys.modules, {"System": SimpleNamespace(Action=lambda f: f)}), \
                mock.patch("app.threading.Thread") as thread:
            desktop_app.install_edge_navigation_guard(window, api, origin)
            for url in (origin + "reports/2026-10-17/report.html", "about:blank"):
                args = SimpleNamespace(Uri=url, Cancel=False)
                native.FrameNavigationStarting.callback(None, args)
                self.assertFalse(args.Cancel)
            args = SimpleNamespace(Uri="https://x.com/test_account/status/1", Cancel=False)
            native.FrameNavigationStarting.callback(None, args)
            self.assertTrue(args.Cancel)
            self.assertEqual(thread.call_args.kwargs["args"], (args.Uri,))
            thread.return_value.start.assert_called_once()
            args = SimpleNamespace(Uri="file:///C:/secret", Cancel=False)
            native.NavigationStarting.callback(None, args)
            self.assertTrue(args.Cancel)
            self.assertEqual(thread.call_count, 1)


class DesktopReportTests(WorkspaceTest):
    def test_api_first_setup_normalizes_validates_and_preserves_other_keys(self):
        api = desktop_app.API(self.root)
        original = {"handle": "", "app": {"mirasim_port": 5123}, "private": {"keep": [1, 2]}}
        self.write_json(self.root / "config.local.json", original)
        self.assertEqual(api.list_reports()["handle"], "")
        with self.assertRaisesRegex(ValueError, "请先设置"):
            api.start_job("login")
        for text, normalized in ((" @New_123 ", "New_123"), ("a", "a"), ("a" * 15, "a" * 15)):
            self.assertEqual(api.set_handle(text), {"ok": True, "handle": normalized})
            self.assertEqual(api.list_reports()["handle"], normalized)
            self.assertEqual(json.loads((self.root / "config.local.json").read_text()), {**original, "handle": normalized})
        before = (self.root / "config.local.json").read_bytes()
        for text in ("", "@@test", "中文", "test-name", "a" * 16, None):
            with self.assertRaises(ValueError):
                api.set_handle(text)
        api.running = True
        with self.assertRaisesRegex(ValueError, "任务结束"):
            api.set_handle("other")
        self.assertEqual((self.root / "config.local.json").read_bytes(), before)

    def test_strategy_action_opens_personal_file(self):
        core.initialize_root(self.root)
        api = desktop_app.API(self.root)
        if sys.platform == "win32":
            with mock.patch("app.os.startfile") as opened:
                api.open_path("strategy")
                opened.assert_called_once_with(str(self.root / "docs/策略基线.md"))
        else:
            with mock.patch("app.subprocess.Popen") as opened:
                api.open_path("strategy")
                self.assertEqual(opened.call_args.args[0][-1], str(self.root / "docs/策略基线.md"))

    def test_history_fields_pending_mark_and_selection(self):
        self.assertEqual(core.list_reports(self.root), [])
        self.run_analyze()
        items = core.list_reports(self.root)
        self.assertEqual(items[0]["id"], REPORT_DATE)
        self.assertTrue(items[0]["pending"])
        self.assertIsNone(items[0]["modified"])
        self.write_json(self.root / "data/history.json", [{"report_date": REPORT_DATE, "eligibility_verified_home_90d": 600000,
                                                        "targets_met": 3, "targets_total": 7}])
        new = self.root / "reports/2026-10-24"
        new.mkdir()
        self.write_json(new / "analysis.json", {})
        (new / "report.md").write_text("建议已写", encoding="utf-8")
        (new / "report.html").write_text("报告", encoding="utf-8")
        items = core.list_reports(self.root)
        self.assertEqual(items[1]["progress"], 1)
        self.assertEqual(items[1]["targets_met"], 3)
        self.assertFalse(items[0]["pending"])
        self.assertIsNotNone(items[0]["modified"])
        self.assertEqual(core.select_report(items, REPORT_DATE), REPORT_DATE)
        self.assertEqual(core.select_report(items, REPORT_DATE, latest=True), "2026-10-24")
        self.assertEqual(core.select_report(items, "missing"), "2026-10-24")
        self.assertIsNone(core.select_report([]))

    def test_malformed_history_still_lists_reports(self):
        self.run_analyze()
        (self.root / "data/history.json").write_text("broken")
        self.assertEqual(len(core.list_reports(self.root)), 1)

    def test_api_limits_actions_and_external_url_schemes(self):
        api = desktop_app.API(self.root)
        with mock.patch("app.webbrowser.open") as opened:
            self.assertTrue(api.open_url("https://x.com/test_account/status/1"))
            opened.assert_called_once()
            for url in ("file:///etc/passwd", "javascript:alert(1)", "https:", "cmd.exe"):
                with self.assertRaises(ValueError):
                    api.open_url(url)
        for name in ("../config.json", "shell", "report"):
            with self.assertRaises(ValueError):
                api.open_path(name, "../../etc")
        with self.assertRaises(ValueError):
            api.start_job("bad")
        with self.assertRaises(ValueError):
            api.start_job("render", "../bad")
        with api.lock:
            api.running = True
        self.assertFalse(api.start_job("login")["ok"])

    @unittest.skipUnless(render, "需要可选的 markdown 依赖")
    def test_cli_and_threaded_job_run_without_webview_or_browser(self):
        self.run_analyze()
        api = desktop_app.API(self.root)
        self.assertTrue(api.start_job("render", REPORT_DATE)["ok"])
        deadline = time.monotonic() + 30
        while api.job_status()["running"] and time.monotonic() < deadline:
            time.sleep(.05)
        state = api.job_status()
        self.assertFalse(state["running"])
        self.assertEqual(state["code"], 0, state["log"])
        self.assertIn("report_html", state["log"])
        self.assertTrue((self.report_dir / "report.html").is_file())
        with mock.patch.dict(sys.modules, {"webview": None}), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(desktop_app.main(["--run-weekly", "--root", str(self.root), "--date", REPORT_DATE, "--skip-collect"]), 0)

    def test_mirasim_detection_and_schedule_recursion(self):
        with mock.patch("core.shutil.which", return_value="C:/mirasim.exe") as which:
            self.assertEqual(core.find_mirasim("win32"), "C:/mirasim.exe")
            which.assert_called_once_with("mirasim.exe")
        with mock.patch("core.find_mirasim", return_value="mirasim"):
            self.assertIsNone(core.assistant_settings(self.root))
            self.write_json(self.root / "config.local.json", {"app": {"mirasim_schedule_id": "test-id",
                                                                    "mirasim_workspace": str(self.root), "mirasim_port": 4970}})
            self.assertEqual(core.assistant_settings(self.root)[1], "test-id")
        entry = {"id": "test-id", "cron": "test", "running": False}
        self.assertEqual(core.find_schedule({"data": [[entry]]}, "test-id"), entry)
        self.assertIsNone(core.find_schedule({"id": "test-id"}, "test-id"))

    def test_assistant_waits_until_schedule_finishes(self):
        entry = {"id": "test-id", "cron": "test"}
        responses = [mock.Mock(returncode=0, stdout="{}", stderr=""),
                     mock.Mock(returncode=0, stdout=json.dumps({**entry, "running": True}), stderr=""),
                     mock.Mock(returncode=0, stdout=json.dumps({**entry, "running": False, "lastRun": {"ok": True}}), stderr="")]
        with mock.patch("core.assistant_settings", return_value=("mirasim", "test-id", str(self.root), 4970)), \
                mock.patch("core.subprocess.run", side_effect=responses) as run, \
                mock.patch("core.time.sleep"), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(core.run_assistant(self.root), 0)
        self.assertEqual(run.call_count, 3)
        self.assertIn("run", run.call_args_list[0].args[0])

    @unittest.skipUnless(importlib.util.find_spec("webview"), "需要可选的 pywebview 依赖")
    def test_pywebview_import_does_not_create_window(self):
        import webview
        self.assertTrue(callable(webview.create_window))


class StaticServerTests(WorkspaceTest):
    def setUp(self):
        super().setUp()
        core.initialize_root(self.root)
        self.ui = ROOT / "desktop/ui"

    def test_traversal_and_private_paths_are_rejected(self):
        for path in ("../config.json", "reports/../../config.json", "reports/%2e%2e/config.json", "data/history.json",
                     "config.json", "ui/../../config.json", "reports/C:/Windows", "reports/..\\config.json",
                     "ui/", "docs/开发记录/secret.md", "ui/%00file.js", "ui/.hidden"):
            self.assertIsNone(core.safe_static_path(path, self.root, self.ui), path)
        self.assertEqual(core.safe_static_path("ui/app.js", self.root, self.ui), self.ui / "app.js")
        self.assertIsNotNone(core.safe_static_path("docs/周报流程.md", self.root, self.ui))

    @unittest.skipIf(os.name == "nt", "Windows 创建符号链接可能需要管理员权限")
    def test_symlink_escape_is_rejected(self):
        (self.root / "reports/leak").symlink_to(ROOT, target_is_directory=True)
        self.assertIsNone(core.safe_static_path("reports/leak/config.json", self.root, self.ui))

    def test_loopback_server_is_read_only_and_decorates_response_only(self):
        folder = self.root / "reports" / REPORT_DATE
        folder.mkdir()
        page = folder / "report.html"
        original = b"<!doctype html><html><head></head><body>synthetic</body></html>"
        page.write_bytes(original)
        try:
            server = core.StaticServer(self.root, self.ui).start()
        except PermissionError:
            if os.environ.get("XWB_BROWSER_TESTS") == "1":
                raise
            self.skipTest("当前沙箱禁止本地端口监听；CI 仍须执行真实连接测试")
        self.addCleanup(server.close)
        with urlopen(server.url + "ui/index.html", timeout=5) as response:
            self.assertIn("X 分析工作台", response.read().decode())
        with urlopen(server.url + f"reports/{REPORT_DATE}/report.html", timeout=5) as response:
            self.assertIn(b"ui/report.js", response.read())
        self.assertEqual(page.read_bytes(), original)
        for suffix in ("config.json", "data/history.json", "ui/%2e%2e/config.json", "reports/"):
            with self.assertRaises(HTTPError) as error:
                urlopen(server.url + suffix, timeout=5)
            self.assertEqual(error.exception.code, 404)
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(server.url + "ui/index.html", data=b"bad", method="POST"), timeout=5)
        self.assertEqual(error.exception.code, 501)

    def test_response_handler_without_network_never_modifies_report(self):
        folder = self.root / "reports" / REPORT_DATE
        folder.mkdir()
        page = folder / "report.html"
        original = b"<html><head></head><body>synthetic</body></html>"
        page.write_bytes(original)
        handler_class = core.static_handler(self.root, self.ui, "/secret/")
        for path, expected in ((f"/secret/reports/{REPORT_DATE}/report.html", 200),
                               ("/secret/config.json", 404), ("/secret/data/history.json", 404),
                               ("/secret/ui/%2e%2e/config.json", 404), ("/ui/index.html", 404)):
            handler = handler_class.__new__(handler_class)
            handler.path = path
            handler.request_version = "HTTP/1.1"
            handler.requestline = "GET " + path + " HTTP/1.1"
            handler.command = "GET"
            handler.wfile = io.BytesIO()
            handler.do_GET()
            output = handler.wfile.getvalue()
            self.assertIn(f" {expected} ".encode(), output.split(b"\r\n", 1)[0])
            if expected == 200:
                self.assertIn(b"/secret/ui/report.js", output)
                self.assertIn(b"Cache-Control: no-store", output)
            self.assertEqual(page.read_bytes(), original)
