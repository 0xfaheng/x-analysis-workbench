import contextlib
import io
import json
import os
import socket
import sys
import unittest
from pathlib import Path
from unittest import mock

from support import WorkspaceTest
import collect_playwright as cp


class CollectorPureTests(unittest.TestCase):
    def test_urls_keep_base_prefix_query_and_non_default_origin(self):
        self.assertEqual(cp.build_url("https://x.com/", "/home"), "https://x.com/home")
        self.assertEqual(cp.build_url("http://127.0.0.1:8080/mock/", "/i/content?days=90"),
                         "http://127.0.0.1:8080/mock/i/content?days=90")
        for base in ("x.com", "file:///tmp/site", "https://x.com?a=1", "https://x.com/#fragment"):
            with self.subTest(base=base), self.assertRaises(ValueError):
                cp.build_url(base, "home")

    def test_login_matches_complete_handle_only(self):
        for seen, expected in ((None, False), ("", False), ("测试\n@Test_Account\n更多", True),
                               ("@test_account_other", False), ("@test_account2", False),
                               ("someone@test_account", False), ("@other", False)):
            self.assertEqual(cp.is_logged_in(seen, "test_account"), expected)

    def test_meta_is_independent_and_has_common_protocol(self):
        meta = cp.new_meta("test_account")
        self.assertEqual(meta["backend"], "playwright")
        self.assertEqual(meta["handle"], "test_account")
        self.assertTrue(meta["started_at"].endswith("Z"))
        self.assertEqual(meta["files"], {})
        meta["warnings"].append("one")
        self.assertEqual(cp.new_meta("other")["warnings"], [])

    def test_missing_package_has_install_hint_without_import_failure(self):
        with mock.patch.dict(sys.modules, {"playwright": None, "playwright.sync_api": None}):
            with self.assertRaisesRegex(cp.BrowserDependencyError, "pip install"):
                cp.load_playwright()

    def test_launch_errors_are_classified(self):
        playwright = mock.Mock()
        for message, expected in (("Chromium distribution 'msedge' is not found", cp.BrowserDependencyError),
                                  ("Executable doesn't exist at C:/missing", cp.BrowserDependencyError),
                                  ("ProcessSingleton: profile already in use", cp.ProfileOccupiedError),
                                  ("browser disconnected", RuntimeError)):
            playwright.chromium.launch_persistent_context.side_effect = RuntimeError(message)
            with self.subTest(message=message), self.assertRaises(expected):
                cp.launch_context(playwright, Path("中文配置"), {"channel": "msedge"})

    def test_auto_browser_order_and_fallback_only_on_missing_executable(self):
        for system, channels in (("Windows", ["msedge", "chrome"]),
                                 ("Darwin", ["chrome", "msedge"]),
                                 ("Linux", ["chrome", "msedge", None])):
            for success_at in range(len(channels)):
                playwright = mock.Mock()
                context = object()
                launch = playwright.chromium.launch_persistent_context
                launch.side_effect = [RuntimeError("Executable doesn't exist")] * success_at + [context]
                with mock.patch("collect_playwright.platform.system", return_value=system):
                    self.assertIs(cp.launch_context(playwright, Path("profile"), {"channel": "auto", "headless": True}), context)
                self.assertEqual([call.kwargs.get("channel") for call in launch.call_args_list], channels[:success_at + 1])
                self.assertTrue(all(call.kwargs["headless"] for call in launch.call_args_list))
        for message, expected in (("ProcessSingleton: in use", cp.ProfileOccupiedError),
                                   ("browser disconnected", RuntimeError)):
            playwright = mock.Mock()
            playwright.chromium.launch_persistent_context.side_effect = RuntimeError(message)
            with self.assertRaises(expected):
                cp.launch_context(playwright, Path("profile"), {"channel": "auto"})
            self.assertEqual(playwright.chromium.launch_persistent_context.call_count, 1)

    def test_all_auto_browsers_missing_has_platform_install_hint(self):
        for system, hint, count in (("Windows", "请安装 Microsoft Edge 或 Google Chrome", 2),
                                    ("Darwin", "请安装 Google Chrome 或 Microsoft Edge", 2),
                                    ("Linux", "playwright install chromium", 3)):
            playwright = mock.Mock()
            playwright.chromium.launch_persistent_context.side_effect = RuntimeError("Executable doesn't exist")
            with mock.patch("collect_playwright.platform.system", return_value=system), \
                    self.assertRaisesRegex(cp.BrowserDependencyError, hint):
                cp.launch_context(playwright, Path("profile"), {"channel": "auto"})
            self.assertEqual(playwright.chromium.launch_persistent_context.call_count, count)

    def test_explicit_browser_never_falls_back(self):
        for channel in ("chrome", "msedge", "", None):
            playwright = mock.Mock()
            launch = playwright.chromium.launch_persistent_context
            launch.side_effect = RuntimeError("Executable doesn't exist")
            with self.assertRaises(cp.BrowserDependencyError):
                cp.launch_context(playwright, Path("profile"), {"channel": channel})
            self.assertEqual(launch.call_count, 1)
            self.assertEqual(launch.call_args.kwargs.get("channel"), channel or None)

    def test_range_and_verified_selector_use_native_api(self):
        page, meta = mock.Mock(), cp.new_meta("test_account")
        cp.select_range(page, "3M")
        page.get_by_text.assert_called_with("3M", exact=True)
        page.get_by_text.return_value.first.click.assert_called_once()
        button = page.locator.return_value.get_by_role.return_value
        button.count.return_value = 1
        button.get_attribute.return_value = "false"
        self.assertTrue(cp.set_verified_only(page, meta, True))
        page.locator.assert_called_with("main")
        page.locator.return_value.get_by_role.assert_called_with("button", name="Verified only", exact=True)
        button.click.assert_called_once()
        button.count.return_value = 0
        self.assertFalse(cp.set_verified_only(page, meta, True))
        self.assertEqual(meta["warnings"], ["Verified only 开关未找到"])


class CollectorFileTests(WorkspaceTest):
    def test_settings_defaults_override_and_login_is_always_visible(self):
        profile, options = cp.browser_settings(self.root, {})
        self.assertEqual(profile, (self.root / "browser-profile").resolve())
        self.assertEqual(options["channel"], "auto")
        self.assertFalse(options["headless"])
        profile, options = cp.browser_settings(self.root, {
            "profile_dir": "中文配置", "headless": True, "browser_channel": ""}, True)
        self.assertEqual(profile, (self.root / "中文配置").resolve())
        self.assertFalse(options["headless"])
        self.assertNotIn("channel", options)
        for config in ({"headless": "false"}, {"browser_channel": "firefox"}):
            with self.assertRaises(ValueError):
                cp.browser_settings(self.root, config)

    def test_download_chinese_path_preserves_original_on_sharing_violation(self):
        target = self.raw / "中文导出.csv"
        target.write_bytes(b"old")
        download = mock.Mock()
        download.save_as.side_effect = lambda path: Path(path).write_bytes(b"new")
        with mock.patch("collect_playwright.os.replace", side_effect=PermissionError("in use")):
            with self.assertRaisesRegex(OSError, "关闭占用.*Excel"):
                cp.save_download(download, target)
        self.assertEqual(target.read_bytes(), b"old")
        self.assertFalse(list(self.raw.glob("*.tmp")))
        cp.save_download(download, target)
        self.assertEqual(target.read_bytes(), b"new")

    @unittest.skipIf(os.name == "nt", "Windows 配置占用由原生锁与启动错误检测")
    def test_profile_occupied_is_detected_before_launch(self):
        profile = self.root / "中文配置"
        profile.mkdir()
        (profile / "SingletonLock").symlink_to(f"{socket.gethostname()}-{os.getpid()}")
        with self.assertRaisesRegex(cp.ProfileOccupiedError, "配置目录已被占用"):
            cp.check_profile_available(profile)

    def test_missing_playwright_returns_six_and_failure_meta(self):
        with mock.patch("collect_playwright.load_playwright", side_effect=cp.BrowserDependencyError("请安装 playwright")), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cp.collect(self.root, self.raw, "test_account", {}), 6)
        meta = json.loads((self.raw / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["reason"], "error")
        self.assertEqual(meta["step"], "启动浏览器")
        self.assertIn("playwright", meta["error"])
        self.assertFalse(meta["ok"])

    def test_all_browsers_missing_returns_six_for_collection_and_login(self):
        factory = mock.MagicMock()
        factory.return_value.__enter__.return_value.chromium.launch_persistent_context.side_effect = RuntimeError("Executable doesn't exist")
        with mock.patch("collect_playwright.load_playwright", return_value=factory), \
                contextlib.redirect_stderr(io.StringIO()) as err, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cp.collect(self.root, self.raw, "test_account", {}), 6)
            self.assertEqual(cp.login(self.root, "test_account", {}), 6)
        self.assertIn(cp.browser_install_hint(), err.getvalue())

    def test_collect_error_records_current_step_and_success_protocol(self):
        def fail_pages(page, raw, handle, config, meta, set_step):
            set_step("下载 content_90d.csv")
            raise RuntimeError("模拟页面异常")

        def fail(root, handle, config, action):
            # 用动作回调设置失败位置；没有浏览器或 Playwright 调用。
            with mock.patch("collect_playwright.collect_pages", side_effect=fail_pages):
                return action(None, None)
        with mock.patch("collect_playwright.run_browser", side_effect=fail), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cp.collect(self.root, self.raw, "test_account", {}), 4)
        meta = json.loads((self.raw / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["reason"], "error")
        self.assertEqual(meta["error"], "模拟页面异常")
        self.assertEqual(meta["step"], "下载 content_90d.csv")
        with mock.patch("collect_playwright.run_browser", return_value=0):
            self.assertEqual(cp.collect(self.root, self.raw, "test_account", {}), 0)
        meta = json.loads((self.raw / "meta.json").read_text(encoding="utf-8"))
        self.assertTrue(meta["ok"])
        self.assertNotIn("reason", meta)
        self.assertIn("finished_at", meta)

    def test_not_logged_in_writes_account_and_stops_before_analytics(self):
        page, meta = mock.Mock(), cp.new_meta("test_account")
        page.evaluate.return_value = "@other"
        code = cp.collect_pages(page, self.raw, "test_account", {}, meta, mock.Mock())
        self.assertEqual(code, 3)
        page.goto.assert_called_once_with("https://x.com/home")
        saved = json.loads((self.raw / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["reason"], "not_logged_in")
        self.assertEqual(saved["account_seen"], "@other")

    def test_login_does_not_create_collection_metadata(self):
        with mock.patch("collect_playwright.run_browser", return_value=3) as runner, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cp.login(self.root, "test_account", {"headless": True}), 3)
        self.assertTrue(runner.call_args.kwargs["login_mode"])
        self.assertFalse((self.root / "reports").exists())

    def test_login_callback_accepts_target_and_user_closing_window(self):
        for logged_in in (True, False):
            page, context = mock.Mock(), mock.Mock()
            context.pages = [page]
            page.is_closed.return_value = False
            page.evaluate.return_value = "@test_account" if logged_in else "@other"

            def close_window(*_):
                context.pages = []
                page.is_closed.return_value = True
                context.on.call_args.args[1]()
                raise RuntimeError("用户关闭窗口")

            if not logged_in:
                # 关闭发生在导航中也应按未登录退出，不能报连接失败。
                page.goto.side_effect = close_window

            def fake_browser(root, handle, config, action, **kwargs):
                return action(page, context)

            with self.subTest(logged_in=logged_in), mock.patch("collect_playwright.run_browser", side_effect=fake_browser), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cp.login(self.root, "test_account", {}), 0 if logged_in else 3)

    def test_context_cleanup_keeps_original_error_and_nonzero_result(self):
        context = mock.Mock()
        context.pages = [mock.Mock()]
        context.close.side_effect = RuntimeError("关闭失败")
        factory = mock.MagicMock()
        with mock.patch("collect_playwright.load_playwright", return_value=factory), \
                mock.patch("collect_playwright.launch_context", return_value=context):
            self.assertEqual(cp.run_browser(self.root, "test_account", {}, lambda *_: 3), 3)
            with self.assertRaisesRegex(RuntimeError, "原始失败"):
                cp.run_browser(self.root, "test_account", {}, mock.Mock(side_effect=RuntimeError("原始失败")))
            with self.assertRaisesRegex(RuntimeError, "关闭失败"):
                cp.run_browser(self.root, "test_account", {}, lambda *_: 0)

    def test_login_retries_navigation_errors_then_accepts_handle(self):
        page, context = mock.Mock(), mock.Mock()
        context.pages = [page]
        page.is_closed.return_value = False
        page.evaluate.side_effect = [RuntimeError("Execution context was destroyed"),
                                     RuntimeError("Cannot find context with specified id"), "@test_account"]
        with mock.patch("collect_playwright.run_browser", side_effect=lambda r, h, c, action, **kw: action(page, context)), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cp.login(self.root, "test_account", {}), 0)
        self.assertEqual(page.evaluate.call_count, 3)

    def test_login_tracks_newest_page_and_survives_old_page_closing(self):
        old, new, context = mock.Mock(), mock.Mock(), mock.Mock()
        context.pages = [old]
        old.is_closed.return_value = False
        new.is_closed.return_value = False
        old.evaluate.side_effect = RuntimeError("Execution context was destroyed")
        new.evaluate.return_value = "@test_account"

        def new_tab(*_):
            context.pages = [new]
            old.is_closed.return_value = True
            raise RuntimeError("Target page has been closed")
        old.wait_for_timeout.side_effect = new_tab
        with mock.patch("collect_playwright.run_browser", side_effect=lambda r, h, c, action, **kw: action(old, context)), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cp.login(self.root, "test_account", {}), 0)
        new.evaluate.assert_called_once()

    def test_login_times_out_as_not_logged_in(self):
        page, context = mock.Mock(), mock.Mock()
        context.pages = [page]
        page.is_closed.return_value = False
        with mock.patch("collect_playwright.run_browser", side_effect=lambda r, h, c, action, **kw: action(page, context)), \
                mock.patch("collect_playwright.time.monotonic", side_effect=[0, 901, 901]), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cp.login(self.root, "test_account", {}), 3)
        self.assertIn("15 分钟", err.getvalue())

    def test_login_waits_for_replacement_page_when_pages_temporarily_empty(self):
        old, new, context = mock.Mock(), mock.Mock(), mock.Mock()
        context.pages = []
        new.is_closed.return_value = False
        new.evaluate.return_value = "@test_account"
        context.wait_for_event.side_effect = lambda *args, **kw: setattr(context, "pages", [new])
        with mock.patch("collect_playwright.run_browser", side_effect=lambda r, h, c, action, **kw: action(old, context)), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cp.login(self.root, "test_account", {}), 0)
        context.wait_for_event.assert_called_once_with("page", timeout=cp.LOGIN_POLL_MS)


if __name__ == "__main__":
    unittest.main()
