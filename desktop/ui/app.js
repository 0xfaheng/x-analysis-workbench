'use strict';
const $ = id => document.getElementById(id);
let reports = [], selection = null, loaded = '', offset = 0, generation = -1, running = false, canAssist = false;
let refreshBusy = false, pollBusy = false;
const api = () => window.pywebview.api;
const fmt = n => n == null ? '—' : (Math.abs(n) >= 10000 ? (n / 10000).toFixed(1).replace(/\.0$/, '') + ' 万' : n.toLocaleString('zh-CN'));
function failure(error) { $('status').textContent = '操作失败：' + (error.message || error); $('status').classList.add('error'); }
function controls() {
  document.querySelectorAll('[data-job]').forEach(b => {
    b.disabled = running || (b.dataset.job === 'assistant' && !canAssist) || (b.dataset.job === 'render' && !selection);
  });
  document.querySelectorAll('[data-path]').forEach(b => { b.disabled = running || (b.dataset.path === 'report' && !selection); });
}
function choose(id) { selection = id; paint(); }
function paint() {
  $('reports').replaceChildren();
  for (const r of reports) {
    const row = document.createElement('button'); row.className = 'report-row';
    row.setAttribute('aria-current', String(r.id === selection));
    const title = document.createElement('div'); title.className = 'row-title'; title.textContent = r.id;
    if (r.pending) { const mark = document.createElement('span'); mark.className = 'pending'; mark.textContent = '待写建议'; title.append(mark); }
    row.append(title);
    if (r.progress != null) { const bar = document.createElement('progress'); bar.max = 1; bar.value = r.progress; bar.setAttribute('aria-label', '门槛进度'); row.append(bar); }
    const text = document.createElement('div'); text.className = 'metrics';
    text.textContent = `门槛 ${fmt(r.eligibility)} / 50 万 · 目标 ${r.targets_met ?? '—'}/${r.targets_total ?? '—'}`;
    row.append(text); row.addEventListener('click', () => choose(r.id)); $('reports').append(row);
  }
  $('count').textContent = `共 ${reports.length} 期 · 每 20 秒刷新`;
  const selected = reports.find(r => r.id === selection);
  const key = selected?.modified == null ? '' : selected.id + ':' + selected.modified;
  $('report').hidden = !key; $('empty').hidden = !!key;
  if (key && key !== loaded) $('report').src = '../' + selected.url + '?v=' + selected.modified;
  if (!key && loaded) $('report').src = 'about:blank';
  loaded = key;
  if (reports.length && !key) {
    $('empty').querySelector('h1').textContent = '这一期还没有生成报告页面';
    $('guide').textContent = '点击「重新生成网页」使用本期已有数据生成页面。';
  }
  controls();
}
async function refresh(latest = false) {
  if (refreshBusy) return;
  refreshBusy = true;
  try {
    const data = await api().list_reports(); reports = data.reports; canAssist = data.assistant;
    $('account').textContent = `@${data.handle} · v${data.version}`;
    $('assistant-help').title = canAssist ? '让 mirasim 运行已配置的每周任务' : data.assistant_hint;
    if (latest || !reports.some(r => r.id === selection)) selection = reports[0]?.id ?? null;
    if (!reports.length) {
      $('empty').querySelector('h1').textContent = '还没有周报';
      $('guide').textContent = `第一步：点「登录 X」在弹出的 Edge 窗口登录 @${data.handle}；\n第二步：点「仅更新数据」。`;
    }
    paint();
  } catch (error) { failure(error); } finally { refreshBusy = false; }
}
async function poll() {
  if (pollBusy) return;
  pollBusy = true;
  try {
    let state = await api().job_status(offset);
    if (state.generation !== generation) { generation = state.generation; offset = 0; $('log').textContent = ''; state = await api().job_status(0); }
    const wasRunning = running; running = state.running;
    offset = state.offset;
    if (state.log) { $('log').textContent += state.log; $('log').scrollTop = $('log').scrollHeight; }
    $('status').textContent = state.status; $('status').classList.toggle('error', state.code != null && state.code !== 0);
    if (state.code != null && state.code !== 0) showLog(true);
    controls();
    if (wasRunning && !running) await refresh(state.code === 0 && state.kind !== 'render');
  } catch (error) { failure(error); } finally { pollBusy = false; }
}
function showLog(show) { $('logs').hidden = !show; $('toggle-log').setAttribute('aria-expanded', String(show)); }
// 报告脚本调用这里，URL 的协议在 Python 侧再次验证。
window.XWBReport = url => api().open_url(url).catch(failure);
window.addEventListener('pywebviewready', async () => {
  document.querySelectorAll('[data-job]').forEach(button => button.addEventListener('click', async () => {
    const kind = button.dataset.job;
    if (kind === 'assistant' && !window.confirm('让 mirasim 采集数据、写建议并生成完整周报？通常需要 5–15 分钟。')) return;
    try {
      running = true; controls();
      const result = await api().start_job(kind, selection);
      if (!result.ok) failure(result.message);
      await poll();
    } catch (error) { running = false; controls(); failure(error); }
  }));
  document.querySelectorAll('[data-path]').forEach(button => button.addEventListener('click', () => {
    $('more').open = false; api().open_path(button.dataset.path, selection).catch(failure);
  }));
  $('toggle-log').addEventListener('click', () => showLog($('logs').hidden));
  await refresh(); await poll();
  setInterval(() => refresh(), 20000); setInterval(poll, 500);
});
