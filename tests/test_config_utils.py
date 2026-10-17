import copy
import json
import unittest

from support import WorkspaceTest, render
from config_utils import HANDLE_HINT, deep_merge, load_config, require_handle, save_local_config
from unittest import mock


class ConfigTests(WorkspaceTest):
    def test_deep_merge_preserves_order_and_does_not_mutate_inputs(self):
        base = {"nested": {"keep": 1, "change": 2}, "array": [1, 2]}
        override = {"nested": {"change": 3, "added": 4}, "array": [9]}
        before = copy.deepcopy((base, override))
        result = deep_merge(base, override)
        self.assertEqual(result, {"nested": {"keep": 1, "change": 3, "added": 4}, "array": [9]})
        self.assertEqual((base, override), before)
        self.assertEqual(list(result["nested"]), ["keep", "change", "added"])
        result["array"].append(10)
        self.assertEqual(override["array"], [9])

    def test_local_overrides_only_supplied_values(self):
        self.write_json(self.root / "config.local.json", {
            "collector": {"headless": True}, "handle": "local_account"})
        cfg = load_config(self.root)
        self.assertTrue(cfg["collector"]["headless"])
        self.assertEqual(cfg["collector"]["browser_channel"], "auto")
        self.assertEqual(cfg["handle"], "local_account")
        self.assertEqual(cfg["categories"], self.cfg["categories"])

    def test_optional_local_and_invalid_top_level(self):
        self.assertEqual(load_config(self.root), self.cfg)
        for value in ([], None, "bad"):
            self.write_json(self.root / "config.local.json", value)
            with self.assertRaisesRegex(ValueError, "顶层必须是对象"):
                load_config(self.root)

    def test_local_save_merges_nested_values_and_preserves_unknown_keys(self):
        original = {"handle": "old", "assistant": {"context_file": "private-context.md"},
                    "app": {"mirasim_port": 5000}, "custom": [1, 2]}
        self.write_json(self.root / "config.local.json", original)
        saved = save_local_config(self.root, {"handle": "new", "app": {"mirasim_schedule_id": "id"}})
        self.assertEqual(saved, {**original, "handle": "new", "app": {"mirasim_port": 5000, "mirasim_schedule_id": "id"}})
        self.assertEqual(json.loads((self.root / "config.local.json").read_text()), saved)
        self.assertEqual(load_config(self.root)["handle"], "new")

    def test_invalid_or_unwritable_local_config_is_never_overwritten(self):
        path = self.root / "config.local.json"
        for source in ("broken", "[]", "null"):
            path.write_text(source)
            with self.assertRaises(ValueError):
                save_local_config(self.root, {"handle": "new"})
            self.assertEqual(path.read_text(), source)
        self.write_json(path, {"other": {"keep": 1}})
        before = path.read_bytes()
        with mock.patch("file_utils.os.replace", side_effect=OSError("模拟写入失败")):
            with self.assertRaises(OSError):
                save_local_config(self.root, {"handle": "new"})
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(list(self.root.glob(".*.tmp")))

    def test_unset_handle_fails_before_any_output_for_all_entries(self):
        self.write_json(self.root / "config.local.json", {"handle": ""})
        for script in ("run_weekly.py", "analyze.py", "render.py"):
            if script == "render.py" and not render:
                continue
            result = self.run_script(script, "--date", "2026-10-17", success=False)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn(HANDLE_HINT, result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse((self.root / "reports").exists())
            self.assertFalse((self.root / "data/history.json").exists())
        for value in ("has-hyphen", "with space", "a" * 16, "@test", 123):
            with self.assertRaisesRegex(ValueError, "X 用户名"):
                require_handle({"handle": value})

    @unittest.skipUnless(render, "需要可选的 markdown 依赖")
    def test_analyze_and_render_share_local_phase_settings(self):
        self.write_json(self.root / "config.local.json", {"handle": "local_account", "phase_targets": {
            "phases": [{"name": "合成阶段", "until": "2027-01-01", "weekly": {
                **self.cfg["phase_targets"]["phases"][0]["weekly"], "median_impressions_min": 4321}}]}})
        a = self.run_analyze()
        self.assertEqual(a["handle"], "local_account")
        self.assertEqual(a["phase"]["name"], "合成阶段")
        self.run_script("render.py")
        page = (self.report_dir / "report.html").read_text(encoding="utf-8")
        payload = page.split("const A = ")[1].split(";\n", 1)[0]
        self.assertEqual(json.loads(payload)["phase_weekly"]["median_impressions_min"], 4321)


if __name__ == "__main__":
    unittest.main()
