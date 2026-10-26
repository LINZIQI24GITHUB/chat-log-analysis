# -*- coding: utf-8 -*-
"""把 stats/profile/keywords/analysis 渲染成 report.md 和 report.html。

用法：
  python render_report.py --stats work/stats.json --profile work/profile.json \
      --keywords work/keywords.json --analysis examples/analysis.json \
      --out work/report.md --html work/report.html
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def fmt_sec(s) -> str:
    if not s:
        return "—"
    s = float(s)
    if s < 60:
        return f"{s:.0f} 秒"
    if s < 3600:
        return f"{s / 60:.1f} 分钟"
    return f"{s / 3600:.1f} 小时"


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_md(stats: dict, profile: dict, kw: dict, an: dict, masked: bool = True) -> str:
    m = an["meta"]
    s = stats["senders"]
    ses = stats["sessions"]
    lat = stats["latency"]
    L = []
    A = L.append

    A(f"# {m['title']}")
    A("")
    A(f"> {m['one_line']}")
    A("")
    who = "对方" if masked else (m.get("other_name") or "对方")
    scope = m["scope"] + (" ｜ 对方姓名已脱敏" if masked else " ｜ 含真实姓名")
    A(f"**范围**：{m['period']} ｜ 与{who} ｜ {profile['total']} 条 ｜ "
      f"{profile['days']} 天 ｜ {scope}")
    A("")
    level = profile["level"]
    level_text = {"ok": "可以做趋势判断", "descriptive": "样本偏少，只做描述，不做趋势预测",
                  "unusable": "样本不足，结论不可信"}[level]
    A(f"**数据体检**：{level_text}")
    for w in profile["warnings"]:
        A(f"- {w}")
    A("")
    fws = an.get("frameworks_used") or []
    if fws:
        A("**分析框架**")
        A("")
        for f in fws:
            A(f"- {f.get('name','')} —— {f.get('why','')}")
        A("")
    A("---")
    A("")

    # ---------- 三个问题 ----------
    A(f"## {an.get('meta', {}).get('questions_title', '你想问的三件事')}")
    A("")
    for i, v in enumerate(an["verdicts"], 1):
        conf = v.get("confidence")
        head = f"### {i}. {v['q']} —— **{v['score']}**"
        if conf:
            head += f" ｜ 置信度：{conf}"
        A(head)
        A("")
        A(f"> {v['answer']}")
        A("")
        if v.get("framework"):
            A(f"**框架**：{' / '.join(v['framework'])}")
            A("")
        A("**支持这个判断的记录**")
        A("")
        for e in v.get("support", []):
            A(f"- `{e['date']}` 「{e['quote']}」—— {e['why']}")
        A("")
        if v.get("against"):
            A("**反方向或者不完全成立的记录**")
            A("")
            for e in v["against"]:
                A(f"- `{e['date']}` 「{e['quote']}」—— {e['why']}")
            A("")
        if v.get("alt"):
            alt = re.sub(r"^另一种解释[:：]\s*", "", v["alt"])
            A(f"**另一种解释**：{alt}")
            A("")
        if v.get("verdict_line"):
            A(f"**一句话**：{v['verdict_line']}")
            A("")
        A("---")
        A("")

    # ---------- 阶段 ----------
    A("## 关系走势")
    A("")
    if level != "ok":
        A("> 样本偏少，阶段划分来自定性阅读，不是统计推断。")
        A("")
    A("| 阶段 | 时间 | 说明 |")
    A("|---|---|---|")
    for p in an["phases"]:
        A(f"| {p['label']} | {p['range']} | {p['note']} |")
    A("")

    # ---------- 数字 ----------
    A("## 数字部分")
    A("")
    A("这些数字由脚本算出，不经过模型，可以复核。")
    A("")
    A("| 指标 | 我 | 对方 |")
    A("|---|---|---|")
    A(f"| 消息数 | {s['me']['msgs']} | {s['other']['msgs']} |")
    A(f"| 平均字数 | {s['me']['avg_len']} | {s['other']['avg_len']} |")
    A(f"| 发起会话 | {ses['initiator'].get('me', 0)} | {ses['initiator'].get('other', 0)} |")
    A(f"| 收尾会话 | {ses['ender'].get('me', 0)} | {ses['ender'].get('other', 0)} |")
    A(f"| 回复中位 | {fmt_sec(lat['me'].get('median'))} | {fmt_sec(lat['other'].get('median'))} |")
    A(f"| 回复 P90 | {fmt_sec(lat['me'].get('p90'))} | {fmt_sec(lat['other'].get('p90'))} |")
    A(f"| 5 分钟内回复 | {lat['me'].get('under_5min', 0):.0%} | {lat['other'].get('under_5min', 0):.0%} |")
    A("")
    A(f"共 {ses['count']} 段会话，平均 {ses['avg_msgs']} 条/段；"
      f"每天先开口：我 {stats['day_openers'].get('me', 0)} 次 / 对方 {stats['day_openers'].get('other', 0)} 次。")
    A("")

    wk = stats.get("latency_by_week") or {}
    if wk:
        A("**回复速度按周变化**（会话内换手中位数）")
        A("")
        A("| 周 | 我 | 对方 |")
        A("|---|---|---|")
        for w, v in wk.items():
            A(f"| {w} | {fmt_sec(v.get('me'))} | {fmt_sec(v.get('other'))} |")
        A("")

    ph = stats.get("peak_hours") or {}
    A(f"活跃时段：我 {'、'.join(f'{h}点' for h, _ in ph.get('me', []))}；"
      f"对方 {'、'.join(f'{h}点' for h, _ in ph.get('other', []))}。")
    A("")

    if stats.get("silences"):
        A("**最长的几段沉默**")
        A("")
        for x in stats["silences"][:3]:
            A(f"- {x['from']} → {x['to']}（{x['hours']} 小时），由{'我' if x['resumed_by'] == 'me' else '对方'}重新开口")
        A("")

    # ---------- 关键词 ----------
    if kw:
        A("## 你们在聊什么")
        A("")
        A(f"（分词器：{kw.get('tokenizer')}）")
        A("")
        for who, label in (("me", "我"), ("other", "对方")):
            words = "、".join(f"{w}({c})" for w, c in kw["overall_top"].get(who, [])[:10])
            A(f"- **{label}**：{words}")
        A("")
        drift = kw.get("weekly_drift") or {}
        if drift:
            A("**每周冒出来的新词**")
            A("")
            for w, items in drift.items():
                if items:
                    A(f"- {w}：{'、'.join(x['word'] for x in items[:6])}")
            A("")

    # ---------- 红旗 ----------
    A("## 红旗清单")
    A("")
    A("| 行为 | 次数 | 出处 | 程度 | 框架 |")
    A("|---|---|---|---|---|")
    for r in an["red_flags"]:
        A(f"| {r['behavior']} | {r['count']} | {r['evidence']} | {r['severity']} | "
          f"{r.get('framework','—')} |")
    A("")

    # ---------- 模式 ----------
    A("## 反复出现的模式")
    A("")
    for p in an["patterns"]:
        name = p["name"] + (f"（{p['framework']}）" if p.get("framework") else "")
        A(f"### {name}")
        A("")
        A(p["desc"])
        A("")

    # ---------- 建议 ----------
    A("## 可以怎么做")
    A("")
    for a in an["advice"]:
        A(f"- {a['text']}")
    A("")

    # ---------- 局限 ----------
    A("## 这份分析看不到什么")
    A("")
    for x in an["limits"]:
        A(f"- {x}")
    A("")

    A("---")
    A("")
    A("## 方法说明")
    A("")
    A("- 数字部分（条数、发起、回复速度、活跃时段、沉默）由脚本直接从聊天记录计算，可复核。")
    qs = "、".join(v["q"] for v in an.get("verdicts", []))
    A(f"- 判断部分（{qs}）由模型基于原文做定性判断，标注了支持与反对证据。")
    A("- 每条引用都经过字符串校验，必须能在原文中找到，否则不会出现在报告里。")
    A("- 框架来自公开的亲密关系研究（依恋、Gottman、Rusbult 等），"
      "样本以西方已婚异性恋夫妻为主，跨文化适用性有限，只做描述性使用。")
    A("- 本报告是探索性分析，不是心理诊断，也不能替你做决定。")
    A("")
    return "\n".join(L)


def _inline(text: str) -> str:
    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"`([^`]+?)`", r"<code>\1</code>", t)
    return t


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--keywords", default=None)
    ap.add_argument("--analysis", required=True)
    ap.add_argument("--out", default="work/report.md")
    ap.add_argument("--html", default=None)
    ap.add_argument("--reveal", action="store_true",
                    help="显示对方真名（默认脱敏为「对方」）")
    args = ap.parse_args()

    stats = load(args.stats)
    profile = load(args.profile)
    kw = load(args.keywords) if args.keywords and os.path.exists(args.keywords) else {}
    an = load(args.analysis)

    md = build_md(stats, profile, kw, an, masked=not args.reveal)
    if not args.reveal:
        name = (an.get("meta") or {}).get("other_name")
        if name:
            md = md.replace(name, "对方")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"写入 {args.out}  {len(md) / 1024:.1f} KB")

    if args.html:
        import report_html
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(report_html.build(stats, profile, kw, an, masked=not args.reveal))
        print(f"写入 {args.html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
