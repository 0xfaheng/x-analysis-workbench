"""执行真实前端脚本的最小 DOM 替身；不启动浏览器。"""
import shutil
import subprocess
import unittest

from support import ROOT


@unittest.skipUnless(shutil.which("node"), "需要 Node 验证桌面脚本")
class DesktopScriptTests(unittest.TestCase):
    def run_js(self, source):
        result = subprocess.run([shutil.which("node"), "--input-type=module"], input=source,
                                text=True, encoding="utf-8", capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_report_links_window_open_and_navigation_hiding(self):
        script = (ROOT / "desktop/ui/report.js").read_text(encoding="utf-8")
        harness = r'''
import assert from 'node:assert/strict';
const events = {}, opened = [], styles = [];
globalThis.window = {};
globalThis.parent = { XWBReport: url => opened.push(url) };
globalThis.location = { href: 'http://127.0.0.1:123/secret/reports/2026-10-17/report.html', origin: 'http://127.0.0.1:123' };
globalThis.document = {
  addEventListener: (name, cb) => events[name] = cb,
  createElement: () => ({}), head: { append: value => styles.push(value) }
};
'''
        assertions = r'''
window.open('https://x.com/test_account/status/1', '_blank');
window.open('javascript:alert(1)');
assert.equal(opened.length, 1);
for (const name of ['click', 'auxclick']) {
  let prevented = false, stopped = false;
  events[name]({ target: { closest: () => ({ href: 'https://example.com/article' }) },
    preventDefault: () => prevented = true, stopImmediatePropagation: () => stopped = true });
  assert(prevented && stopped);
}
let prevented = false;
events.click({ target: { closest: () => ({ href: location.href + '#section' }) }, preventDefault: () => prevented = true });
assert.equal(prevented, false);
events.DOMContentLoaded();
assert(styles[0].textContent.includes('.nav, .history { display: none !important; }'));
assert.equal(opened.length, 3);
'''
        self.run_js(harness + script + assertions)

    def test_shell_refresh_preserves_selection_and_reloads_changed_report(self):
        script = (ROOT / "desktop/ui/app.js").read_text(encoding="utf-8")
        harness = r'''
import assert from 'node:assert/strict';
const nodes = {};
function node() { return { textContent: '', hidden: false, children: [], classList: {add(){}, toggle(){}},
  setAttribute(){}, addEventListener(){}, append(x){this.children.push(x)}, replaceChildren(){this.children=[]},
  querySelector(){return node()} }; }
globalThis.document = { getElementById: id => nodes[id] ||= node(), querySelectorAll: () => [], createElement: node };
globalThis.window = { addEventListener(){}, pywebview: { api: { list_reports: async () => data } } };
const first = {id: '2026-10-17', modified: 10, progress: .1, pending: true, url: 'reports/2026-10-17/report.html'};
const second = {...first, id: '2026-10-24', url: 'reports/2026-10-24/report.html'};
let data = {reports:[first], handle:'test_account', version:'2.0.0', assistant:false};
'''
        assertions = r'''
await refresh();
assert.equal(selection, first.id);
assert(nodes.report.src.includes(first.url));
data.reports = [second, first];
await refresh();
assert.equal(selection, first.id);
data.reports = [second, {...first, modified:20}];
await refresh();
assert(nodes.report.src.endsWith('?v=20'));
await refresh(true);
assert.equal(selection, second.id);
assert(nodes.report.src.includes(second.url));
'''
        self.run_js(harness + script + assertions)
