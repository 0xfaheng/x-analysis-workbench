#!/usr/bin/env python3
"""把 reports/<日期>/report.md + analysis.json 渲染成网页，并刷新工作台首页 index.html。

用法：python3 scripts/render.py --root <工作台目录> [--date YYYY-MM-DD]
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path

import markdown

sys.path.insert(0, str(Path(__file__).resolve().parent))
from file_utils import atomic_write_text, ensure_utf8_stdio
from config_utils import load_config

SUG_START = "<!-- SUGGESTIONS:START -->"
SUG_END = "<!-- SUGGESTIONS:END -->"

TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
.viz-root {
  color-scheme: light;
  --page: #f9f9f7; --surface-1: #fcfcfb; --text-primary: #0b0b0b; --text-secondary: #52514e;
  --muted: #898781; --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a;
  --good: #006300; --critical: #d03b3b; --track: #e1e0d9;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) .viz-root {
    color-scheme: dark;
    --page: #0d0d0d; --surface-1: #1a1a19; --text-primary: #f0efec; --text-secondary: #c3c2b7;
    --muted: #898781; --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70;
    --good: #0ca30c; --critical: #e66767; --track: #2c2c2a;
  }
}
* { box-sizing: border-box; }
body { margin: 0; }
.viz-root { background: var(--page); color: var(--text-primary); min-height: 100vh;
  font-family: system-ui, -apple-system, "PingFang SC", "Segoe UI", sans-serif; line-height: 1.6; }
.wrap { max-width: 1080px; margin: 0 auto; padding: 28px 20px 60px; }
header h1 { font-size: 22px; margin: 0 0 4px; }
header .sub { color: var(--text-secondary); font-size: 13px; }
.nav { margin-top: 10px; font-size: 13px; color: var(--text-secondary); }
.nav a { color: var(--series-1); }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin: 20px 0; }
.tile, .card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }
.tile .label { font-size: 12px; color: var(--text-secondary); }
.tile .value { font-size: 26px; font-weight: 650; margin-top: 2px; }
.tile .note { font-size: 12px; color: var(--muted); }
.hero { grid-column: 1 / -1; }
.hero .value { font-size: 34px; }
.bar { height: 10px; background: var(--track); border-radius: 5px; margin: 10px 0 6px; overflow: hidden; }
.bar > span { display: block; height: 100%; background: var(--series-1); border-radius: 5px; }
.checks { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 13px; color: var(--text-secondary); margin-top: 8px; }
.card { margin: 16px 0; }
.card h2 { font-size: 16px; margin: 0 0 2px; }
.card .desc { font-size: 12px; color: var(--muted); margin-bottom: 8px; }
.legend { display: flex; gap: 16px; font-size: 12px; color: var(--text-secondary); margin: 4px 0 8px; }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: -1px; }
.chart { position: relative; }
.chart svg { display: block; width: 100%; height: auto; overflow: visible; }
.chart text { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.tip { position: absolute; pointer-events: none; background: var(--surface-1); border: 1px solid var(--border);
  border-radius: 8px; padding: 8px 10px; font-size: 12px; color: var(--text-primary); box-shadow: 0 4px 16px rgba(0,0,0,.12);
  display: none; max-width: 320px; z-index: 5; }
.tip .t { color: var(--text-secondary); margin-bottom: 2px; }
details { margin-top: 8px; font-size: 13px; }
details summary { cursor: pointer; color: var(--text-secondary); }
.report { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 8px 24px 20px; margin-top: 16px; }
.report h1 { display: none; }
.report h2 { font-size: 18px; margin-top: 26px; padding-top: 12px; border-top: 1px solid var(--grid); }
.report h2:first-of-type { border-top: 0; }
.report a { color: var(--series-1); }
table { border-collapse: collapse; width: 100%; font-size: 13px; margin: 8px 0; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--grid); vertical-align: top; }
th { color: var(--text-secondary); font-weight: 600; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.suggest { border-left: 3px solid var(--series-1); padding-left: 14px; }
.history li { margin: 2px 0; }
</style>
</head>
<body>
<div class="viz-root">
<div class="wrap">
<header>
  <h1>X 分析工作台 · @__HANDLE__</h1>
  <div class="sub">__SUBTITLE__</div>
  <div class="nav">__NAV__</div>
</header>
<section class="tiles" id="tiles"></section>

<div class="card">
  <h2>每日曝光（近 90 天）</h2>
  <div class="desc">账号总曝光与认证用户曝光（都含回复）。门槛只计算认证用户在首页时间线看到主帖的曝光。</div>
  <div class="legend"><span><i style="background:var(--series-1)"></i>全部用户</span><span><i style="background:var(--series-2)"></i>认证用户</span></div>
  <div class="chart" id="daily"></div>
  <details><summary>表格视图</summary><div id="daily-table"></div></details>
</div>

<div class="card">
  <h2>本周主帖曝光</h2>
  <div class="desc">按曝光从高到低排列，颜色表示内容类别；虚线为本阶段中位数目标。</div>
  <div class="legend"><span><i style="background:var(--series-1)"></i>AI</span><span><i style="background:var(--series-2)"></i>web3</span><span><i style="background:var(--series-3)"></i>其他</span></div>
  <div class="chart" id="posts"></div>
</div>

<div class="card">
  <h2>收益资格进度（历次周报）</h2>
  <div class="desc">Creator Studio 显示的「近 90 天认证用户首页曝光」，目标 50 万。</div>
  <div class="chart" id="history"></div>
  <details open><summary>表格视图</summary><div id="history-table"></div></details>
</div>

<article class="report">__REPORT__</article>
__HISTORY_LIST__
</div>
</div>
<script>
const A = __DATA__;
const esc = (v) => String(v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const css = (v) => getComputedStyle(document.querySelector('.viz-root')).getPropertyValue(v).trim();
const fmt = (n) => n == null ? '—' : (Math.abs(n) >= 10000 ? (n / 10000).toFixed(1).replace(/\.0$/, '') + ' 万' : n.toLocaleString('zh-CN'));
const NS = 'http://www.w3.org/2000/svg';
const el = (tag, attrs = {}, parent) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; };
function niceMax(v) { if (v <= 0) return 1; const p = Math.pow(10, Math.floor(Math.log10(v))); for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p; return 10 * p; }
function tipFor(box) { const t = document.createElement('div'); t.className = 'tip'; box.appendChild(t); return t; }
function placeTip(tip, box, x, y, html) { tip.innerHTML = html; tip.style.display = 'block'; const w = tip.offsetWidth; const bw = box.clientWidth; tip.style.left = Math.min(Math.max(x + 12, 0), bw - w) + 'px'; tip.style.top = (y + 12) + 'px'; }
function table(id, head, rows, numCols) {
  const h = '<table><thead><tr>' + head.map((c, i) => `<th class="${numCols.includes(i) ? 'num' : ''}">${esc(c)}</th>`).join('') + '</tr></thead><tbody>' +
    rows.map(r => '<tr>' + r.map((c, i) => `<td class="${numCols.includes(i) ? 'num' : ''}">${esc(c)}</td>`).join('') + '</tr>').join('') + '</tbody></table>';
  document.getElementById(id).innerHTML = h;
}

// ---- 指标卡 ----
(function tiles() {
  const e = A.eligibility || {}; const v = e.verified_home_90d; const T = A.target_90d;
  const p = v != null ? Math.min(v / T, 1) : 0;
  const checks = (e.items || []).map(i => `<span>${i.met ? '✅ 已满足' : '❌ 未满足'}：${esc(i.text)}</span>`).join('');
  const wk = A.week;
  const box = document.getElementById('tiles');
  box.innerHTML = `
  <div class="tile hero"><div class="label">近 90 天认证用户首页曝光（收益门槛 50 万）</div>
    <div class="value">${esc(fmt(v))} <span style="font-size:15px;font-weight:500;color:var(--text-secondary)">/ 50 万 · ${v != null ? (v / T * 100).toFixed(1) + '%' : '—'}</span></div>
    <div class="bar" role="img" aria-label="进度 ${(p * 100).toFixed(1)}%"><span style="width:${(p * 100).toFixed(2)}%"></span></div>
    <div class="note">按本周速度推算的 90 天稳态：${esc(fmt(A.steady_state_90d))}；每周约需 ${esc(fmt(Math.round(T * 7 / 90)))}</div>
    <div class="checks">${checks}</div></div>
  <div class="tile"><div class="label">认证粉丝 / 总粉丝</div><div class="value">${esc(fmt((A.followers || {}).verified_followers))}</div><div class="note">总粉丝 ${esc(fmt((A.followers || {}).followers))}</div></div>
  <div class="tile"><div class="label">本周认证用户曝光（含回复）</div><div class="value">${esc(fmt(A.impr_verified_week))}</div><div class="note">上周 ${esc(fmt(A.impr_verified_prev))}</div></div>
  <div class="tile"><div class="label">本周主帖 · 中位数曝光</div><div class="value">${esc(fmt(wk.median))}</div><div class="note">${esc(wk.main_posts)} 条主帖，最高 ${esc(fmt(wk.max))}</div></div>
  <div class="tile"><div class="label">阶段目标达成</div><div class="value">${A.targets.filter(t => t.ok).length} / ${A.targets.length}</div><div class="note">${esc(A.phase.name)}</div></div>`;
})();

// ---- 每日曝光折线 ----
(function daily() {
  const box = document.getElementById('daily'); const d = A.daily; if (!d.length) { box.textContent = '无数据'; return; }
  const W = 1000, H = 260, m = { l: 48, r: 70, t: 10, b: 26 };
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': '近 90 天每日曝光折线图' }, box);
  const ymax = niceMax(Math.max(...d.map(r => r.all)));
  const x = i => m.l + (W - m.l - m.r) * (d.length === 1 ? 0.5 : i / (d.length - 1));
  const y = v => m.t + (H - m.t - m.b) * (1 - v / ymax);
  for (let k = 0; k <= 4; k++) { const v = ymax * k / 4; el('line', { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), stroke: css('--grid'), 'stroke-width': 1 }, svg); const t = el('text', { x: m.l - 8, y: y(v) + 4, 'text-anchor': 'end' }, svg); t.textContent = fmt(v); }
  el('line', { x1: m.l, x2: W - m.r, y1: y(0), y2: y(0), stroke: css('--axis'), 'stroke-width': 1 }, svg);
  const step = Math.ceil(d.length / 8);
  d.forEach((r, i) => { if (i % step === 0 || i === d.length - 1) { const t = el('text', { x: x(i), y: H - 6, 'text-anchor': 'middle' }, svg); t.textContent = r.date.slice(5); } });
  const series = [['all', '--series-1', '全部'], ['verified', '--series-2', '认证']];
  const endLabels = [];
  for (const [k, c, name] of series) {
    const pts = d.map((r, i) => r[k] == null ? null : [x(i), y(r[k])]).filter(Boolean);
    if (!pts.length) continue;
    el('path', { d: pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(''), fill: 'none', stroke: css(c), 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, svg);
    endLabels.push({ y: pts[pts.length - 1][1] + 4, x: pts[pts.length - 1][0] + 8, name });
  }
  // 末端标签至少间隔 14px，避免两条线收尾接近时重叠
  endLabels.sort((a, b) => a.y - b.y);
  for (let i = 1; i < endLabels.length; i++) endLabels[i].y = Math.max(endLabels[i].y, endLabels[i - 1].y + 14);
  for (const l of endLabels) { const t = el('text', { x: l.x, y: l.y }, svg); t.textContent = l.name; t.style.fill = css('--text-secondary'); }
  const cross = el('line', { y1: m.t, y2: H - m.b, stroke: css('--axis'), 'stroke-width': 1, visibility: 'hidden' }, svg);
  const dots = series.map(([, c]) => el('circle', { r: 4, fill: css(c), stroke: css('--surface-1'), 'stroke-width': 2, visibility: 'hidden' }, svg));
  const hit = el('rect', { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: 'transparent' }, svg);
  const tip = tipFor(box);
  hit.addEventListener('mousemove', ev => {
    const r = svg.getBoundingClientRect(); const sx = (ev.clientX - r.left) * W / r.width;
    const i = Math.max(0, Math.min(d.length - 1, Math.round((sx - m.l) / (W - m.l - m.r) * (d.length - 1))));
    cross.setAttribute('x1', x(i)); cross.setAttribute('x2', x(i)); cross.setAttribute('visibility', 'visible');
    series.forEach(([k], j) => { const v = d[i][k]; dots[j].setAttribute('cx', x(i)); dots[j].setAttribute('cy', y(v || 0)); dots[j].setAttribute('visibility', v == null ? 'hidden' : 'visible'); });
    placeTip(tip, box, ev.clientX - box.getBoundingClientRect().left, ev.clientY - box.getBoundingClientRect().top,
      `<div class="t">${esc(d[i].date)}</div>全部用户：<b>${esc(fmt(d[i].all))}</b><br>认证用户：<b>${esc(fmt(d[i].verified))}</b>`);
  });
  hit.addEventListener('mouseleave', () => { tip.style.display = 'none'; cross.setAttribute('visibility', 'hidden'); dots.forEach(c => c.setAttribute('visibility', 'hidden')); });
  table('daily-table', ['日期', '全部用户', '认证用户'], d.slice().reverse().map(r => [r.date, fmt(r.all), fmt(r.verified)]), [1, 2]);
})();

// ---- 本周主帖条形图 ----
(function posts() {
  const box = document.getElementById('posts'); const P = A.week_posts; if (!P.length) { box.textContent = '本周没有主帖'; return; }
  const color = { 'AI': '--series-1', 'web3': '--series-2', '其他': '--series-3' };
  const rowH = 26, W = 1000, m = { l: 300, r: 70, t: 6, b: 24 }; const H = m.t + m.b + P.length * rowH;
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': '本周主帖曝光条形图' }, box);
  const target = (A.phase_weekly || {}).median_impressions_min || 0;
  const xmax = niceMax(Math.max(...P.map(p => p.impressions), target));
  const x = v => m.l + (W - m.l - m.r) * v / xmax;
  for (let k = 0; k <= 4; k++) { const v = xmax * k / 4; el('line', { x1: x(v), x2: x(v), y1: m.t, y2: H - m.b, stroke: css('--grid') }, svg); const t = el('text', { x: x(v), y: H - 6, 'text-anchor': 'middle' }, svg); t.textContent = fmt(v); }
  const tip = tipFor(box);
  P.forEach((p, i) => {
    const yy = m.t + i * rowH; const label = p.text.replace(/\s+/g, ' ').slice(0, 22) + (p.text.length > 22 ? '…' : '');
    const t = el('text', { x: m.l - 8, y: yy + rowH / 2 + 4, 'text-anchor': 'end' }, svg); t.textContent = `${p.date.slice(5)} ${label}`; t.style.fill = css('--text-secondary');
    const w = Math.max(x(p.impressions) - m.l, 2);
    el('path', { d: `M${m.l},${yy + 4} h${w - 4} a4,4 0 0 1 4,4 v${rowH - 16} a4,4 0 0 1 -4,4 h${-(w - 4)} z`, fill: css(color[p.category]) }, svg);
    const v = el('text', { x: m.l + w + 6, y: yy + rowH / 2 + 4 }, svg); v.textContent = fmt(p.impressions); v.style.fill = css('--text-primary');
    const hit = el('rect', { x: 0, y: yy, width: W, height: rowH, fill: 'transparent' }, svg);
    hit.style.cursor = 'pointer';
    hit.addEventListener('click', () => window.open(p.link, '_blank'));
    hit.addEventListener('mousemove', ev => placeTip(tip, box, ev.clientX - box.getBoundingClientRect().left, ev.clientY - box.getBoundingClientRect().top,
      `<div class="t">${esc(p.date)} · ${esc(p.category)}${p.english ? ' · 英文' : ''}${p.risks.length ? ' · ⚠️ 风险' : ''}</div>${esc(p.text.slice(0, 140))}<br>曝光 <b>${esc(fmt(p.impressions))}</b> · 互动 ${esc(p.engagements)} · 新关注 ${esc(p.new_follows)}<br><span class="t">点击打开原帖</span>`));
    hit.addEventListener('mouseleave', () => tip.style.display = 'none');
  });
  if (target) { el('line', { x1: x(target), x2: x(target), y1: m.t, y2: H - m.b, stroke: css('--text-secondary'), 'stroke-width': 1.5, 'stroke-dasharray': '4 4' }, svg); const t = el('text', { x: x(target) - 6, y: H - m.b - 6, 'text-anchor': 'end' }, svg); t.textContent = '中位数目标 ' + fmt(target); t.style.fill = css('--text-secondary'); }
})();

// ---- 资格进度历史 ----
(function history() {
  const H0 = A.history.filter(h => h.eligibility_verified_home_90d != null); const box = document.getElementById('history');
  table('history-table', ['报告日期', '近 90 天认证首页曝光', '认证粉丝', '本周主帖', '中位数', '目标达成'],
    A.history.slice().reverse().map(h => [h.report_date, fmt(h.eligibility_verified_home_90d), fmt(h.verified_followers), h.main_posts, fmt(h.median), `${h.targets_met}/${h.targets_total}`]), [1, 2, 3, 4]);
  if (H0.length < 2) { box.innerHTML = '<div class="desc">积累两期以上周报后显示趋势图。</div>'; return; }
  const W = 1000, Hh = 220, m = { l: 48, r: 30, t: 10, b: 26 };
  const svg = el('svg', { viewBox: `0 0 ${W} ${Hh}`, role: 'img', 'aria-label': '收益资格进度趋势' }, box);
  const ymax = niceMax(Math.max(...H0.map(h => h.eligibility_verified_home_90d)) * 1.15);
  const x = i => m.l + (W - m.l - m.r) * i / (H0.length - 1); const y = v => m.t + (Hh - m.t - m.b) * (1 - v / ymax);
  for (let k = 0; k <= 4; k++) { const v = ymax * k / 4; el('line', { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), stroke: css('--grid') }, svg); const t = el('text', { x: m.l - 8, y: y(v) + 4, 'text-anchor': 'end' }, svg); t.textContent = fmt(v); }
  el('path', { d: H0.map((h, i) => (i ? 'L' : 'M') + x(i) + ',' + y(h.eligibility_verified_home_90d)).join(''), fill: 'none', stroke: css('--series-1'), 'stroke-width': 2 }, svg);
  const tip = tipFor(box);
  H0.forEach((h, i) => {
    const t = el('text', { x: x(i), y: Hh - 6, 'text-anchor': 'middle' }, svg); t.textContent = h.report_date.slice(5);
    el('circle', { cx: x(i), cy: y(h.eligibility_verified_home_90d), r: 4, fill: css('--series-1'), stroke: css('--surface-1'), 'stroke-width': 2 }, svg);
    const hit = el('circle', { cx: x(i), cy: y(h.eligibility_verified_home_90d), r: 14, fill: 'transparent' }, svg);
    hit.addEventListener('mousemove', ev => placeTip(tip, box, ev.clientX - box.getBoundingClientRect().left, ev.clientY - box.getBoundingClientRect().top, `<div class="t">${esc(h.report_date)}</div>近 90 天认证首页曝光 <b>${esc(fmt(h.eligibility_verified_home_90d))}</b>`));
    hit.addEventListener('mouseleave', () => tip.style.display = 'none');
  });
})();
</script>
</body>
</html>
"""


def render_page(root, d, a, md_text, nav, history_list):
    body = markdown.markdown(md_text, extensions=["tables", "sane_lists"])
    # python-markdown 原样保留独占行的 HTML 注释；以标记定位，建议内部可含分隔线。
    m = re.search(re.escape(SUG_START) + r".*?" + re.escape(SUG_END) + r"\s*", body, re.S)
    if m:
        heading = re.search(r"<h2>8\. 下周调整建议</h2>\s*$", body[:m.start()])
        start = heading.start() + len("<h2>8. 下周调整建议</h2>") if heading else m.start()
        body = body[:start] + '<div class="suggest">' + body[start:m.end()] + "</div>" + body[m.end():]
    data = dict(a)
    phase_weekly = None
    cfg = load_config(root)
    for ph in cfg["phase_targets"]["phases"]:
        if ph["name"] == a["phase"]["name"]:
            phase_weekly = ph["weekly"]
    data["phase_weekly"] = phase_weekly
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    values = {
        "TITLE": html.escape(f"X 周报 {d} · @{a['handle']}"),
        "HANDLE": html.escape(a["handle"]),
        "SUBTITLE": html.escape(f"周报 {d} · 统计周期 {a['window'][0]} 至 {a['window'][1]} · {a['phase']['name']}"),
        "NAV": nav, "REPORT": body, "HISTORY_LIST": history_list, "DATA": payload,
    }
    # 单次替换，避免把帖子或建议里的 __DATA__ 等原文再次当成模板变量。
    return re.sub(r"__(TITLE|HANDLE|SUBTITLE|NAV|REPORT|HISTORY_LIST|DATA)__", lambda m: values[m[1]], TEMPLATE)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--date")
    args = ap.parse_args(argv)
    root = Path(args.root)
    reports_dir = root / "reports"
    reports = sorted(p for p in reports_dir.iterdir() if p.is_dir() and (p / "analysis.json").is_file()) if reports_dir.exists() else []
    if not reports:
        raise SystemExit("还没有任何报告，先运行 scripts/run_weekly.sh")
    target = root / "reports" / (args.date or reports[-1].name)
    for report in {target, reports[-1]}:
        for name in ("analysis.json", "report.md"):
            if not (report / name).is_file():
                raise SystemExit(f"报告文件不存在：{report / name}，请先运行 scripts/analyze.py")
    a = json.loads((target / "analysis.json").read_text(encoding="utf-8"))
    md_text = (target / "report.md").read_text(encoding="utf-8")
    if "（待助手填写" in md_text:
        print("提醒：下周调整建议尚未填写，网页里会显示占位文字")

    items = "".join(
        f'<li><a href="{{prefix}}reports/{p.name}/report.html">{p.name} 周报</a></li>' for p in reversed(reports))
    hist_block = f'<div class="card history"><h2>历史周报</h2><ul>{items}</ul></div>'

    # 单期报告页（位于 reports/<日期>/）
    page = render_page(root, target.name, a, md_text,
                       '<a href="../../index.html">← 返回工作台首页（最新一期）</a>',
                       hist_block.replace("{prefix}", "../../"))
    atomic_write_text(target / "report.html", page)

    # 首页始终展示最新一期
    latest = reports[-1]
    la = json.loads((latest / "analysis.json").read_text(encoding="utf-8"))
    index = render_page(root, latest.name, la, (latest / "report.md").read_text(encoding="utf-8"),
                        f"最新一期：{latest.name} · 共 {len(reports)} 期周报",
                        hist_block.replace("{prefix}", ""))
    atomic_write_text(root / "index.html", index)
    print(json.dumps({"report_html": str(target / "report.html"), "index": str(root / "index.html")}, ensure_ascii=False))


if __name__ == "__main__":
    ensure_utf8_stdio()
    main()
