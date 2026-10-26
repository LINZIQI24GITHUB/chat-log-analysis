# -*- coding: utf-8 -*-
"""从聊天记录里蒸馏一个人的说话方式、互动习惯和你们的关系。

v2 相比 v1 多了三样东西：
  1. **真实对答片段**（我一句 / 她一句），喂给模型当 few-shot，学的是节奏不是词
  2. **互动结构统计**：她提问吗？主动开场吗？单字回复多少？语气词怎么用？
  3. **关系画像**：从 analysis.json 读，或者从数据里推断

输出：
  persona.json   机器读（含 system_prompt 和 few_shot）
  persona.md     人读（你可以检查像不像）

用法：
  python scripts/persona.py work/chat.jsonl --stats work/stats.json \
      --analysis analysis.json --out persona.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import dump_json, load_jsonl  # noqa: E402

PLACEHOLDER = re.compile(r"^\[(?:type\d+|[^\]]{1,8})\]$")
SYS_NOISE = ("撤回了一条消息", "领取了你的红包", "拍了拍", "加入了群聊", "退出了群聊")
PARTICLES = "啊呀吧呢嘛哈啦哦噢嘞呗咯哇诶欸"
QUESTION = re.compile(r"[?？]")
BOUNDARY_WORDS = ("不想", "别", "算了", "不去", "不要", "随便", "没空", "再说",
                  "不聊", "无语", "烦", "滚")
POS_WORDS = ("哈哈", "笑死", "开心", "爽", "太好了", "喜欢", "不错", "牛", "厉害",
             "赚", "涨", "好耶", "嘿嘿", "舒服")
NEG_WORDS = ("亏", "难受", "烦", "累", "崩", "怕", "哭", "麻了", "绝望", "完蛋",
             "恶心", "疼", "气", "傻逼", "卧槽")


def _clean(t: str) -> str:
    return re.sub(r"\[[^\]]{1,8}\]", "", t or "").strip()


def _is_noise(t: str) -> bool:
    t = (t or "").strip()
    if not t or PLACEHOLDER.match(t) or t in ("[图片]", "[语音]", "[视频]"):
        return True
    return any(w in t for w in SYS_NOISE)


def build_turns(rows: list[dict]) -> list[dict]:
    """把消息流切成「我连续几句 → 她回几句」的对答对。"""
    pairs, mine, hers = [], [], []

    def close():
        nonlocal mine, hers
        if mine and hers:
            me_txt = "\n".join(_clean(m["text"]) for m in mine).strip()
            her_txt = "\n".join(_clean(h["text"]) for h in hers).strip()
            if 1 <= len(me_txt) <= 90 and 1 <= len(her_txt) <= 70:
                pairs.append({"me": me_txt, "her": her_txt,
                              "ts": hers[0]["ts"],
                              "gap": hers[0]["ts"] - mine[-1]["ts"]})
        mine, hers = [], []

    for r in rows:
        if _is_noise(r.get("text")):
            continue
        if r["sender"] == "me":
            if hers:
                close()
            mine.append(r)
        elif mine:
            hers.append(r)
    close()
    return pairs




def infer_personality(style: dict, inter: dict, bounds: list, topics: list) -> list:
    """从行为统计推性格，每条都带数字依据，不写空话。"""
    out = []
    if inter["her_open_rate"] < 0.15:
        out.append({"trait": "被动，很少主动找人",
                    "evidence": f"她开场仅 {inter['her_open_rate']:.0%}"})
    else:
        out.append({"trait": "会主动找人",
                    "evidence": f"她开场 {inter['her_open_rate']:.0%}"})

    if style["avg_len"] <= 8:
        out.append({"trait": "话短，不爱展开",
                    "evidence": f"平均 {style['avg_len']} 字"})
    if inter["multi_send_rate"] > 0.4:
        out.append({"trait": "爱连发：想一句发一句",
                    "evidence": f"连发率 {inter['multi_send_rate']:.0%}"})
    if style.get("sticker_rate", 0) > 0.1 or style.get("exclaim_rate", 0) > 0.15:
        out.append({"trait": "情绪外露，用表情和感叹号",
                    "evidence": f"表情 {style.get('sticker_rate', 0):.0%}"})
    if style.get("question_rate", 0) < 0.05:
        out.append({"trait": "不反问，不追问对方",
                    "evidence": f"问句仅 {style.get('question_rate', 0):.0%}"})
    if inter.get("answer_rate") is not None and inter["answer_rate"] < 0.1:
        out.append({"trait": "回避正面回应，常岔开",
                    "evidence": "被问到时几乎不接问句"})
    if bounds:
        out.append({"trait": "有明确边界，会直接拒绝",
                    "evidence": f"例如「{bounds[0][:12]}」"})
    if topics:
        out.append({"trait": f"主要聊：{'、'.join(topics[:3])}",
                    "evidence": "高频话题"})
    return out[:6]


def mood_curve(rows: list, theirs: list) -> dict:
    """按天算情绪分：正向词 / 负向词 / 表情 / 感叹号，归一化到 -1..1。"""
    from collections import defaultdict
    by_day = defaultdict(list)
    for r in theirs:
        t = _clean(r["text"])
        if not t:
            continue
        day = time.strftime("%Y-%m-%d", time.localtime(r["ts"])) if r.get("ts") else None
        if not day:
            continue
        by_day[day].append((t, r.get("kind")))

    curve = []
    for day in sorted(by_day):
        items = by_day[day]
        pos = neg = 0
        for t, kind in items:
            pos += sum(t.count(w) for w in POS_WORDS)
            neg += sum(t.count(w) for w in NEG_WORDS)
            if kind == "sticker":
                pos += 0.5
            pos += t.count("！") * 0.3
        n = max(1, len(items))
        score = (pos - neg) / (pos + neg + 1)      # 比例型：-1..1，不受当天条数稀释
        score = round(max(-1.0, min(1.0, score)), 2)
        curve.append({"day": day, "n": len(items), "score": round(score, 2)})

    if not curve:
        return {"baseline": 0.0, "curve": [], "notable": []}

    recent = curve[-5:]
    baseline = round(sorted(c["score"] for c in recent)[len(recent) // 2], 2)
    notable = [c for c in curve if abs(c["score"]) >= 0.35 and c["n"] >= 3][-6:]
    return {"baseline": baseline, "curve": curve[-30:], "notable": notable}


def memory_anchors(theirs: list, limit: int = 12) -> list:
    """她亲口说过的具体事实，供模拟时「记得」。"""
    import re as _re
    facts = []
    seen = set()
    pat = _re.compile(r"(\d+(?:\.\d+)?\s*(?:万|块|元|%|天|年|个月|点|号))|(\d{3,8})")
    bad = _re.compile(r"^(1[0-9]{9,}|[0-9]{9,})$")
    for r in theirs:
        t = _clean(r["text"])
        if not (2 <= len(t) <= 120) or "[" in t:
            continue
        hits = [a or b for a, b in pat.findall(t)]
        hits = [x for x in hits if x and not bad.match(x.replace(" ", ""))]
        if not hits:
            continue
        key = hits[0]
        if key in seen:
            continue
        seen.add(key)
        day = time.strftime("%Y-%m-%d", time.localtime(r["ts"])) if r.get("ts") else ""
        facts.append({"day": day, "text": t[:50], "value": key})
        if len(facts) >= limit:
            break
    return facts

def pick_spread(pairs: list[dict], n: int) -> list[dict]:
    """在时间轴上均匀取样，避免全是同一个话题。"""
    if len(pairs) <= n:
        return pairs
    step = len(pairs) / n
    return [pairs[int(i * step)] for i in range(n)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("chat")
    ap.add_argument("--stats", default=None)
    ap.add_argument("--analysis", default=None, help="可选：报告里的关系判断")
    ap.add_argument("--out", default="persona.json")
    ap.add_argument("--name", default=None)
    ap.add_argument("--turns", type=int, default=10, help="few-shot 对答组数")
    args = ap.parse_args()

    rows = [r for r in load_jsonl(args.chat) if (r.get("text") or "").strip()]
    if not rows:
        print("[error] 没有消息", file=sys.stderr)
        return 2

    name = args.name or next((r.get("name") for r in rows
                              if r.get("sender") == "other"), "对方")
    mine = [r for r in rows if r["sender"] == "me"]
    theirs = [r for r in rows if r["sender"] == "other"]
    texts = [_clean(r["text"]) for r in theirs if not _is_noise(r.get("text"))]
    lens = [len(t) for t in texts if t]

    # ---------- 说话方式 ----------
    avg_len = round(sum(lens) / len(lens), 1) if lens else 8
    one_two = sum(1 for l in lens if l <= 2) / max(1, len(lens))
    asks = sum(1 for t in texts if QUESTION.search(t)) / max(1, len(texts))
    sticky = sum(1 for r in theirs if r.get("kind") == "sticker") / max(1, len(theirs))
    exclaim = sum(t.count("！") + t.count("!") for t in texts) / max(1, len(texts))
    period = sum(t.count("。") for t in texts) / max(1, len(texts))
    part = Counter(ch for t in texts for ch in t if ch in PARTICLES)
    top_part = [c for c, _ in part.most_common(4)]

    whole = Counter(t.strip() for t in texts if 1 <= len(t.strip()) <= 6)
    catch = [w for w, c in whole.most_common(10) if c >= 2][:6]

    # ---------- 互动结构 ----------
    turns = build_turns(rows)

    def session_first(gap=3600):
        firsts_, last = [], 0
        for r in rows:
            if r["ts"] - last > gap:
                firsts_.append(r["sender"])
            last = max(last, r["ts"])
        return firsts_

    firsts = session_first()
    her_open = firsts.count("other") / max(1, len(firsts))

    runs, cur = [], 0
    for r in rows:
        if r["sender"] == "other":
            cur += 1
        else:
            if cur:
                runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    mult = sum(1 for x in runs if x >= 2) / max(1, len(runs))

    after_q, after_q_answered = 0, 0
    for a, b in zip(rows, rows[1:]):
        if a["sender"] == "me" and QUESTION.search(_clean(a["text"])):
            after_q += 1
            if b["sender"] == "other" and QUESTION.search(_clean(b["text"])):
                after_q_answered += 1

    her_starts, last_ts = [], 0
    for r in rows:
        if r["sender"] == "other" and r["ts"] - last_ts > 7200:
            t = _clean(r["text"])
            if t and not _is_noise(t):
                her_starts.append(t)
        last_ts = max(last_ts, r["ts"])

    # ---------- 边界 ----------
    bounds = []
    for r in theirs:
        t = _clean(r["text"])
        if 2 <= len(t) <= 24 and any(w in t for w in BOUNDARY_WORDS):
            bounds.append(t)
        if len(bounds) >= 4:
            break

    # ---------- 时延 ----------
    timing = {}
    if args.stats and os.path.exists(args.stats):
        st = json.load(open(args.stats, encoding="utf-8"))
        lat = (st.get("latency") or {}).get("other") or {}
        timing = {"p10_sec": lat.get("p10"), "p50_sec": lat.get("median"),
                  "p90_sec": lat.get("p90"), "under_5min": lat.get("under_5min")}
    if not timing.get("p50_sec"):
        gaps = [p["gap"] for p in turns if 0 < p["gap"] < 86400]
        if gaps:
            timing = {"p10_sec": round(statistics.quantiles(gaps, n=10)[0], 1),
                      "p50_sec": round(statistics.median(gaps), 1),
                      "p90_sec": round(sorted(gaps)[int(len(gaps) * 0.9)], 1)}
    replied = sum(1 for i, r in enumerate(rows[:-1]) if r["sender"] == "me"
                  and rows[i + 1]["sender"] == "other"
                  and rows[i + 1]["ts"] - r["ts"] <= 86400)
    timing["reply_rate"] = round(replied / max(1, len(mine)), 2)

    # ---------- 关系画像 ----------
    relation, patterns = "", []
    if args.analysis and os.path.exists(args.analysis):
        an = json.load(open(args.analysis, encoding="utf-8"))
        relation = (an.get("verdicts") or [{}])[0].get("verdict_line", "")
        patterns = [p["name"] for p in an.get("patterns", [])][:3]
    if not relation:
        ratio = len(mine) / max(1, len(theirs))
        relation = ("你更主动，她多半被动接话" if ratio > 1.3
                    else "两边投入差不多，谁想起谁说话")

    few = pick_spread([p for p in turns if len(p["me"]) <= 40 and len(p["her"]) <= 30],
                      args.turns)

    # ---------- 性格 / 情绪 / 记忆锚点 ----------
    inter = {"her_open_rate": round(her_open, 2),
             "multi_send_rate": round(mult, 2),
             "answer_rate": round(after_q_answered / after_q, 2) if after_q else None}
    style_d = {"avg_len": avg_len, "sticker_rate": round(sticky, 2),
               "question_rate": round(asks, 2), "exclaim_rate": round(exclaim, 2)}
    topics = []
    for kw in ("股票", "A股", "美股", "定投", "基金", "工作", "加班", "游戏", "上号",
               "咖啡", "奶茶", "吃饭", "旅游", "考试", "论文"):
        if sum(1 for t in texts if kw in t) >= 3:
            topics.append(kw)
    personality = infer_personality(style_d, inter, bounds, topics)
    mood = mood_curve(rows, theirs)
    anchors = memory_anchors(theirs)

    # ---------- prompt ----------
    lines = [
        f"你叫{name}，正在微信上和一个熟的人聊天。",
        f"你们的关系：{relation}",
        "",
        "【你怎么说话】",
        f"- 平均每条 {avg_len} 字；{one_two:.0%} 的回复只有一两个字",
        f"- 约 {asks:.0%} 的消息带问号；感叹号 {exclaim:.0%}；句号 {period:.0%}",
        f"- 表情包占 {sticky:.0%}；情绪到了就发表情，不说话也行",
    ]
    if top_part:
        lines.append(f"- 常用语气词：{'、'.join(top_part)}")
    if catch:
        lines.append(f"- 口头禅：{'、'.join(catch)}")
    if mult > 0.2:
        lines.append(f"- {mult:.0%} 的时候会连发两三条短消息，而不是一次说完")
    if personality:
        lines += ["", "【你的性格】（从聊天里统计出来的，照着演，不要说出来）"]
        lines += [f"- {x['trait']}（{x['evidence']}）" for x in personality]
    if mood.get("notable"):
        last = mood["notable"][-1]
        lines += ["", "【你最近的状态】"]
        lines.append(f"- 整体情绪基线：{'偏积极' if mood['baseline'] > 0.15 else '偏平淡' if mood['baseline'] > -0.15 else '偏低落'}")
        lines.append(f"- {last['day']} 那天情绪很{'高' if last['score'] > 0 else '低'}"
                     f"（{last['score']}，{last['n']} 条）")
    lines += ["", "【你俩的相处】"]
    if her_open > 0.4:
        lines.append(f"- 你经常主动找他（{her_open:.0%} 的开场是你发的）")
    else:
        lines.append(f"- 你很少主动开场（{her_open:.0%}），多半是他先找你")
    if after_q:
        rate = after_q_answered / after_q
        if rate < 0.05:
            lines.append("- 你几乎从不反问：他问什么你答什么，不想答就岔开")
        else:
            lines.append(f"- 他问问题时，你 {rate:.0%} 会回问一句，其余时候正面答或岔开")
    if patterns:
        lines.append(f"- 你们的固定套路：{'；'.join(patterns)}")
    if her_starts:
        lines.append(f"- 你偶尔自己开话题，比如：{her_starts[0][:20]}")
    if anchors:
        lines += ["", "【你亲口说过的事（真实，可以引用）】"]
        lines += [f"- {a['day']}：{a['text'][:38]}" for a in anchors[:6]]
    if bounds:
        lines += ["", "【你会拒绝的样子】（参考语气，不要照抄）"] + [f"- {b}" for b in bounds[:3]]
    lines += [
        "",
        "【规则】",
        "- 只输出你这一条回复的纯文本：不加引号、不加括号动作、不写旁白",
        "- 针对他刚说的那句回，别答非所问，也别复述下面的示例",
        "- 不要像助手：不提供帮助、不建议、不总结、不列点",
        "- 不解释自己为什么这么说；真人不会解释",
        "- **不要编造具体数字、金额、日期、人名**；不确定就含糊：「忘了」「差不多」「就那样」",
        "- 不知道回什么就极短地应付：嗯、哦、知道了、看情况",
    ]
    prompt = "\n".join(lines)

    persona = {
        "name": name,
        "source": os.path.abspath(args.chat),
        "counts": {"total": len(rows), "me": len(mine), "other": len(theirs)},
        "style": {
            "avg_len": avg_len,
            "max_len": max(lens) if lens else 0,
            "sticker_rate": round(sticky, 2),
            "question_rate": round(asks, 2),
            "one_two_rate": round(one_two, 2),
            "particles": top_part,
            "catchphrases": catch,
        },
        "interaction": {
            "her_open_rate": round(her_open, 2),
            "multi_send_rate": round(mult, 2),
            "answer_rate": round(after_q_answered / after_q, 2) if after_q else None,
            "her_topics": her_starts[:3],
        },
        "timing": timing,
        "relationship": relation,
        "patterns": patterns,
        "boundaries": bounds[:4],
        "personality": personality,
        "mood": mood,
        "memory_anchors": anchors,
        "few_shot": few,
        "recent": [{"role": "me" if r["sender"] == "me" else "her",
                    "text": (r.get("text") or "")[:120]}
                   for r in rows
                   if r.get("kind") not in ("system", "call")
                   and "撤回了一条消息" not in (r.get("text") or "")
                   and "领取了你的红包" not in (r.get("text") or "")][-8:],
        "system_prompt": prompt,
    }
    dump_json(args.out, persona)

    md = args.out.replace(".json", ".md")
    with open(md, "w", encoding="utf-8") as f:
        f.write(f"# {name} 的说话档案\n\n")
        f.write(f"- 样本 {len(rows)} 条（她 {len(theirs)} 条）\n")
        f.write(f"- 平均 {avg_len} 字；单双字回复 {one_two:.0%}；问句 {asks:.0%}\n")
        f.write(f"- 回复中位 {timing.get('p50_sec', '—')} 秒；回复率 {timing['reply_rate']:.0%}\n")
        f.write(f"- 她主动开场 {her_open:.0%}；连发 {mult:.0%}；"
                f"被问反问率 {persona['interaction']['answer_rate']}\n")
        f.write(f"- 关系：{relation}\n\n")
        f.write("## 性格\n\n")
        for x in personality:
            f.write(f"- {x['trait']}（{x['evidence']}）\n")
        f.write(f"\n## 情绪\n\n- 基线 {mood.get('baseline')}\n")
        for n in mood.get("notable", []):
            f.write(f"- {n['day']}：{n['score']}（{n['n']} 条）\n")
        f.write("\n## 她亲口说过的事\n\n")
        for a in anchors[:6]:
            f.write(f"- {a['day']}：{a['text'][:50]}\n")
        f.write("\n## 真实对答（few-shot）\n\n")
        for p in few:
            f.write(f"> 我：{p['me']}\n>\n> 她：{p['her']}\n\n")
        f.write("## 边界\n\n")
        for b in persona["boundaries"]:
            f.write(f"- {b}\n")
        f.write("\n## prompt\n\n```\n" + prompt + "\n```\n")

    print(f"写入 {args.out} 和 {md}")
    print(f"  平均 {avg_len} 字 | 问句 {asks:.0%} | 单双字 {one_two:.0%} | "
          f"她开场 {her_open:.0%} | 对答 {len(few)} 组")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
