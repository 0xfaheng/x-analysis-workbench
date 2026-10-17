import json
import re
import shutil
import subprocess
import unittest
from html.parser import HTMLParser

from support import REPORT_DATE, WorkspaceTest, analyze, post, render


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.anchors = []
        self.current_anchor = None
        self.scripts = []
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == "a":
            self.current_anchor = {"attrs": dict(attrs), "text": "", "children": []}
            self.anchors.append(self.current_anchor)
        elif self.current_anchor is not None:
            self.current_anchor["children"].append(tag)
        if tag == "script":
            self.scripts.append("")
            self.in_script = True

    def handle_endtag(self, tag):
        if tag == "a":
            self.current_anchor = None
        if tag == "script":
            self.in_script = False

    def handle_data(self, data):
        if self.current_anchor is not None:
            self.current_anchor["text"] += data
        if self.in_script:
            self.scripts[-1] += data


@unittest.skipUnless(render, "需要可选的 markdown 依赖")
class RenderTests(WorkspaceTest):
    def test_no_reports_is_friendly_error(self):
        for make_directory in (False, True):
            if make_directory:
                (self.root / "reports").mkdir()
            result = self.run_script("render.py", success=False)
            self.assertEqual(result.returncode, 1)
            self.assertIn("还没有任何报告", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_unknown_date_and_missing_markdown_are_friendly_errors(self):
        self.run_analyze()
        result = self.run_script("render.py", "--date", "2026-01-01", success=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("报告文件不存在", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        (self.report_dir / "report.md").unlink()
        result = self.run_script("render.py", success=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("report.md", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_complete_pipeline_utf8_lf_and_rerun_bytes(self):
        self.run_analyze()
        self.run_script("render.py")
        paths = [self.root / "data" / "history.json", self.report_dir / "analysis.json",
                 self.report_dir / "report.md", self.report_dir / "report.html", self.root / "index.html"]
        before = {p: p.read_bytes() for p in paths}
        self.run_analyze()
        self.run_script("render.py")
        for path in paths:
            with self.subTest(path=path.name):
                data = path.read_bytes()
                self.assertNotIn(b"\r\n", data)
                self.assertEqual(data, before[path])
                data.decode("utf-8")
        self.assertFalse(list(self.root.rglob("*.tmp")))

    def test_post_special_characters_remain_literal_link_text(self):
        texts = [r"[方] (案) | *星* _线_ <b> & `码` \ 路径", '<img src=x onerror="boom()">',
                 "点击 ](javascript:alert(1)) [伪链接", "正常中文帖子完全保持原样"]
        self.write_posts([post(t, ident=str(i)) for i, t in enumerate(texts)])
        self.run_analyze()
        self.run_script("render.py")
        md = (self.report_dir / "report.md").read_text(encoding="utf-8")
        self.assertIn("[正常中文帖子完全保持原样](https://x.com/test_account/status/3)", md)
        self.assertIn(r"\[方\] \(案\) \| \*星\* \_线\_ &lt;b&gt; &amp; \`码\` \\ 路径", md)
        self.assertNotIn("<img", md)
        parser = PageParser()
        parser.feed((self.report_dir / "report.html").read_text(encoding="utf-8"))
        links = [a for a in parser.anchors if a["attrs"].get("href", "").startswith("https://x.com/test_account/status/")]
        # 最佳帖列表与新增选题备忘均可能引用同一帖，每次展示都必须保留原文转义。
        self.assertEqual([a["text"] for a in links[:len(texts)]], texts)
        self.assertTrue(all(a["text"] in texts for a in links))
        self.assertTrue(all(not a["children"] for a in links))
        self.assertNotIn("img", parser.tags)

    def test_escape_markdown_in_table(self):
        text = r"甲|乙 [丙] *丁* _戊_ `己` <b> & \\"
        body = render.markdown.markdown("| 原文 | 指标 |\n|---|---|\n| " + analyze.escape_markdown(text) + " | 1 |\n", extensions=["tables"])
        parser = PageParser()
        parser.feed(body)
        self.assertEqual(parser.tags.count("td"), 2)
        self.assertNotIn("b", parser.tags)
        self.assertNotIn("em", parser.tags)
        self.assertNotIn("code", parser.tags)

    def test_bottom_and_risk_post_text_are_also_escaped(self):
        special = "AI 求点赞 | [合成] <img src=x> *强调*"
        self.write_posts([post("AI 普通合成样本", ident=str(i), impressions=100 + i) for i in range(5)]
                         + [post(special, ident="99", impressions=1)])
        a = self.run_analyze()
        page = render.render_page(self.root, REPORT_DATE, a, analyze.build_report(a), "", "")
        parser = PageParser()
        parser.feed(page)
        links = [a for a in parser.anchors if a["attrs"].get("href", "").endswith("/status/99")]
        self.assertEqual(len(links), 2)
        self.assertTrue(all(a["text"] == special and not a["children"] for a in links))
        self.assertNotIn("img", parser.tags)

    def test_suggestions_with_rules_close_after_end_marker(self):
        a = self.run_analyze()
        a["recommendations"].update(origin="manual", markdown="第一段建议\n\n---\n\n第二段建议\n\n---\n\n最后一段建议")
        md = analyze.build_report(a)
        page = render.render_page(self.root, REPORT_DATE, a, md, "", "")
        self.assertEqual(page.count('<div class="suggest">'), 1)
        block = page.split('<div class="suggest">', 1)[1].split("</div>", 1)[0]
        self.assertIn("最后一段建议", block)
        self.assertIn(render.SUG_END, block)
        self.assertEqual(block.count("<hr />"), 2)
        self.assertNotIn("数据来源：", block)
        self.assertIn("</div><hr />", page)

    def test_earlier_horizontal_rule_does_not_close_suggestions(self):
        a = self.run_analyze()
        md = analyze.build_report(a).replace("## 2. 本周核心数据", "---\n\n## 2. 本周核心数据")
        page = render.render_page(self.root, REPORT_DATE, a, md, "", "")
        block = page.split('<div class="suggest">', 1)[1].split("</div>", 1)[0]
        self.assertIn(render.SUG_START, block)
        self.assertIn(render.SUG_END, block)

    def test_template_tokens_in_content_are_preserved(self):
        a = self.run_analyze()
        a["recommendations"].update(origin="manual", markdown="保留 __DATA__ 与 __HISTORY_LIST__")
        md = analyze.build_report(a)
        # 用代码文字避免 Markdown 把下划线当成强调。
        md += "\n`__DATA__ __HISTORY_LIST__`\n"
        page = render.render_page(self.root, REPORT_DATE, a, md, "", "")
        self.assertIn("<code>__DATA__ __HISTORY_LIST__</code>", page)

    def test_json_script_cannot_be_ended_or_double_escaped_by_post(self):
        self.write_posts([post("<!--<script></script><img src=x onerror='boom()'>")])
        a = self.run_analyze()
        page = render.render_page(self.root, REPORT_DATE, a, analyze.build_report(a), "", "")
        parser = PageParser()
        parser.feed(page)
        self.assertEqual(len(parser.scripts), 1)
        payload = re.search(r"const A = (.*);", parser.scripts[0])[1]
        self.assertNotIn("<", payload)
        self.assertEqual(json.loads(payload)["week_posts"][0]["text"], a["week_posts"][0]["text"])

    def test_empty_posts_render(self):
        self.write_posts([])
        self.run_analyze()
        self.run_script("render.py")
        self.assertTrue((self.report_dir / "report.html").is_file())

    @unittest.skipUnless(shutil.which("node"), "需要 Node 验证网页脚本")
    def test_javascript_escaping_and_missing_verified_series(self):
        a = self.run_analyze()
        evil = '<img src=x onerror="boom()"> & \'文字\''
        a["eligibility"] = {"items": [{"met": False, "text": evil}], "verified_home_90d": 0}
        a["phase"]["name"] = evil
        a["daily"] = [{"date": evil, "all": 100, "verified": None}]
        a["week_posts"][0].update(text=evil, category=evil)
        a["history"][0]["report_date"] = evil
        a["history"].append(dict(a["history"][0]))
        page = render.render_page(self.root, REPORT_DATE, a, analyze.build_report(a), "", "")
        parser = PageParser()
        parser.feed(page)
        # 最小 DOM 替身：执行真实模板脚本和鼠标回调，不打开浏览器、不访问网络。
        harness = r'''
import assert from 'node:assert/strict';
const nodes = {}, all = [];
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this.style = {}; this.attributes = {}; this.clientWidth = 1000; this.offsetWidth = 200; this.innerHTML = ''; all.push(this); }
  appendChild(e) { this.children.push(e); return e; }
  setAttribute(k, v) { assert(!/NaN|Infinity/.test(String(v))); this.attributes[k] = String(v); }
  addEventListener(k, fn) { (this.listeners[k] ||= []).push(fn); }
  getBoundingClientRect() { return { left: 0, top: 0, width: 1000 }; }
}
globalThis.document = {
  getElementById: id => nodes[id] ||= new Element('div'),
  querySelector: () => nodes.root ||= new Element('div'),
  createElement: tag => new Element(tag),
  createElementNS: (ns, tag) => new Element(tag),
};
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '#123456' });
globalThis.window = { open: () => { throw new Error('测试不得打开网页'); } };
'''
        assertions = r'''
for (const e of all.slice()) for (const fn of e.listeners.mousemove || []) fn({ clientX: 200, clientY: 100 });
assert(nodes['daily-table'].innerHTML.includes('&lt;img'));
assert(nodes['history-table'].innerHTML.includes('&lt;img'));
assert(nodes.tiles.innerHTML.includes('&lt;img'));
assert(nodes.tiles.innerHTML.includes('&amp;'));
for (const e of all) assert(!e.innerHTML.includes('<img'));
assert(all.some(e => e.className === 'tip' && e.innerHTML.includes('&lt;img')));
assert.equal(esc('&<>"\''), '&amp;&lt;&gt;&quot;&#39;');
'''
        result = subprocess.run([shutil.which("node"), "--input-type=module"],
                                input=harness + parser.scripts[0] + assertions,
                                text=True, encoding="utf-8", capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
