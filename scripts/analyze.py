#!/usr/bin/env python3
"""X 账号周报分析：读取 data/raw/<日期>/ 的采集结果，生成 reports/<日期>/analysis.json 与 report.md 草稿。

统计窗口：报告日前 7 天（不含报告日当天，当天数据不完整）。
report.md 中「下周调整建议」区块由助手填写；重复运行本脚本会保留已填写的建议。
"""
import argparse
import csv
import html
import json
import re
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

# run_weekly.sh 使用 -I，需显式加入本脚本目录才能导入共用工具。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from file_utils import atomic_write_text, ensure_utf8_stdio
from config_utils import load_config

SUG_START = "<!-- SUGGESTIONS:START -->"
SUG_END = "<!-- SUGGESTIONS:END -->"
SUG_PLACEHOLDER = "（待助手填写：按 docs/周报流程.md 第 3 步撰写）"
ICON_MET = "M12 1.75C6.34"  # Creator Studio 清单中「已满足」的实心对勾图标
ICON_UNMET = "M12 3.75c"  # 「未满足」的圆圈叉号图标；其他图标（如说明行的 i 图标）不是清单项


def parse_num(s):
    if s is None:
        return None
    s = str(s).strip().replace(",", "")
    m = re.fullmatch(r"(\d+(?:\.\d*)?|\.\d+)\s*([KMkm万]?)", s)
    if not m:
        return None
    v = float(m.group(1))
    mult = {"k": 1e3, "m": 1e6, "万": 1e4}.get(m.group(2).lower(), 1)
    try:
        return int(round(v * mult))
    except (ValueError, OverflowError):
        return None


def parse_date(s):
    # 导出始终使用英文缩写，不依赖 Windows/macOS 的系统语言。
    m = re.fullmatch(r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+([A-Za-z]{3})\s+(\d{1,2}),\s+(\d{4})", s.strip(), re.I)
    months = "jan feb mar apr may jun jul aug sep oct nov dec".split()
    if not m or m[1].lower() not in months:
        raise ValueError(f"无效的导出日期：{s}")
    return date(int(m[3]), months.index(m[1].lower()) + 1, int(m[2]))


def fmt(n):
    if n is None:
        return "—"
    if abs(n) >= 10000:
        return f"{n / 10000:.1f} 万".replace(".0 万", " 万")
    return f"{n:,}"


def pct(x, digits=0):
    return "—" if x is None else f"{x * 100:.{digits}f}%"


def delta(cur, prev):
    if cur is None or prev is None or prev < 50:  # 基数太小时百分比没有意义
        return None
    return cur / prev - 1


def fmt_delta(d):
    if d is None:
        return ""
    arrow = "↑" if d >= 0 else "↓"
    return f"（{arrow}{abs(d) * 100:.0f}%）"


# ---------- 读取原始数据 ----------

def load_eligibility(raw):
    p = raw / "eligibility.json"
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    text = data.get("text", "")
    items = []
    for it in data.get("items", []):
        icon = it.get("icon", "")
        if icon.startswith(ICON_MET) or icon.startswith(ICON_UNMET):
            items.append({"text": it["text"], "met": icon.startswith(ICON_MET)})
    value = None
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for i, l in enumerate(lines):
        if re.search(r"曝光|impressions", l, re.I) and re.search(r"50\s*万|500[,.]?000|500K", l, re.I):
            for nxt in lines[i + 1:i + 6]:
                v = parse_num(nxt)
                if v is not None:
                    value = v
                    break
            break
    enrolled = not items and bool(re.search(r"收益|earnings|payout", text, re.I))
    return {"items": items, "verified_home_90d": value, "maybe_enrolled": enrolled, "raw_excerpt": text[:600]}


def load_followers(raw):
    p = raw / "overview_all_3m.txt"
    if not p.exists():
        return {}
    t = p.read_text(encoding="utf-8")
    m = re.search(r"Verified followers\n(\S+)\n[\s\S]*?/\s*\n(\S+)", t)
    if not m:
        return {}
    return {"verified_followers": parse_num(m.group(1)), "followers": parse_num(m.group(2))}


def load_daily(raw, name):
    p = raw / name
    if not p.exists():
        return {}
    out = {}
    with p.open(newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            d = parse_date(r["Date"])
            out[d] = {k: int(v) for k, v in r.items() if k != "Date" and v.strip().lstrip("-").isdigit()}
    return out


def load_posts(raw, cfg):
    p = raw / "content_90d.csv"
    posts = []
    if not p.exists():
        return posts
    cats = {k: re.compile(v, re.I) for k, v in cfg["categories"].items() if not k.startswith("_")}
    risks = {k: re.compile(v, re.I) for k, v in cfg["risk_rules"].items()}
    metrics = [("impressions", "Impressions"), ("likes", "Likes"), ("engagements", "Engagements"),
               ("bookmarks", "Bookmarks"), ("shares", "Shares"), ("new_follows", "New follows"),
               ("replies", "Replies"), ("reposts", "Reposts"), ("profile_visits", "Profile visits"),
               ("url_clicks", "URL Clicks")]
    with p.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        required = {"Post id", "Date", "Post text", "Post Link"} | {col for _, col in metrics}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError("帖子 CSV 缺少必要列：" + "、".join(sorted(missing)))
        for r in reader:
            text = r["Post text"].strip()
            is_reply = text.startswith("@")
            hits = {k: len(rx.findall(text)) for k, rx in cats.items()}
            best = max(hits, key=hits.get) if any(hits.values()) else "其他"
            letters = re.findall(r"[A-Za-z]|[一-鿿]", re.sub(r"https?://\S+|@\w+|\$\w+|0x\w+", "", text))
            latin = sum(1 for c in letters if c.isascii())
            english = bool(letters) and latin / len(letters) >= cfg["english_ratio_min"]
            body = re.sub(r"https?://\S+", "", text)
            posts.append({
                "id": r["Post id"],
                "date": parse_date(r["Date"]).isoformat(),
                "text": text,
                "link": r["Post Link"],
                "reply": is_reply,
                "category": best,
                "english": english,
                "has_link": bool(re.search(r"https?://|\b[\w-]+\.(com|io|xyz|ai|app|fun|cn|me|org|net|co)\b/?", text)),
                "one_liner": len(body.strip()) <= cfg["one_liner_max_chars"],
                # 喊单式表述只在 web3 帖里算风险，避免把「Pro 20x」这类 AI 套餐名误判
                "risks": [k for k, rx in risks.items() if rx.search(body) and (k != "hype_call" or best == "web3")],
                **{k: int(r[col] or 0) for k, col in metrics},
            })
    return posts


# ---------- 统计 ----------

def window(d_end, days):
    return d_end - timedelta(days=days), d_end - timedelta(days=1)


def in_win(dstr, win):
    d = date.fromisoformat(dstr)
    return win[0] <= d <= win[1]


def post_stats(posts):
    main = [p for p in posts if not p["reply"]]
    replies = [p for p in posts if p["reply"]]
    imps = sorted((p["impressions"] for p in main), reverse=True)
    n = len(main)
    total = sum(imps)
    eng = sum(p["engagements"] for p in main)
    by_cat = {}
    for c in ["AI", "web3", "其他"]:
        xs = [p["impressions"] for p in main if p["category"] == c]
        by_cat[c] = {"posts": len(xs), "impressions": sum(xs),
                     "median": int(statistics.median(xs)) if xs else None}
    buckets = {"<500": 0, "500–1K": 0, "1K–3K": 0, "3K–10K": 0, "10K–50K": 0, "≥50K": 0}
    for v in imps:
        k = ("<500" if v < 500 else "500–1K" if v < 1000 else "1K–3K" if v < 3000 else
             "3K–10K" if v < 10000 else "10K–50K" if v < 50000 else "≥50K")
        buckets[k] += 1
    return {
        "main_posts": n,
        "replies": len(replies),
        "main_impressions": total,
        "reply_impressions": sum(p["impressions"] for p in replies),
        "median": int(statistics.median(imps)) if imps else None,
        "p75": int(statistics.quantiles(imps, n=4)[2]) if n >= 4 else (imps[0] if imps else None),
        "max": imps[0] if imps else None,
        "posts_over_10k": sum(1 for v in imps if v >= 10000),
        "engagement_rate": eng / total if total else None,
        "new_follows_from_posts": sum(p["new_follows"] for p in main),
        "profile_visits_from_posts": sum(p["profile_visits"] for p in main),
        "english_posts": sum(1 for p in main if p["english"]),
        "link_posts": sum(1 for p in main if p["has_link"]),
        "one_liners": sum(1 for p in main if p["one_liner"]),
        "risk_posts": sum(1 for p in main if p["risks"]),
        "ai_share": by_cat["AI"]["posts"] / n if n else None,
        "by_category": by_cat,
        "buckets": buckets,
    }


def sum_daily(daily, win, key="Impressions"):
    vals = [v.get(key, 0) for d, v in daily.items() if win[0] <= d <= win[1]]
    return sum(vals) if vals else None


def pick_phase(cfg, d):
    phases = cfg["phase_targets"]["phases"]
    for ph in phases:
        if d <= date.fromisoformat(ph["until"]):
            return ph
    return phases[-1]


def evaluate_targets(phase, wk, week_main, verified_week):
    t = phase["weekly"]
    checks = [
        ("主帖数量", f"{t['main_posts_min']}–{t['main_posts_max']} 条", wk["main_posts"],
         t["main_posts_min"] <= wk["main_posts"] <= t["main_posts_max"]),
        ("单条曝光中位数", f"≥ {fmt(t['median_impressions_min'])}", wk["median"],
         (wk["median"] or 0) >= t["median_impressions_min"]),
        (f"爆款帖（≥ {fmt(t['breakout_threshold'])}）", f"≥ {t['breakout_min']} 条",
         sum(1 for p in week_main if p["impressions"] >= t["breakout_threshold"]),
         sum(1 for p in week_main if p["impressions"] >= t["breakout_threshold"]) >= t["breakout_min"]),
        ("英文帖", f"≥ {t['english_posts_min']} 条", wk["english_posts"],
         wk["english_posts"] >= t["english_posts_min"]),
        ("AI 主线占比", f"≥ {pct(t['ai_share_min'])}", wk["ai_share"],
         (wk["ai_share"] or 0) >= t["ai_share_min"]),
        ("风险帖", f"≤ {t['risk_posts_max']} 条", wk["risk_posts"],
         wk["risk_posts"] <= t["risk_posts_max"]),
        ("认证用户曝光（周，含回复）", f"≥ {fmt(t['verified_impressions_week_min'])}", verified_week,
         (verified_week or 0) >= t["verified_impressions_week_min"]),
    ]
    out = []
    for name, target, actual, ok in checks:
        shown = pct(actual) if name == "AI 主线占比" else fmt(actual)
        out.append({"name": name, "target": target, "actual": shown, "ok": bool(ok)})
    return out


def previous_suggestions(root, d):
    reports_dir = root / "reports"
    if not reports_dir.exists():
        return None
    reports = sorted(p for p in reports_dir.iterdir() if p.is_dir() and p.name < d.isoformat())
    for rp in reversed(reports):
        md = rp / "report.md"
        if md.exists():
            t = md.read_text(encoding="utf-8")
            m = re.search(re.escape(SUG_START) + r"(.*?)" + re.escape(SUG_END), t, re.S)
            if m and SUG_PLACEHOLDER not in m.group(1):
                return {"date": rp.name, "text": m.group(1).strip()}
    return None


def short(text, n=60):
    t = re.sub(r"\s+", " ", text).strip()
    return t if len(t) <= n else t[:n] + "…"


def escape_markdown(text):
    # 先处理 HTML，再转义链接文字、表格及行内格式中的特殊符号。
    return re.sub(r"([\\`*_\[\]()|])", r"\\\1", html.escape(text, quote=False))


# ---------- 报告 ----------

def build_report(a):
    e, wk, pw = a["eligibility"], a["week"], a["prev_week"]
    L = []
    L.append(f"# X 账号周报 · @{a['handle']} · {a['report_date']}")
    L.append("")
    L.append(f"统计周期：{a['window'][0]} 至 {a['window'][1]}（对比上周 {a['prev_window'][0]} 至 {a['prev_window'][1]}）  ")
    L.append(f"当前阶段：{a['phase']['name']}（截至 {a['phase']['until']}）")
    L.append("")
    L.append("## 1. 创作者收益资格进度")
    L.append("")
    if e and e.get("verified_home_90d") is not None:
        v = e["verified_home_90d"]
        L.append(f"- **近 90 天认证用户首页曝光：{fmt(v)} / 50 万（{pct(v / a['target_90d'], 1)}）**"
                 + (f"，较上次 {fmt_delta(a['eligibility_delta'])}" if a.get("eligibility_delta") is not None else ""))
    elif e and e.get("maybe_enrolled"):
        L.append("- 资格页未显示清单，可能已入选计划，请人工核对 Creator Studio。")
    else:
        L.append("- 未能读取资格页数据，请人工核对 Creator Studio。")
    for it in (e or {}).get("items", []):
        L.append(f"- {'✅' if it['met'] else '❌'} {escape_markdown(it['text'])}")
    f = a["followers"]
    if f:
        L.append(f"- 认证粉丝 {fmt(f.get('verified_followers'))} / 总粉丝 {fmt(f.get('followers'))}")
    if a.get("steady_state_90d") is not None:
        L.append(f"- 按本周速度推算，90 天稳态约 **{fmt(a['steady_state_90d'])}**"
                 f"（本周合格曝光估算 {fmt(a['qualified_week_est'])}，需要每周约 {fmt(a['target_90d'] * 7 // 90)}）")
    L.append("")
    L.append("## 2. 本周核心数据")
    L.append("")
    L.append("| 指标 | 本周 | 上周 |")
    L.append("|---|---|---|")
    rows = [
        ("账号总曝光（含回复）", a["impr_all_week"], a["impr_all_prev"]),
        ("认证用户曝光（含回复）", a["impr_verified_week"], a["impr_verified_prev"]),
        ("主帖数 / 回复数", f"{wk['main_posts']} / {wk['replies']}", f"{pw['main_posts']} / {pw['replies']}"),
        ("主帖曝光合计", wk["main_impressions"], pw["main_impressions"]),
        ("回复曝光合计（不计入门槛）", wk["reply_impressions"], pw["reply_impressions"]),
        ("单条曝光中位数", wk["median"], pw["median"]),
        ("单条最高曝光", wk["max"], pw["max"]),
        ("过万帖子数", wk["posts_over_10k"], pw["posts_over_10k"]),
        ("主帖互动率", pct(wk["engagement_rate"], 1), pct(pw["engagement_rate"], 1)),
        ("新增关注 / 取关", f"{a['follows_week']} / {a['unfollows_week']}", f"{a['follows_prev']} / {a['unfollows_prev']}"),
    ]
    for name, cur, prev in rows:
        c = cur if isinstance(cur, str) else fmt(cur) + fmt_delta(delta(cur, prev))
        p = prev if isinstance(prev, str) else fmt(prev)
        L.append(f"| {name} | {c} | {p} |")
    L.append("")
    L.append("## 3. 内容结构")
    L.append("")
    L.append("| 类别 | 主帖数 | 曝光合计 | 中位数 |")
    L.append("|---|---|---|---|")
    for c, s in wk["by_category"].items():
        L.append(f"| {c} | {s['posts']} | {fmt(s['impressions'])} | {fmt(s['median'])} |")
    L.append("")
    L.append(f"英文帖 {wk['english_posts']} 条；带外链 {wk['link_posts']} 条；一句话帖 {wk['one_liners']} 条。  ")
    L.append("曝光分布：" + "，".join(f"{k} {v} 条" for k, v in wk["buckets"].items()))
    L.append("")
    L.append("## 4. 阶段目标检查")
    L.append("")
    L.append("| 项目 | 目标 | 本周 | 结果 |")
    L.append("|---|---|---|---|")
    for t in a["targets"]:
        L.append(f"| {t['name']} | {t['target']} | {t['actual']} | {'✅ 达标' if t['ok'] else '❌ 未达标'} |")
    L.append("")
    L.append("## 5. 本周最佳与最弱主帖")
    L.append("")
    L.append("**曝光最高**")
    L.append("")
    for p in a["top_posts"]:
        L.append(f"- {fmt(p['impressions'])} · {p['category']} · {p['date']} · [{escape_markdown(short(p['text']))}]({p['link']})")
    L.append("")
    L.append("**曝光最低**")
    L.append("")
    for p in a["bottom_posts"]:
        L.append(f"- {fmt(p['impressions'])} · {p['category']} · {p['date']} · [{escape_markdown(short(p['text']))}]({p['link']})")
    L.append("")
    L.append("## 6. 风险提示")
    L.append("")
    if a["risk_posts"]:
        names = {"contract_address": "合约地址", "gray_market": "代充/招代理/导流", "solicitation": "求互动",
                 "hype_call": "喊单式表述"}
        for p in a["risk_posts"]:
            L.append(f"- {'、'.join(names.get(r, r) for r in p['risks'])} · {p['date']} · [{escape_markdown(short(p['text']))}]({p['link']})")
        L.append("")
        L.append("以上为关键词规则命中，可能有误判，请人工判断是否删除或调整写法。")
    else:
        L.append("- 本周主帖未命中风险规则。")
    L.append("")
    L.append("## 7. 上周建议回顾")
    L.append("")
    if a["prev_suggestions"]:
        L.append(f"上次报告（{a['prev_suggestions']['date']}）的建议见该期报告；助手已在下方建议中评估执行情况。")
    else:
        L.append("这是第一期报告，暂无上周建议。")
    L.append("")
    L.append("## 8. 下周调整建议")
    L.append("")
    L.append(SUG_START)
    L.append(SUG_PLACEHOLDER)
    L.append(SUG_END)
    L.append("")
    L.append("---")
    L.append(f"数据来源：X Creator Studio 与 Analytics 导出（采集于 {a['collected_at']}）。分类与风险标记为关键词规则，仅供参考。")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--date", default=date.today().isoformat())
    args = ap.parse_args(argv)
    root = Path(args.root)
    d = date.fromisoformat(args.date)
    raw = root / "data" / "raw" / d.isoformat()
    cfg = load_config(root)

    meta = json.loads((raw / "meta.json").read_text(encoding="utf-8")) if (raw / "meta.json").exists() else {}
    if meta.get("ok") is False:
        raise SystemExit(f"采集失败：{meta.get('reason')}（{raw}/meta.json）")

    win, pwin = window(d, 7), (d - timedelta(days=14), d - timedelta(days=8))
    if not (raw / "content_90d.csv").is_file():
        raise SystemExit(f"缺少帖子数据：{raw}/content_90d.csv")
    try:
        posts = load_posts(raw, cfg)
    except ValueError as error:
        raise SystemExit(f"帖子数据无效：{error}") from None
    daily_all = load_daily(raw, "overview_all.csv")
    # 本次未导出认证数据时，不复用同目录上一次采集留下的 CSV；兼容旧版无 files 的元数据。
    daily_ver = load_daily(raw, "overview_verified.csv") if "files" not in meta or "overview_verified.csv" in meta["files"] else {}
    elig = load_eligibility(raw)
    followers = load_followers(raw)

    wk_posts = [p for p in posts if in_win(p["date"], win)]
    pw_posts = [p for p in posts if in_win(p["date"], pwin)]
    wk, pw = post_stats(wk_posts), post_stats(pw_posts)
    main_wk = sorted((p for p in wk_posts if not p["reply"]), key=lambda p: -p["impressions"])

    impr_ver_week = sum_daily(daily_ver, win)
    ver_90 = sum_daily(daily_ver, window(d, 90))
    elig_val = (elig or {}).get("verified_home_90d")
    ratio = (elig_val / ver_90) if (elig_val is not None and ver_90) else None
    qualified_week = int(impr_ver_week * ratio) if (impr_ver_week is not None and ratio is not None) else None

    hist_path = root / "data" / "history.json"
    history = json.loads(hist_path.read_text(encoding="utf-8")) if hist_path.exists() else []
    prev_hist = [h for h in history if h["report_date"] < d.isoformat()]
    prev_elig = prev_hist[-1].get("eligibility_verified_home_90d") if prev_hist else None

    phase = pick_phase(cfg, d)
    a = {
        "handle": cfg["handle"],
        "report_date": d.isoformat(),
        "collected_at": meta.get("finished_at", "未知"),
        "window": [x.isoformat() for x in win],
        "prev_window": [x.isoformat() for x in pwin],
        "target_90d": cfg["program"]["verified_home_impressions_90d_target"],
        "phase": {"name": phase["name"], "until": phase["until"]},
        "eligibility": elig,
        "eligibility_delta": delta(elig_val, prev_elig),
        "followers": followers,
        "impr_all_week": sum_daily(daily_all, win),
        "impr_all_prev": sum_daily(daily_all, pwin),
        "impr_verified_week": impr_ver_week,
        "impr_verified_prev": sum_daily(daily_ver, pwin),
        "follows_week": sum_daily(daily_all, win, "New follows"),
        "unfollows_week": sum_daily(daily_all, win, "Unfollows"),
        "follows_prev": sum_daily(daily_all, pwin, "New follows"),
        "unfollows_prev": sum_daily(daily_all, pwin, "Unfollows"),
        "qualified_ratio": ratio,
        "qualified_week_est": qualified_week,
        "steady_state_90d": int(qualified_week * 90 / 7) if qualified_week is not None else None,
        "week": wk,
        "prev_week": pw,
        "targets": evaluate_targets(phase, wk, main_wk, impr_ver_week),
        "top_posts": main_wk[:5],
        "bottom_posts": main_wk[-5:][::-1] if len(main_wk) > 5 else [],
        "risk_posts": [p for p in main_wk if p["risks"]],
        "week_posts": main_wk,
        "prev_suggestions": previous_suggestions(root, d),
        "daily": [
            {"date": dd.isoformat(), "all": daily_all[dd].get("Impressions", 0),
             "verified": daily_ver.get(dd, {}).get("Impressions")}
            for dd in sorted(daily_all) if dd < d
        ],
    }

    entry = {
        "report_date": d.isoformat(),
        "eligibility_verified_home_90d": elig_val,
        "verified_followers": followers.get("verified_followers"),
        "followers": followers.get("followers"),
        "impr_all_week": a["impr_all_week"],
        "impr_verified_week": impr_ver_week,
        "qualified_week_est": qualified_week,
        "main_posts": wk["main_posts"],
        "median": wk["median"],
        "posts_over_10k": wk["posts_over_10k"],
        "ai_share": wk["ai_share"],
        "risk_posts": wk["risk_posts"],
        "targets_met": sum(t["ok"] for t in a["targets"]),
        "targets_total": len(a["targets"]),
    }
    history = [h for h in history if h["report_date"] != entry["report_date"]] + [entry]
    history.sort(key=lambda h: h["report_date"])
    atomic_write_text(hist_path, json.dumps(history, ensure_ascii=False, indent=2))
    a["history"] = history

    out = root / "reports" / d.isoformat()
    out.mkdir(parents=True, exist_ok=True)
    atomic_write_text(out / "analysis.json", json.dumps(a, ensure_ascii=False, indent=2))

    md_path = out / "report.md"
    new_md = build_report(a)
    if md_path.exists():
        m = re.search(re.escape(SUG_START) + r".*?" + re.escape(SUG_END), md_path.read_text(encoding="utf-8"), re.S)
        if m and SUG_PLACEHOLDER not in m.group(0):
            new_md = re.sub(re.escape(SUG_START) + r".*?" + re.escape(SUG_END), lambda _: m.group(0), new_md, flags=re.S)
    atomic_write_text(md_path, new_md)
    print(json.dumps({"report": str(md_path), "analysis": str(out / "analysis.json"),
                      "eligibility": elig_val, "main_posts": wk["main_posts"], "median": wk["median"],
                      "targets_met": f"{entry['targets_met']}/{entry['targets_total']}"}, ensure_ascii=False))


if __name__ == "__main__":
    ensure_utf8_stdio()
    main()
