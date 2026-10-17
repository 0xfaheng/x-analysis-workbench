import json
import re
import unittest
from datetime import date, timedelta
from unittest import mock

from support import REPORT_DATE, WorkspaceTest, analyze, post


class NumberDateTests(unittest.TestCase):
    def test_parse_num(self):
        cases = [(None, None), ("", None), ("—", None), ("1,234", 1234), (" 2.5K ", 2500),
                 ("1.2m", 1200000), ("3万", 30000), (".5k", 500), ("0", 0),
                 ("1.2.3", None), (".", None), ("2亿", None), ("9" * 400, None)]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(analyze.parse_num(value), expected)

    def test_parse_date_english_without_locale_parser(self):
        # 非英文系统上的 strptime 无法识别导出的英文月份。
        with mock.patch("_strptime._strptime_time", side_effect=AssertionError("不可依赖区域设置")):
            self.assertEqual(analyze.parse_date(" Fri, Oct 16, 2026 "), date(2026, 10, 16))
            self.assertEqual(analyze.parse_date("fri, oct 9, 2026"), date(2026, 10, 9))
            self.assertEqual(analyze.parse_date("Thu, Feb 29, 2024"), date(2024, 2, 29))

    def test_parse_date_invalid(self):
        for value in ("2026-10-16", "Fri, Foo 16, 2026", "Fri, Feb 29, 2026", "", "Foo, Oct 16, 2026"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                analyze.parse_date(value)

    def test_fmt(self):
        for value, expected in [(None, "—"), (0, "0"), (9999, "9,999"), (10000, "1 万"),
                                (12500, "1.2 万"), (-20000, "-2 万")]:
            with self.subTest(value=value):
                self.assertEqual(analyze.fmt(value), expected)

    def test_delta(self):
        for cur, prev, expected in [(None, 100, None), (100, None, None), (10, 0, None),
                                    (100, 49, None), (100, 50, 1), (0, 100, -1), (150, 100, .5)]:
            with self.subTest(cur=cur, prev=prev):
                self.assertEqual(analyze.delta(cur, prev), expected)
        self.assertEqual(analyze.fmt_delta(None), "")
        self.assertEqual(analyze.fmt_delta(-.5), "（↓50%）")
        self.assertEqual(analyze.fmt_delta(0), "（↑0%）")

    def test_empty_stats(self):
        stats = analyze.post_stats([])
        self.assertEqual(stats["main_posts"], 0)
        self.assertIsNone(stats["median"])
        self.assertIsNone(stats["engagement_rate"])
        self.assertIsNone(stats["ai_share"])


class ClassificationTests(WorkspaceTest):
    def load_texts(self, texts):
        self.write_posts([post(t, ident=str(i)) for i, t in enumerate(texts)])
        return analyze.load_posts(self.raw, self.cfg)

    def test_categories_and_reply(self):
        posts = self.load_texts(["用 Claude 编程", "BTC 钱包", "周末散步", "@someone AI 测试回复",
                                "BTC AI AI", "AI BTC"])
        self.assertEqual([p["category"] for p in posts], ["AI", "web3", "其他", "AI", "AI", "web3"])
        self.assertEqual([p["reply"] for p in posts], [False, False, False, True, False, False])

    def test_risks_and_hype_only_web3(self):
        posts = self.load_texts(["AI Pro 20x 套餐", "BTC 20x", "BTC 梭哈", "AI 求点赞",
                                "低价充值", "BTC 0x" + "a" * 40, "AI https://example.com/20x"])
        self.assertEqual(posts[0]["risks"], [])
        self.assertIn("hype_call", posts[1]["risks"])
        self.assertIn("hype_call", posts[2]["risks"])
        self.assertIn("solicitation", posts[3]["risks"])
        self.assertIn("gray_market", posts[4]["risks"])
        self.assertIn("contract_address", posts[5]["risks"])
        self.assertNotIn("hype_call", posts[6]["risks"])

    def test_english_ignores_links_mentions_tokens_and_addresses(self):
        posts = self.load_texts(["This is a synthetic English test", "中文内容", "中文 https://example.com/english @tester $TOKEN 0xabcdef",
                                "https://example.com @tester $TOKEN 0xabcdef", "abc中文", "ab中文"])
        self.assertEqual([p["english"] for p in posts], [True, False, False, False, True, False])

    def test_link_and_one_liner(self):
        posts = self.load_texts(["说明 https://example.com/a", "说明 example.ai", "长" * 26, "普通合成文字"])
        self.assertEqual([p["has_link"] for p in posts], [True, True, False, False])
        self.assertEqual([p["one_liner"] for p in posts], [True, True, False, True])


class EligibilityTests(WorkspaceTest):
    def test_icons_and_value(self):
        self.write_json(self.raw / "eligibility.json", {
            "text": "近三个月曝光需 50 万\n进度\n123.4K",
            "items": [{"text": "已满足项目", "icon": analyze.ICON_MET + "rest"},
                      {"text": "未满足项目", "icon": analyze.ICON_UNMET + "rest"},
                      {"text": "说明文字", "icon": "info"}]})
        data = analyze.load_eligibility(self.raw)
        self.assertEqual(data["items"], [{"text": "已满足项目", "met": True}, {"text": "未满足项目", "met": False}])
        self.assertEqual(data["verified_home_90d"], 123400)
        self.assertFalse(data["maybe_enrolled"])

    def test_enrolled_missing_and_zero(self):
        self.assertIsNone(analyze.load_eligibility(self.raw))
        self.write_json(self.raw / "eligibility.json", {"text": "Your earnings and payouts", "items": []})
        self.assertTrue(analyze.load_eligibility(self.raw)["maybe_enrolled"])
        self.write_json(self.raw / "eligibility.json", {"text": "500,000 impressions\n0", "items": []})
        self.assertEqual(analyze.load_eligibility(self.raw)["verified_home_90d"], 0)

    def test_followers_utf8(self):
        (self.raw / "overview_all_3m.txt").write_text("合成数据\nVerified followers\n123\n/\n4.5K\n", encoding="utf-8", newline="\n")
        self.assertEqual(analyze.load_followers(self.raw), {"verified_followers": 123, "followers": 4500})


class AnalyzeIntegrationTests(WorkspaceTest):
    def test_first_run_without_reports_or_history(self):
        self.assertFalse((self.root / "reports").exists())
        self.assertFalse((self.root / "data" / "history.json").exists())
        a = self.run_analyze()
        self.assertIsNone(a["prev_suggestions"])
        self.assertEqual(a["week"]["main_posts"], 1)
        self.assertTrue((self.root / "data" / "history.json").is_file())
        self.assertIn("AI 合成测试内容", (self.report_dir / "report.md").read_text(encoding="utf-8"))

    def test_week_boundaries_exclude_report_day(self):
        self.write_posts([post(day=day, ident=str(i)) for i, day in enumerate([
            "2026-10-02", "2026-10-03", "2026-10-09", "2026-10-10", "2026-10-16", REPORT_DATE, "2026-10-18"])])
        self.write_daily("overview_all.csv", [("2026-10-09", 3), ("2026-10-10", 10), ("2026-10-16", 20), (REPORT_DATE, 999)])
        a = self.run_analyze()
        self.assertEqual(a["window"], ["2026-10-10", "2026-10-16"])
        self.assertEqual(a["prev_window"], ["2026-10-03", "2026-10-09"])
        self.assertEqual(a["week"]["main_posts"], 2)
        self.assertEqual(a["prev_week"]["main_posts"], 2)
        self.assertEqual(a["impr_all_week"], 30)
        self.assertEqual(a["impr_all_prev"], 3)
        self.assertNotIn(REPORT_DATE, [r["date"] for r in a["daily"]])

    def test_qualified_ratio_90_day_boundaries(self):
        start = (date.fromisoformat(REPORT_DATE) - timedelta(days=90)).isoformat()
        before = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
        self.write_daily("overview_verified.csv", [(before, 9999), (start, 100), ("2026-10-16", 100), (REPORT_DATE, 9999)])
        self.write_json(self.raw / "eligibility.json", {"text": "500K impressions\n100", "items": []})
        a = self.run_analyze()
        self.assertEqual(a["qualified_ratio"], .5)
        self.assertEqual(a["qualified_week_est"], 50)

    def test_zero_eligibility_is_zero_estimate(self):
        self.write_daily("overview_verified.csv", [("2026-10-16", 100)])
        self.write_json(self.raw / "eligibility.json", {"text": "500K impressions\n0", "items": []})
        a = self.run_analyze()
        self.assertEqual(a["qualified_ratio"], 0)
        self.assertEqual(a["qualified_week_est"], 0)
        self.assertEqual(a["steady_state_90d"], 0)

    def test_empty_csv_is_valid_but_missing_file_is_error(self):
        self.write_posts([])
        a = self.run_analyze()
        self.assertEqual(a["week"]["main_posts"], 0)
        self.assertIsNone(a["week"]["median"])
        (self.raw / "content_90d.csv").unlink()
        result = self.run_script("analyze.py", "--date", REPORT_DATE, success=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("缺少帖子数据", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_corrupt_or_headerless_csv_does_not_replace_report(self):
        self.run_analyze()
        before = (self.report_dir / "analysis.json").read_bytes()
        for content in ("", "错误列名\n", "Post id,Date,Post text,Post Link\n"):
            with self.subTest(content=content):
                (self.raw / "content_90d.csv").write_text(content, encoding="utf-8", newline="\n")
                result = self.run_script("analyze.py", "--date", REPORT_DATE, success=False)
                self.assertEqual(result.returncode, 1)
                self.assertIn("CSV 缺少必要列", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual((self.report_dir / "analysis.json").read_bytes(), before)

    def test_zero_daily_denominator_does_not_divide_by_zero(self):
        self.write_daily("overview_verified.csv", [("2026-10-16", 0)])
        self.write_json(self.raw / "eligibility.json", {"text": "500K impressions\n0", "items": []})
        a = self.run_analyze()
        self.assertEqual(a["impr_verified_week"], 0)
        self.assertIsNone(a["qualified_ratio"])
        self.assertIsNone(a["qualified_week_est"])

    def test_skipped_verified_export_does_not_reuse_stale_csv(self):
        self.write_daily("overview_verified.csv", [("2026-10-16", 99999)])
        self.write_json(self.raw / "meta.json", {"ok": True, "files": {"content_90d.csv": "synthetic.csv"}, "warnings": ["开关未找到"]})
        a = self.run_analyze()
        self.assertIsNone(a["impr_verified_week"])
        self.assertIsNone(a["qualified_ratio"])
        self.assertEqual(a["daily"], [])

    def test_rerun_preserves_suggestions_and_single_history_entry(self):
        self.run_analyze()
        path = self.report_dir / "report.md"
        suggestion = "按原文保留 **中文建议**\n\n---\n\n路径 C:\\test 与 [链接](https://example.com)\n"
        original = path.read_text(encoding="utf-8")
        original = re.sub(re.escape(analyze.SUG_START) + r".*?" + re.escape(analyze.SUG_END),
                          lambda _: analyze.SUG_START + "\n" + suggestion + analyze.SUG_END, original, flags=re.S)
        path.write_text(original, encoding="utf-8", newline="\n")
        self.run_analyze()
        self.assertEqual(path.read_text(encoding="utf-8"), original)
        a = json.loads((self.report_dir / "analysis.json").read_text(encoding="utf-8"))
        self.assertEqual(a["recommendations"]["origin"], "manual")
        history = json.loads((self.root / "data" / "history.json").read_text(encoding="utf-8"))
        self.assertEqual(len(history), 1)

    def test_previous_suggestions_skip_placeholder(self):
        self.assertIsNone(analyze.previous_suggestions(self.root, date.fromisoformat(REPORT_DATE)))
        for day, text in [("2026-10-03", "旧建议"), ("2026-10-10", analyze.SUG_PLACEHOLDER), (REPORT_DATE, "本期建议")]:
            folder = self.root / "reports" / day
            folder.mkdir(parents=True)
            (folder / "report.md").write_text(f"{analyze.SUG_START}\n{text}\n{analyze.SUG_END}", encoding="utf-8", newline="\n")
        self.assertEqual(analyze.previous_suggestions(self.root, date.fromisoformat(REPORT_DATE)), {"date": "2026-10-03", "text": "旧建议"})

    def test_failed_collection_does_not_generate_report(self):
        self.write_json(self.raw / "meta.json", {"ok": False, "reason": "error"})
        result = self.run_script("analyze.py", "--date", REPORT_DATE, success=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("采集失败", result.stderr)
        self.assertFalse((self.root / "reports").exists())


if __name__ == "__main__":
    unittest.main()
