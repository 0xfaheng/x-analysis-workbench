"""验证建议的依据、未知值、规则时效、人工内容保护及无需网络的完整输出。"""
import copy
import json
import re
import shutil
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from support import ROOT, REPORT_DATE, WorkspaceTest, analyze, post, render
import recommendations as rec


class PolicyTests(unittest.TestCase):
    def test_policy_has_official_sources_and_distinct_impression_threshold(self):
        policy = rec.load_policy()
        self.assertEqual(policy["thresholds"]["verified_home_impressions_90d"], 500000)
        self.assertEqual(policy["thresholds"]["verified_followers"], 500)
        self.assertEqual(policy["verified_at"], "2026-10-17")
        self.assertTrue(all(s["url"].startswith("https://help.x.com/") for s in policy["sources"].values()))
        self.assertTrue({"originality", "reward_content", "qualified_impressions", "automation"} <= {r["id"] for r in policy["rules"]})

    def test_checksum_detects_content_edits_and_text_outside_generated_block(self):
        block = rec.wrap_automatic("第一段\n\n第二段")
        self.assertTrue(rec.is_untouched_automatic(block))
        self.assertFalse(rec.is_untouched_automatic(block.replace("第二段", "人工修改")))
        self.assertFalse(rec.is_untouched_automatic(block + "\n人工补充"))
        self.assertFalse(rec.is_untouched_automatic("人工建议"))

    def test_metric_check_does_not_infer_execution_or_replace_unknown_with_zero(self):
        self.assertEqual(rec.evaluate_check({"week": {"median": None}}, {"metric": "week.median", "min": 100})["status"], "数据不足")
        self.assertEqual(rec.evaluate_check({"week": {"main_posts": 15}}, {"metric": "week.main_posts", "min": 7, "max": 14})["status"], "指标未达标")
        self.assertEqual(rec.evaluate_check({"week": {"main_posts": 10}}, {"metric": "week.main_posts", "min": 7, "max": 14})["status"], "指标达标")
        self.assertEqual(rec.evaluate_check({}, None)["status"], "需人工核对")


class RecommendationTests(WorkspaceTest):
    def test_first_run_is_complete_offline_and_contains_policy_evidence(self):
        # 直接执行分析期间，禁止进程和网络调用；规则摘要应随源码离线可用。
        import socket
        with mock.patch("subprocess.run", side_effect=AssertionError("不得调用外部程序或AI")), \
                mock.patch.object(socket, "create_connection", side_effect=AssertionError("不得联网")):
            analyze.main(["--root", str(self.root), "--date", REPORT_DATE])
        a = json.loads((self.report_dir / "analysis.json").read_text(encoding="utf-8"))
        text = (self.report_dir / "report.md").read_text(encoding="utf-8")
        self.assertEqual(a["recommendations"]["origin"], "program")
        self.assertNotIn(analyze.SUG_PLACEHOLDER, text)
        self.assertIn("X 官方规则依据", text)
        self.assertIn("https://help.x.com/en/using-x/original-content-rewards", text)
        self.assertIn("不调用AI", text)
        for item in a["recommendations"]["actions"]:
            self.assertTrue(item["evidence"] and item["action"] and item["review"])

    def test_regeneration_updates_automatic_advice_but_not_manual_edits(self):
        self.run_analyze()
        path = self.report_dir / "report.md"
        before = path.read_text(encoding="utf-8")
        self.write_posts([post(ident=str(i)) for i in range(9)])
        a = self.run_analyze()
        after = path.read_text(encoding="utf-8")
        self.assertEqual(a["recommendations"]["origin"], "program")
        self.assertNotEqual(before, after)
        after = after.replace("这些建议由本机程序", "人工补充过的建议由本机程序")
        path.write_text(after, encoding="utf-8")
        a = self.run_analyze()
        self.assertEqual(a["recommendations"]["origin"], "manual")
        self.assertIn("人工补充过的建议由本机程序", path.read_text(encoding="utf-8"))
        self.assertEqual(a["recommendations"]["actions"], [])

    def test_old_placeholder_migrates_automatically(self):
        self.report_dir.mkdir(parents=True)
        (self.report_dir / "report.md").write_text(analyze.SUG_START + "\n" + analyze.SUG_PLACEHOLDER + "\n" + analyze.SUG_END, encoding="utf-8")
        self.assertEqual(self.run_analyze()["recommendations"]["origin"], "program")
        self.assertNotIn(analyze.SUG_PLACEHOLDER, (self.report_dir / "report.md").read_text(encoding="utf-8"))

    def test_missing_data_is_unknown_and_analytics_does_not_prove_eligibility(self):
        self.write_daily("overview_verified.csv", [("2026-10-16", 9999999)])
        a = self.run_analyze()
        self.assertIn("暂不能判断", a["recommendations"]["summary"])
        actions = {x["id"]: x for x in a["recommendations"]["actions"]}
        self.assertIn("complete_data", actions)
        self.assertIn("两者不是同一口径", actions["qualified_exposure"]["evidence"])
        self.assertIsNone(a["qualified_week_est"])
        self.assertIn("未读取", actions["verified_followers"]["evidence"])

    def test_threshold_met_never_implies_admission_and_config_cannot_change_official_rule(self):
        self.write_json(self.raw / "eligibility.json", {"text": "500K impressions\n600K", "items": []})
        self.write_json(self.root / "config.local.json", {"program": {"verified_home_impressions_90d_target": 1}})
        a = self.run_analyze()
        self.assertEqual(a["target_90d"], 500000)
        self.assertEqual(a["configured_target_90d"], 1)
        self.assertIn("仍须核对其他资格", a["recommendations"]["summary"])
        self.assertIn("由X审核", a["recommendations"]["summary"])

    def test_stale_and_future_policy_dates_require_review(self):
        a = self.run_analyze()
        policy = rec.load_policy()
        for day in (date(2026, 11, 18), date(2026, 10, 1)):
            generated = rec.generate(a, self.cfg, policy, as_of=day)
            self.assertTrue(generated["policy_stale"])
            self.assertEqual(generated["actions"][0]["id"], "review_policy")
            self.assertIn("规则快照需要复核", generated["summary"])

    def test_generic_categories_small_sample_and_overposting_are_not_official_requirements(self):
        self.write_json(self.root / "config.local.json", {"categories": {"美食": "美食"}})
        self.write_posts([post("美食案例", ident=str(i)) for i in range(6)])
        a = self.run_analyze()
        self.assertEqual(a["week"]["by_category"]["美食"]["posts"], 6)
        action = next(x for x in a["recommendations"]["actions"] if x["id"] == "topic_test")
        self.assertIn("美食", action["action"])
        self.assertEqual(action["kind"], "运营实验")
        self.assertIn("不能解释因果", action["review"])
        self.write_posts([post(ident=str(i)) for i in range(30)])
        a = self.run_analyze()
        action = next(x for x in a["recommendations"]["actions"] if x["id"] == "posting_plan")
        self.assertEqual(action["check"]["max"], 14)
        self.assertIn("合并重复信息", action["action"])
        self.assertIn("用户设置", action["evidence"])

    def test_keyword_match_is_not_a_violation_or_automatic_deletion(self):
        self.write_posts([post("求点赞转发，AI 合成测试")])
        a = self.run_analyze()
        action = next(x for x in a["recommendations"]["actions"] if x["id"] == "review_flags")
        self.assertIn("命中不代表X认定违规", action["evidence"])
        self.assertIn("不自动删除", action["action"])
        self.assertIsNone(action["check"])

    def test_previous_plan_reviews_metrics_only_and_manual_plan_is_not_skipped(self):
        folder = self.root / "reports/2026-10-10"
        folder.mkdir(parents=True)
        action = {"id": "count", "title": "主帖数", "check": {"metric": "week.main_posts", "min": 7}}
        self.write_json(folder / "analysis.json", {"recommendations": {"origin": "program", "actions": [action]}})
        a = self.run_analyze()
        self.assertEqual(a["recommendations"]["previous_review"][0]["status"], "指标未达标")
        self.write_json(folder / "analysis.json", {"recommendations": {"origin": "manual", "actions": []}})
        self.assertIsNone(rec.previous_actions(self.root, REPORT_DATE))

    @unittest.skipUnless(render, "需要 markdown")
    def test_policy_and_automatic_advice_are_rendered_without_unsafe_post_html(self):
        self.write_posts([post('<script>alert(1)</script> AI [标题](javascript:bad)')])
        a = self.run_analyze()
        self.run_script("render.py", "--date", REPORT_DATE)
        page = (self.report_dir / "report.html").read_text(encoding="utf-8")
        self.assertIn("X 官方规则依据", page)
        self.assertIn("AUTO-SUGGESTIONS:START", page)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("本机程序", page)
        block = re.search(re.escape(analyze.SUG_START) + r"(.*?)" + re.escape(analyze.SUG_END), (self.report_dir / "report.md").read_text(encoding="utf-8"), re.S)[1]
        self.assertTrue(rec.is_untouched_automatic(block))

    def test_frozen_resources_include_policy_without_using_personal_root(self):
        resources = self.root / "bundle"
        shutil.copytree(ROOT / "rules", resources / "rules")
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "_MEIPASS", str(resources), create=True):
            self.assertEqual(rec.load_policy()["version"], "2026-10-17")
