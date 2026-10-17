'use strict';
// 在报告脚本运行前安装；不写回 report.html。
(() => {
  const external = value => {
    try { const u = new URL(value, location.href); return /^https?:$/.test(u.protocol) && u.origin !== location.origin ? u.href : null; }
    catch { return null; }
  };
  const open = url => { if (parent !== window && parent.XWBReport) parent.XWBReport(url); };
  window.open = value => { const url = external(value); if (url) open(url); return null; };
  const linkClick = event => {
    const a = event.target.closest?.('a[href]');
    if (!a) return;
    const url = external(a.href);
    if (url) { event.preventDefault(); event.stopImmediatePropagation(); open(url); }
    else if (!a.href.startsWith(location.origin + '/')) event.preventDefault();
  };
  document.addEventListener('click', linkClick, true);
  document.addEventListener('auxclick', linkClick, true);
  document.addEventListener('DOMContentLoaded', () => {
    const style = document.createElement('style');
    style.textContent = '.nav, .history { display: none !important; } .wrap { padding-top: 18px !important; }';
    document.head.append(style);
  });
})();
