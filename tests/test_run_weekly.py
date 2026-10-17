import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from support import ROOT, REPORT_DATE, WorkspaceTest, analyze, render
import run_weekly
from run_lock import LockBusyError, RunLock


class ArgumentsBackendTests(unittest.TestCase):
    def test_arguments_defaults_root_environment_and_override(self):
        with mock.patch.dict(os.environ, {"XWB_ROOT": str(ROOT)}):
            self.assertEqual(run_weekly.parse_args([]).root, ROOT)
            args = run_weekly.parse_args(["--date", REPORT_DATE, "--skip-collect", "--backend", "ego", "--root", "."])
        self.assertEqual(args.date, REPORT_DATE)
        self.assertTrue(args.skip_collect)
        self.assertEqual(args.backend, "ego")
        self.assertEqual(args.root, Path.cwd())
        with mock.patch.dict(os.environ, {"XWB_ROOT": ""}):
            self.assertEqual(run_weekly.parse_args([]).root, ROOT)

    def test_invalid_arguments_exit_two(self):
        for args in (["--unknown"], ["--date"], ["--date", "2026-02-30"],
                     ["--date", "20261017"], ["--date", "2026-1-1"],
                     ["--backend", "other"], ["--login", "--skip-collect"]):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()) as err:
                with self.assertRaises(SystemExit) as exc:
                    run_weekly.main(args)
                self.assertEqual(exc.exception.code, 2)
                self.assertIn("参数错误", err.getvalue())

    def test_backend_selection_platform_and_which(self):
        for system, found, expected in (("Darwin", "ego", "ego"), ("Darwin", None, "playwright"),
                                        ("Windows", "ego", "playwright"), ("Linux", "ego", "playwright")):
            with self.subTest(system=system, found=found), mock.patch("run_weekly.platform.system", return_value=system), \
                    mock.patch("run_weekly.shutil.which", return_value=found), \
                    mock.patch("run_weekly.Path.is_file", return_value=False):
                self.assertEqual(run_weekly.select_backend("auto"), expected)
                self.assertEqual(run_weekly.select_backend("ego"), "ego")
                self.assertEqual(run_weekly.select_backend("playwright"), "playwright")

    def test_ego_fallback_order(self):
        with mock.patch("run_weekly.shutil.which", return_value=None), \
                mock.patch("run_weekly.Path.is_file", return_value=True), \
                mock.patch("run_weekly.os.access", return_value=True):
            self.assertEqual(run_weekly.find_ego(), str(Path.home() / ".local/bin/ego-browser"))

    def test_collection_exit_mapping(self):
        for code, meta, expected in ((0, {"ok": True}, 0), (0, {}, 4), (1, {"ok": True}, 4),
                                     (3, {"reason": "not_logged_in"}, 3), (4, {"reason": "not_logged_in"}, 3),
                                     (6, {"ok": False}, 4), (0, {"ok": False}, 4)):
            self.assertEqual(run_weekly.collection_exit_code(code, meta), expected)


class RunnerTests(WorkspaceTest):
    def run_main(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            code = run_weekly.main(["--root", str(self.root), "--date", REPORT_DATE, *args])
        return code, err.getvalue()

    @unittest.skipUnless(render, "需要可选的 markdown 依赖")
    def test_in_process_pipeline_matches_separate_cli_bytes(self):
        self.run_analyze()
        self.run_script("render.py")
        paths = [self.root / "data/history.json", self.report_dir / "analysis.json", self.report_dir / "report.md",
                 self.report_dir / "report.html", self.root / "index.html"]
        before = {p: p.read_bytes() for p in paths}
        # 冻结环境不允许另起 Python，也不能依赖修改 sys.argv 来调用模块。
        with mock.patch("run_weekly.subprocess.run", side_effect=AssertionError("不可启动子进程")), \
                mock.patch.object(analyze, "main", wraps=analyze.main) as am, \
                mock.patch.object(render, "main", wraps=render.main) as rm:
            self.assertEqual(self.run_main("--skip-collect")[0], 0)
        am.assert_called_once_with(["--root", str(self.root.resolve()), "--date", REPORT_DATE])
        rm.assert_called_once_with(["--root", str(self.root.resolve()), "--date", REPORT_DATE])
        for p in paths:
            self.assertEqual(p.read_bytes(), before[p])
        self.assertFalse((self.root / "data/.run.lock").exists())

    @unittest.skipUnless(render, "需要可选的 markdown 依赖")
    def test_isolated_python_entry(self):
        self.run_script("run_weekly.py", "--skip-collect", "--date", REPORT_DATE)
        self.assertTrue((self.report_dir / "report.html").exists())

    @unittest.skipUnless(shutil.which("zsh"), "需要 zsh 验证 Mac 薄包装")
    @unittest.skipUnless(render, "需要可选的 markdown 依赖")
    def test_shell_passes_all_arguments_and_uses_python_override(self):
        result = subprocess.run([shutil.which("zsh"), str(ROOT / "scripts/run_weekly.sh"),
                                 "--root", str(self.root), "--skip-collect", "--date", REPORT_DATE,
                                 "--backend", "playwright"], env={**os.environ, "XWB_PYTHON": sys.executable},
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.report_dir / "report.html").exists())

    def test_missing_markdown_returns_five_before_collection(self):
        with mock.patch.dict(sys.modules, {"markdown": None}), mock.patch("run_weekly.collect_ego") as collect:
            code, error = self.run_main("--backend", "ego")
        self.assertEqual(code, 5)
        self.assertIn("pip install", error)
        collect.assert_not_called()

    @unittest.skipUnless(render, "需要可选的 markdown 依赖")
    def test_failures_do_not_run_analysis(self):
        for code in (3, 4, 6):
            with self.subTest(code=code), mock.patch("collect_playwright.collect", return_value=code), \
                    mock.patch("run_weekly.analyze_and_render") as pipeline:
                self.assertEqual(self.run_main("--backend", "playwright")[0], code)
                pipeline.assert_not_called()
        self.assertFalse((self.root / "data/.run.lock").exists())

    @unittest.skipUnless(render, "需要可选的 markdown 依赖")
    def test_analysis_failure_and_invalid_config(self):
        (self.raw / "content_90d.csv").unlink()
        code, error = self.run_main("--skip-collect")
        self.assertEqual(code, 4)
        self.assertIn("缺少帖子数据", error)
        self.write_json(self.root / "config.local.json", {"collector": {"backend": "unknown"}})
        self.assertEqual(self.run_main()[0], 2)

    def test_login_holds_lock_does_not_analyze_or_collect(self):
        def login(*args):
            self.assertTrue((self.root / "data/.run.lock").exists())
            with self.assertRaises(LockBusyError):
                with RunLock(self.root / "data/.run.lock"):
                    pass
            return 0
        with mock.patch("collect_playwright.login", side_effect=login), \
                mock.patch("collect_playwright.collect", side_effect=AssertionError("不得采集")), \
                mock.patch("run_weekly.analyze_and_render", side_effect=AssertionError("不得分析")), \
                mock.patch.dict(sys.modules, {"markdown": None}):
            self.assertEqual(self.run_main("--login")[0], 0)
        self.assertFalse((self.root / "reports").exists())

    def test_running_task_returns_seven_for_both_modes(self):
        with RunLock(self.root / "data/.run.lock"):
            for args in (("--skip-collect",), ("--login",)):
                code, error = self.run_main(*args)
                self.assertEqual(code, 7)
                self.assertIn("已有采集/分析任务在运行", error)

    def test_ego_stdin_and_missing_meta(self):
        def fake_run(argv, **kwargs):
            self.assertEqual(argv, ["ego-test", "nodejs"])
            self.assertIn('const HANDLE = "test_account";', kwargs["input"])
            self.assertIn(json.dumps(str(self.raw)), kwargs["input"])
            self.write_json(self.raw / "meta.json", {"ok": True})
            return mock.Mock(returncode=0)
        with mock.patch("run_weekly.find_ego", return_value="ego-test"), \
                mock.patch("run_weekly.subprocess.run", side_effect=fake_run):
            self.assertEqual(run_weekly.collect_ego(self.raw, "test_account"), 0)
        with mock.patch("run_weekly.find_ego", return_value="ego-test"), \
                mock.patch("run_weekly.subprocess.run", return_value=mock.Mock(returncode=0)), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(run_weekly.collect_ego(self.raw, "test_account"), 4)
        failure = json.loads((self.raw / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(failure["reason"], "error")
        self.assertIn("未生成有效", failure["error"])


class LockTests(WorkspaceTest):
    def test_stale_dead_and_malformed_locks_are_reclaimed(self):
        path = self.root / "data/.run.lock"
        for record in ({"pid": 99999, "started_at": datetime.now(timezone.utc).isoformat()},
                       {"pid": os.getpid(), "started_at": (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()},
                       {"broken": True}):
            self.write_json(path, record)
            with mock.patch("run_lock.pid_exists", return_value=record.get("pid") == os.getpid()):
                with RunLock(path):
                    self.assertEqual(json.loads(path.read_text())["pid"], os.getpid())
            self.assertFalse(path.exists())

    def test_reclaimed_owner_cannot_remove_new_lock(self):
        path = self.root / "data/.run.lock"
        with RunLock(path):
            self.write_json(path, {"token": "new-owner"})
        self.assertEqual(json.loads(path.read_text())["token"], "new-owner")

    def test_real_second_process_cannot_acquire_held_lock(self):
        path = self.root / "data/.run.lock"
        source = "import sys; sys.path.insert(0,sys.argv[1]); from run_lock import RunLock,LockBusyError\ntry:\n with RunLock(sys.argv[2]): pass\nexcept LockBusyError:\n sys.exit(7)\n"
        with RunLock(path):
            result = subprocess.run([sys.executable, "-I", "-c", source, str(ROOT / "scripts"), str(path)],
                                    capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(result.returncode, 7, result.stderr)


if __name__ == "__main__":
    unittest.main()
