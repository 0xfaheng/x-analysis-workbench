"""Chrome 桥的账号边界、下载新鲜度和入口分流；不访问真实网站。"""
import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from support import REPORT_DATE, WorkspaceTest
import collect_opencli as co
import run_weekly


class DownloadTests(unittest.TestCase):
    def test_completed_download_is_copied_without_changing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "new.csv", root / "stored.csv"
            source.write_bytes(b"Date,Impressions\n2026-10-17,123\n")
            result = co.import_download({"filename": str(source), "downloaded": True, "state": "complete"}, target, time.time())
            self.assertEqual(result, "new.csv")
            self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_old_incomplete_empty_and_non_csv_downloads_preserve_existing_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "new.csv", root / "stored.csv"
            target.write_bytes(b"keep old data")
            receipt = {"filename": str(source), "downloaded": True, "state": "complete"}
            source.write_bytes(b"Date,Impressions\n2026-10-17,123\n")
            os.utime(source, (time.time() - 60, time.time() - 60))
            with self.assertRaisesRegex(RuntimeError, "此前的下载"):
                co.import_download(receipt, target, time.time())
            for update in ({"state": "in_progress"}, {"filename": "relative.csv"}, {"downloaded": False}):
                with self.subTest(update=update), self.assertRaises(RuntimeError):
                    co.import_download({**receipt, **update}, target, time.time())
            source.write_bytes(b"")
            with self.assertRaises(RuntimeError):
                co.import_download(receipt, target, time.time())
            self.assertEqual(target.read_bytes(), b"keep old data")
            self.assertEqual(list(root.glob("*.tmp")), [])


class BridgeTests(unittest.TestCase):
    def test_eval_uses_argument_array_without_shell_or_losing_quotes(self):
        result = mock.Mock(returncode=0, stdout='{"value":"@test_account"}', stderr="")
        with mock.patch.object(co, "cli_command", return_value=["node", "opencli.js"]), \
                mock.patch.object(co.subprocess, "run", return_value=result) as run:
            session = co.ChromeSession()
            js = '() => document.querySelector("[data-testid=account]")?.innerText'
            self.assertEqual(session.read(js), "@test_account")
        args, kwargs = run.call_args
        self.assertEqual(args[0][-1], "(() => ({value: (" + js + ")()}))()")
        self.assertNotIn("shell", kwargs)

    def test_ambiguous_controls_never_click(self):
        with mock.patch.object(co, "cli_command", return_value=["opencli"]):
            session = co.ChromeSession()
        with mock.patch.object(session, "run", return_value={"entries": [{"ref": 1}, {"ref": 2}]}) as run:
            with self.assertRaisesRegex(RuntimeError, "不是唯一匹配"):
                session.click("--role", "button", "--name", "Download CSV")
        self.assertEqual(run.call_count, 1)


class RoutingTests(WorkspaceTest):
    def test_wrong_account_stops_before_analytics_and_closes_only_owned_session(self):
        session = mock.Mock()
        session.read.return_value = "另一个账号 @wrong_account"
        with mock.patch.object(co, "ChromeSession", return_value=session), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(co.collect(self.root, self.raw, "test_account", {}), 3)
        session.open.assert_called_once_with("https://x.com/home")
        session.click.assert_not_called()
        session.close.assert_called_once()
        meta = json.loads((self.raw / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["reason"], "not_logged_in")
        self.assertEqual(meta["backend"], "opencli")

    def test_bridge_failure_has_diagnostics_and_never_replaces_reports(self):
        self.report_dir.mkdir(parents=True, exist_ok=True)
        report = self.report_dir / "report.html"
        report.write_text("已有报告", encoding="utf-8")
        with mock.patch.object(co, "ChromeSession", side_effect=co.BridgeDependencyError("未连接")), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(co.collect(self.root, self.raw, "test_account", {}), 6)
        self.assertEqual(report.read_text(encoding="utf-8"), "已有报告")
        self.assertEqual(json.loads((self.raw / "meta.json").read_text(encoding="utf-8"))["error"], "未连接")

    def test_opencli_failure_does_not_run_analysis(self):
        with mock.patch.object(co, "collect", return_value=3) as collect, \
                mock.patch.object(run_weekly, "analyze_and_render") as analyze, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(run_weekly.main(["--root", str(self.root), "--backend", "opencli", "--date", REPORT_DATE]), 3)
        collect.assert_called_once()
        analyze.assert_not_called()

    def test_opencli_login_checks_existing_chrome_without_playwright_profile(self):
        with mock.patch.object(co, "login", return_value=0) as login, \
                mock.patch("collect_playwright.login", side_effect=AssertionError("不能打开独立登录窗口")), \
                mock.patch("collect_playwright.browser_settings", side_effect=AssertionError("不能使用日常配置目录启动浏览器")):
            self.assertEqual(run_weekly.main(["--root", str(self.root), "--backend", "opencli", "--login"]), 0)
        login.assert_called_once()
        self.assertFalse((self.root / "data/.run.lock").exists())
