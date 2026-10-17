"""只生成临时合成数据；不读取真实帖子或报告。"""
import copy
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import analyze
try:
    import render
except ModuleNotFoundError as error:
    if error.name != "markdown":
        raise
    render = None

REPORT_DATE = "2026-10-17"
POST_COLUMNS = ["Post id", "Date", "Post text", "Post Link", "Impressions", "Likes",
                "Engagements", "Bookmarks", "Shares", "New follows", "Replies",
                "Reposts", "Profile visits", "URL Clicks"]


def csv_date(value):
    d = date.fromisoformat(value)
    weekdays = "Mon Tue Wed Thu Fri Sat Sun".split()
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    return f"{weekdays[d.weekday()]}, {months[d.month - 1]} {d.day:02d}, {d.year}"


def post(text="AI 合成测试内容", day="2026-10-16", impressions=100, ident="1"):
    row = {col: "0" for col in POST_COLUMNS}
    row.update({"Post id": ident, "Date": csv_date(day), "Post text": text,
                "Post Link": f"https://x.com/test_account/status/{ident}",
                "Impressions": str(impressions), "Engagements": "10"})
    return row


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="x-workbench-test-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.raw = self.root / "data" / "raw" / REPORT_DATE
        self.raw.mkdir(parents=True)
        # 规则取项目配置，帖子、指标及账号均为合成数据。
        self.cfg = copy.deepcopy(json.loads((ROOT / "config.json").read_text(encoding="utf-8")))
        self.cfg["handle"] = "test_account"
        self.cfg.pop("app", None)
        self.write_json(self.root / "config.json", self.cfg)
        self.write_json(self.raw / "meta.json", {"ok": True, "finished_at": "2026-10-17T01:00:00Z"})
        self.write_posts([post()])

    @property
    def report_dir(self):
        return self.root / "reports" / REPORT_DATE

    def write_json(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    def write_csv(self, name, columns, rows):
        with (self.raw / name).open("w", encoding="utf-8-sig", newline="\n") as f:
            writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def write_posts(self, rows):
        self.write_csv("content_90d.csv", POST_COLUMNS, rows)

    def write_daily(self, name, values):
        self.write_csv(name, ["Date", "Impressions", "New follows", "Unfollows"],
                       [{"Date": csv_date(day), "Impressions": str(value), "New follows": "1", "Unfollows": "0"}
                        for day, value in values])

    def run_script(self, name, *args, success=True):
        result = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / name),
                                 "--root", str(self.root), *args],
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def run_analyze(self):
        self.run_script("analyze.py", "--date", REPORT_DATE)
        return json.loads((self.report_dir / "analysis.json").read_text(encoding="utf-8"))
