"""离线、确定性的周报建议；官方规则、数据观察与运营实验分别标注。"""
import hashlib
import html
import json
import math
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

AUTO_START = "<!-- AUTO-SUGGESTIONS:START sha256="
AUTO_END = "<!-- AUTO-SUGGESTIONS:END -->"


def load_policy():
    resources = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    policy = json.loads((resources / "rules/x-official-rules.json").read_text(encoding="utf-8"))
    if policy.get("schema_version") != 1 or not policy.get("rules"):
        raise ValueError("官方规则快照格式不正确")
    date.fromisoformat(policy["verified_at"])
    for source in policy["sources"].values():
        parts = urlsplit(source["url"])
        if parts.scheme != "https" or parts.netloc != "help.x.com":
            raise ValueError("官方规则来源必须是 X Help Center 的 HTTPS 地址")
    for rule in policy["rules"]:
        if rule["source"] not in policy["sources"]:
            raise ValueError("官方规则缺少来源")
    for value in policy["thresholds"].values():
        if type(value) is not int or value <= 0:
            raise ValueError("官方门槛必须是正整数")
    return policy


def escape(text):
    return re.sub(r"([\\`*_\[\]()|])", r"\\\1", html.escape(str(text), quote=False))


def number(value):
    return "未读取" if value is None else f"{value:,}"


def metric(a, key):
    value = a
    for part in key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def evaluate_check(a, check):
    if not check:
        return {"status": "需人工核对", "actual": None}
    value = metric(a, check["metric"])
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return {"status": "数据不足", "actual": None}
    ok = ("min" not in check or value >= check["min"]) and ("max" not in check or value <= check["max"])
    return {"status": "指标达标" if ok else "指标未达标", "actual": value}


def wrap_automatic(body):
    body = body.strip()
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return f"{AUTO_START}{digest} -->\n{body}\n{AUTO_END}"


def is_untouched_automatic(block):
    match = re.fullmatch(re.escape(AUTO_START) + r"([0-9a-f]{64}) -->\n(.*?)\n" + re.escape(AUTO_END), block.strip(), re.S)
    return bool(match and hashlib.sha256(match[2].encode("utf-8")).hexdigest() == match[1])


def previous_actions(root, report_date):
    folders = sorted((Path(root) / "reports").glob("????-??-??"), reverse=True)
    for folder in folders:
        if folder.name >= report_date:
            continue
        try:
            a = json.loads((folder / "analysis.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        recommendation = a.get("recommendations", {})
        if recommendation.get("origin") == "program":
            return {"date": folder.name, "actions": recommendation.get("actions", [])}
        # 最近一期是人工建议时，不跳过它去声称更早的计划就是上周计划。
        return None
    return None


def source_links(policy, ids):
    return "、".join(f"[{policy['sources'][key]['title']}]({policy['sources'][key]['url']})" for key in dict.fromkeys(ids))


def policy_markdown(policy):
    lines = [f"规则快照核验于 **{policy['verified_at']}**。这是已核验的摘要，未在每次运行时联网确认；申请前以官方页面及本人 Creator Studio 为准。", "",
             "| 规则 | 要点 | 官方来源 |", "|---|---|---|"]
    for rule in policy["rules"]:
        lines.append(f"| {escape(rule['title'])} | {escape(rule['summary'])} | {source_links(policy, [rule['source']])} |")
    return "\n".join(lines)


def generate(a, cfg, policy, previous=None, as_of=None):
    as_of = as_of or max(date.today(), date.fromisoformat(a["report_date"]))
    age = (as_of - date.fromisoformat(policy["verified_at"])).days
    stale = age > policy["review_after_days"] or age < 0
    minimum = cfg.get("recommendations", {}).get("min_sample_posts", 5)
    if type(minimum) is not int or minimum < 2:
        raise ValueError("recommendations.min_sample_posts 必须是至少为2的整数")
    wk, pw = a["week"], a["prev_week"]
    t = a["phase_weekly"]
    actions = []

    def add(ident, title, evidence, action, review, check=None, sources=(), kind="运营实验", confidence="描述性观察"):
        actions.append({"id": ident, "title": title, "kind": kind, "confidence": confidence,
                        "evidence": evidence, "action": action, "review": review, "check": check,
                        "source_ids": list(sources)})

    if stale:
        add("review_policy", "先复核官方规则", f"快照核验日 {policy['verified_at']}，当前参考日 {as_of.isoformat()}，超过有效复核范围。",
            "打开下方官方链接核对条款，再由维护者更新规则快照；本次只按旧快照提供参考，不确认当前官方门槛。",
            "核对规则核验日期及条款变化记录。", sources=tuple(policy["sources"]), kind="规则待复核", confidence="规则可能变化")

    thresholds = policy["thresholds"]
    value = (a.get("eligibility") or {}).get("verified_home_90d")
    target = thresholds["verified_home_impressions_90d"]
    followers = a.get("followers", {}).get("verified_followers")
    missing_conditions = ["开放地区及本人身份", "账号状态与类型", "账号活跃时长、资料、邮箱和双重验证", "身份与收款验证"]
    if value is None:
        summary = "资格页合格曝光尚未读取，暂不能判断距离奖励门槛有多远。"
    elif value < target:
        summary = f"资格页近90天认证首页曝光 {number(value)}，距快照门槛 {number(target)} 还差 {number(target - value)}；优先改善原创主帖表现。"
    else:
        summary = f"资格页近90天认证首页曝光 {number(value)}，达到快照中的曝光门槛；仍须核对其他资格并由X审核。"
    if stale:
        summary = "规则快照需要复核。" + summary
    if value is None or value < target:
        add("qualified_exposure", "用资格页追踪合格曝光", f"资格页曝光：{number(value)}；Analytics认证用户周曝光（含回复）：{number(a.get('impr_verified_week'))}，两者不是同一口径。",
            "下周保留资格页读数，比较滚动90天变化；持续发布本人原创、有实质观点的主帖。不要把回复、总曝光或程序估算视为合格曝光。",
            f"复查资格页读数；{math.ceil(target * 7 / thresholds['window_days']):,}/周仅是90天门槛的算术均摊，不是平台周考核或达标时间承诺。",
            sources=("original_rewards",), kind="官方规则应用", confidence="以资格页实测为准")
    if followers is None or followers < thresholds["verified_followers"]:
        add("verified_followers", "核对认证粉丝条件", f"认证粉丝 {number(followers)}；规则快照要求至少 {thresholds['verified_followers']}。",
            "围绕本人专业内容吸引真实读者，下一期检查认证粉丝；不买粉、不互刷。未读取时先补数据，不按0处理。",
            f"复查认证粉丝是否达到 {thresholds['verified_followers']}，其余资格仍须单独核对。",
            {"metric": "followers.verified_followers", "min": thresholds["verified_followers"]}, ("original_rewards", "authenticity"), "官方规则应用")

    coverage = a.get("data_quality", {})
    missing_days = coverage.get("missing_overview_days", [])
    if missing_days or coverage.get("missing_verified_days") or not coverage.get("verified_overview_available", False):
        details = f"账号总览缺 {len(missing_days)} 个统计日；认证用户总览缺 {len(coverage.get('missing_verified_days', []))} 天，{'已读取' if coverage.get('verified_overview_available') else '未读取'}。"
        add("complete_data", "先补齐统计口径", details,
            "补导出缺失日期或认证用户CSV后再比较周变化；没有数据不等于0，受众文本也不用于推断本人所在地。",
            "下一期检查总览覆盖7天，认证数据可用；仍缺数据则保留缺项说明。", kind="数据质量", confidence="数据不足")

    low, high = t["main_posts_min"], t["main_posts_max"]
    count = wk["main_posts"]
    if count < low or count > high:
        action = (f"按当前自设目标安排 {low}–{high} 条主帖，优先完成原创案例和复盘，不用重复内容补数量。" if count < low else
                  f"把下周主帖控制在自设的 {low}–{high} 条，合并重复信息，将时间用于补充原创证据；这只是待验证的运营实验。")
        add("posting_plan", "调整主帖安排", f"本周 {count} 条，上周 {pw['main_posts']} 条；本机阶段目标 {low}–{high} 条，属于用户设置。",
            action, f"检查主帖数是否在 {low}–{high} 条，并同时比较中位曝光，不能只以数量判断效果。",
            {"metric": "week.main_posts", "min": low, "max": high})

    if count:
        median = wk["median"]
        goal = t["median_impressions_min"]
        add("content_quality", "围绕单帖表现做一次对照复盘", f"本周主帖中位曝光 {number(median)}，上周 {number(pw['median'])}；自设参考目标 {number(goal)}。",
            "选表现较好的本人主帖，补充原始案例、过程和可核对结果；另做同主题的不同表达，再记录表现。不能由本周结果断言某种写法导致增长。",
            f"下一期比较中位曝光与 {number(goal)} 的自设参考目标；未达标时记录差异，不承诺增长。",
            {"metric": "week.median", "min": goal}, confidence="小样本，仅作记录" if count < minimum else "相关性观察")

    categories = [(name, stats) for name, stats in wk["by_category"].items() if stats["posts"] >= minimum]
    if categories:
        name, stats = max(categories, key=lambda item: item[1]["median"] or 0)
        add("topic_test", "小规模验证较强内容方向", f"“{name}”本周 {stats['posts']} 条、中位曝光 {number(stats['median'])}，在满足样本门槛的类别中较高。",
            f"围绕“{name}”挑选1–2个自己有一手材料的题目，补充真实证据。分类由关键词决定，先检查分组是否准确，不直接照搬最佳帖或认定题材必然有效。",
            "下周按类别对比数量、中位曝光与新增关注；CSV没有控制发布时间等变量，不能解释因果。", confidence="相关性观察")
    else:
        add("sample_size", "先积累可比较样本", f"本周主帖 {count} 条，各类别均未达到 {minimum} 条的观察样本门槛。",
            "保持自己的内容定位，用少量同主题原创内容记录差异；不要因为一条高曝光帖就全面换方向，也不为凑样本刷屏。",
            "下周检查样本量、分类准确度及中位曝光；样本门槛是程序设置，不是X规定。", confidence="样本不足")

    if wk["risk_posts"]:
        add("review_flags", "逐条复核关键词提示", f"本周 {wk['risk_posts']} 条主帖命中本机风险关键词，命中不代表X认定违规。",
            "阅读下方帖子上下文；重点检查反复求互动、误导及非原创贡献。合约地址、某个词或外链本身不能据此判定违规，不自动删除或修改帖子。",
            "由本人记录每条的复核结论；下周关键词命中数仅作提示，不能证明合规。",
            sources=("original_rewards", "authenticity", "monetization"), kind="需人工复核", confidence="关键词线索")

    for key, actual, title, unit in (("english_posts_min", wk["english_posts"], "英文内容", "条"),):
        if actual < t[key]:
            add("language_test", "按自己的受众验证语言安排", f"本周英文主帖 {actual} 条，本机目标 {t[key]} 条；X没有要求必须发英文帖。",
                "如果英文仍符合你的受众目标，用本人已有材料做小规模语言实验；若不适合，在本机配置调整该目标。",
                f"下一期记录英文主帖数量及表现（自设参考 {t[key]} {unit}），不假定英文必然获得更多收益。",
                {"metric": "week.english_posts", "min": t[key]})

    reviews = []
    if previous:
        for action in previous["actions"]:
            reviews.append({"id": action["id"], "title": action["title"], **evaluate_check(a, action.get("check"))})
    ideas = []
    for post in [p for p in a["week_posts"] if not p["risks"]][:3]:
        ideas.append({"date": post["date"], "impressions": post["impressions"], "link": post["link"],
                      "text": re.sub(r"\s+", " ", post["text"]).strip()[:65],
                      "task": "先确认这篇是否包含本人原创贡献；若有一手材料，可补充过程、局限或新结果；缺少的案例和数字由本人填写。"})
    lines = ["**程序结论：** " + escape(summary), "",
             "这些建议由本机程序按统计与规则生成，不调用AI。官方要求与运营实验分开标注；不预测推荐算法、收益或达标日期。", ""]
    if previous:
        lines += [f"### 上期计划指标复查（{previous['date']}）", "", "指标达标不等于已执行建议，也不能证明建议造成变化。", ""]
        for item in reviews:
            lines.append(f"- {escape(item['title'])}：{item['status']}" + (f"，本周值 {number(item['actual'])}" if item["actual"] is not None else "") + "。")
        lines.append("")
    elif a.get("prev_suggestions"):
        lines += ["上期建议没有可核对的程序指标，需本人复查执行情况。", ""]
    lines += ["### 下周动作与复查方法", ""]
    for index, action in enumerate(actions, 1):
        lines += [f"{index}. **{escape(action['title'])}**（{action['kind']}；{action['confidence']}）", "",
                  "   依据：" + escape(action["evidence"]), "", "   动作：" + escape(action["action"]), "",
                  "   下周复查：" + escape(action["review"]), ""]
        if action["source_ids"]:
            lines += ["   官方依据：" + source_links(policy, action["source_ids"]), ""]
    if ideas:
        lines += ["### 基于已有主帖的选题备忘", "", "这是复盘任务，不是代写待发布帖子；不能凭导出文本判断原创权属。", ""]
        for post in ideas:
            link = post["link"] if re.fullmatch(r"https://(?:www\.)?x\.com/[A-Za-z0-9_]+/status/[0-9]+", post["link"]) else None
            text = escape(post["text"])
            lines += [f"- {post['date']} · 曝光 {number(post['impressions'])} · " + (f"[{text}]({link})" if link else text) + "。" + post["task"]]
        lines.append("")
    lines += ["### 尚需本人核对的官方条件", "",
              "CSV不能验证：" + "、".join(missing_conditions) + "。订阅与年龄等以本人资格页和官方审核为准；不根据受众地区推断本人所在地。", "",
              "内容原创性、完整媒体、有效社区注释、自动创建或发布等情况也不能靠CSV文字自动判定。奖励计划可能排除自动创建或发布的内容；一般自动化规则的允许范围不等于奖励资格。", "",
              f"规则快照核验日：{policy['verified_at']}；完整摘要及官方链接见第9节。"]
    return {"engine_version": 1, "origin": "program", "policy_version": policy["version"],
            "policy_verified_at": policy["verified_at"], "policy_stale": stale,
            "summary": summary, "actions": actions, "previous_review": reviews, "topic_notes": ideas,
            "manual_checks": missing_conditions, "markdown": "\n".join(lines).strip()}
