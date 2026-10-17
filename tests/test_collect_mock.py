"""只在明确开启的 CI 浏览器测试中启动系统 Edge；绝不访问真实 X。"""
import contextlib
import csv
import importlib.util
import io
import json
import os
import shutil
import subprocess
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html.parser import HTMLParser
from unittest import mock
from urllib.parse import urlsplit

from support import POST_COLUMNS, REPORT_DATE, WorkspaceTest, csv_date, post, render
import collect_playwright as cp
import run_weekly


def csv_bytes(columns, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def mock_handler(requests):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(handler):
            route = urlsplit(handler.path).path
            requests.append(handler.path)
            if route.startswith("/csv/"):
                if route == "/csv/posts":
                    body = csv_bytes(POST_COLUMNS, [post()])
                else:
                    body = csv_bytes(["Date", "Impressions", "New follows", "Unfollows"], [{
                        "Date": csv_date("2026-10-16"), "Impressions": "123" if route.endswith("verified") else "456",
                        "New follows": "1", "Unfollows": "0"}])
                handler.send_response(200)
                handler.send_header("Content-Type", "text/csv")
                handler.send_header("Content-Disposition", 'attachment; filename="synthetic.csv"')
            else:
                logged_out = route.startswith("/signed-out/")
                content = '<button data-testid="SideNav_AccountSwitcher_Button">合成用户 @test_account</button>' if not logged_out else "请先登录"
                if route.endswith("original_content_rewards"):
                    content += '<main><div><svg><path d="M12 1.75C6.34 test"/></svg><p>已认证粉丝</p></div><div><svg><path d="M12 3.75c test"/></svg><p>近 90 天曝光需 50 万</p></div><p>123.4K</p></main>'
                elif route.endswith("/content"):
                    # 同时检验 posts、days 等完整查询串。
                    if urlsplit(handler.path).query != "type=posts&sort=date&dir=desc&days=90":
                        handler.send_error(400)
                        return
                    content += '<main>帖子明细<button aria-label="Download CSV" onclick="location.href=\'/csv/posts\'">下载</button></main>'
                elif route.endswith("/audience"):
                    content += '<main><button onclick="this.dataset.selected=1">28D</button><p>合成受众：25–34 岁</p></main>'
                elif route.endswith("account_analytics"):
                    content += '''<main><button onclick="this.dataset.selected=1">3M</button>
                    <button id="verified" aria-label="Verified only" aria-pressed="false" onclick="this.setAttribute('aria-pressed', this.getAttribute('aria-pressed')==='true'?'false':'true')">认证</button>
                    <button aria-label="Download CSV" onclick="location.href='/csv/'+(document.getElementById('verified').getAttribute('aria-pressed')==='true'?'verified':'all')">下载</button>
                    <p>Verified followers<br>123<br>/<br>456</p></main>'''
                else:
                    content += '<main>合成首页</main>'
                body = ('<!doctype html><html><head><meta charset="utf-8"></head><body>' + content + '</body></html>').encode("utf-8")
                handler.send_response(200)
                handler.send_header("Content-Type", "text/html; charset=utf-8")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)

        def log_message(self, *_):
            pass

    return Handler


class MockSiteFixtureTests(unittest.TestCase):
    def test_mock_pages_have_valid_download_controls_without_starting_browser(self):
        class Parser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.buttons = []

            def handle_starttag(self, tag, attrs):
                if tag == "button":
                    self.buttons.append(dict(attrs))

        requests = []
        handler_class = mock_handler(requests)
        for route in ("/mock/i/account_analytics", "/mock/i/account_analytics/content?type=posts&sort=date&dir=desc&days=90"):
            handler = handler_class.__new__(handler_class)
            handler.path, handler.request_version, handler.requestline, handler.command = route, "HTTP/1.1", "GET " + route, "GET"
            handler.wfile = io.BytesIO()
            handler.do_GET()
            headers, body = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
            self.assertIn(b" 200 ", headers)
            parser = Parser()
            parser.feed(body.decode("utf-8"))
            downloads = [b for b in parser.buttons if b.get("aria-label") == "Download CSV"]
            self.assertEqual(len(downloads), 1)
            self.assertIn("location.href=", downloads[0]["onclick"])
            if shutil.which("node"):
                js = "\n".join("function click(){" + b["onclick"] + "}" for b in parser.buttons if "onclick" in b)
                result = subprocess.run([shutil.which("node"), "--check"], input=js,
                                        text=True, encoding="utf-8", capture_output=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(os.environ.get("XWB_BROWSER_TESTS") == "1", "仅在 XWB_BROWSER_TESTS=1 时启动浏览器")
class MockCollectionTests(WorkspaceTest):
    def test_full_collection_and_logged_out(self):
        # 启用测试时依赖缺失必须失败，避免 CI 意外跳过真实采集路径。
        self.assertIsNotNone(importlib.util.find_spec("playwright"), "请安装 Playwright")
        self.assertIsNotNone(render, "请安装 Markdown")
        requests = []

        Handler = mock_handler(requests)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        config = {"backend": "playwright", "base_url": base + "/mock", "headless": True,
                  "browser_channel": os.environ.get("XWB_BROWSER_CHANNEL", "msedge")}
        # 仍走真实 Playwright；只缩短页面稳定等待，下载与选择器不 mock。
        with contextlib.ExitStack() as stack:
            for name in ("ELIGIBILITY_WAIT_MS", "OVERVIEW_WAIT_MS", "CONTENT_WAIT_MS", "AUDIENCE_WAIT_MS", "RANGE_WAIT_MS", "VERIFIED_WAIT_MS"):
                stack.enter_context(mock.patch.object(cp, name, 30))
            stack.enter_context(mock.patch.object(cp, "LOGIN_WAIT_MS", 300))
            self.write_json(self.root / "config.local.json", {"collector": config})
            self.assertEqual(run_weekly.main(["--root", str(self.root), "--date", REPORT_DATE]), 0)
            expected = {"meta.json", "eligibility.json", "overview_all_3m.txt", "overview_verified_3m.txt",
                        "overview_all.csv", "overview_verified.csv", "content_90d.csv", "audience.txt"}
            self.assertTrue(expected.issubset({p.name for p in self.raw.iterdir()}))
            meta = json.loads((self.raw / "meta.json").read_text(encoding="utf-8"))
            self.assertTrue(meta["ok"])
            self.assertEqual(meta["backend"], "playwright")
            self.assertEqual(set(meta["files"]), {"overview_all.csv", "overview_verified.csv", "content_90d.csv"})
            eligibility = json.loads((self.raw / "eligibility.json").read_text(encoding="utf-8"))
            self.assertEqual(len(eligibility["items"]), 2)
            self.assertTrue((self.report_dir / "report.html").exists())
            self.assertIn("/csv/verified", requests)
            self.assertIn("/csv/all", requests)
            before = (self.report_dir / "report.html").read_bytes()
            config["base_url"] = base + "/signed-out"
            self.write_json(self.root / "config.local.json", {"collector": config})
            requests.clear()
            self.assertEqual(run_weekly.main(["--root", str(self.root), "--date", REPORT_DATE]), 3)
            failure = json.loads((self.raw / "meta.json").read_text(encoding="utf-8"))
            self.assertFalse(failure["ok"])
            self.assertEqual(failure["reason"], "not_logged_in")
            self.assertEqual(failure["backend"], "playwright")
            self.assertFalse(any("analytics" in r for r in requests))
            self.assertEqual((self.report_dir / "report.html").read_bytes(), before)
