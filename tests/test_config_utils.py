import copy
import json
import unittest

from support import WorkspaceTest, render
from config_utils import deep_merge, load_config


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
        self.assertEqual(cfg["collector"]["browser_channel"], "msedge")
        self.assertEqual(cfg["handle"], "local_account")
        self.assertEqual(cfg["categories"], self.cfg["categories"])

    def test_optional_local_and_invalid_top_level(self):
        self.assertEqual(load_config(self.root), self.cfg)
        for value in ([], None, "bad"):
            self.write_json(self.root / "config.local.json", value)
            with self.assertRaisesRegex(ValueError, "顶层必须是对象"):
                load_config(self.root)

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
