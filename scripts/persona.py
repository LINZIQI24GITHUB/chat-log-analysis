# -*- coding: utf-8 -*-
"""从聊天记录里蒸馏出一个人的「说话档案」，供模拟对话使用。

输出两份：
  persona.json    机器读的（含 system_prompt）
  persona.md      人读的（你可以检查像不像）

用法：
  python scripts/persona.py work/chat.jsonl --stats work/stats.json --out persona.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import dump_json, load_jsonl  # noqa: E402

STOP = set("""
的 了 吗 呢 啊 吧 嘛 呀 哦 噢 嗯 是 在 有 没 就 都 也 还 又 再 才 只 很 太 最 更 挺
我 你 他 她 它 我们 你们 他们 自己 这 那 这个 那个 这样 那样 什么 怎么 一个 一下
可以 没有 就是 不是 还是 但是 不过 因为 所以 如果 然后 现在 时候 知道 觉得 应该
可能 需要 想要 感觉 东西 事情 问题 地方 有点 真的 其实 反正 随便 没事 好的 好吧
""".split())

PUNCT = "。！？…，、；：""''（）"


def _strip_placeholders(t: str) -> str:
    return re.sub(r"\[[^\]]{1,8}\]", "", t or "")


def _is_placeholder(t: str) -> bool:
    return bool(re.fullmatch(r"\[[^\]]{1,8}\]", (t or "").strip()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("chat")
    ap.add_argument("--stats", default=None)
    ap.add_argument("--analysis", default=None, help="可选：用报告里的模式补充「避开的话题」")
    ap.add_argument("--out", default="persona.json")
    ap.add_argument("--name", default=None, help="对方名字；默认从 chat.jsonl 推断")
    args = ap.parse_args()

    rows = [r for r in load_jsonl(args.chat) if (r.get("text") or "").strip()]
    if not rows:
        print("[error] 没有消息", file=sys.stderr)
        return 2

    name = args.name or next((r.get("name") for r in rows
                              if r.get("sender") == "other"), "对方")
    mine = [r for r in rows if r["sender"] == "me"]
    theirs = [r for r in rows if r["sender"] == "other"]

    # ---------- 说话风格 ----------
    texts = [r["text"] for r in theirs]
    plain = [_strip_placeholders(t) for t in texts]
    lens = [len(t) for t in plain if t]
    sticker = sum(1 for r in theirs if r.get("kind") == "sticker")
    media = sum(1 for r in theirs if r.get("kind") in ("image", "voice", "sticker"))

    one_liner = Counter(t.strip() for t in plain if 0 < len(t.strip()) <= 6)
    catch = [(w, c) for w, c in one_liner.most_common(12) if c >= 2 and w not in STOP]

    # 标点习惯：中文里不用句号的人，和用的人，读起来完全不一样
    sent_end = sum(t.count("。") for t in plain)
    excl = sum(t.count("！") + t.count("!") for t in plain)
    qmark = sum(t.count("？") + t.count("?") for t in plain)
    punct_style = "几乎不用句号" if sent_end <= max(1, len(plain) * 0.05) else "会用句号收尾"

    # 口头语：二元组里出现次数最多的
    bigrams = Counter()
    for t in plain:
        for run in re.findall(r"[\u4e00-\u9fa5]{2,}", t):
            for i in range(len(run) - 1):
                bg = run[i:i + 2]
                if bg not in STOP:
                    bigrams[bg] += 1
    filler = [w for w, c in bigrams.most_common(30) if c >= 3][:8]

    # ---------- 时间节奏 ----------
    timing = {}
    if args.stats and os.path.exists(args.stats):
        st = json.load(open(args.stats, encoding="utf-8"))
        lat = (st.get("latency") or {}).get("other") or {}
        timing = {
            "p10_sec": lat.get("p10"), "p50_sec": lat.get("median"),
            "p90_sec": lat.get("p90"),
            "under_5min": lat.get("under_5min"),
        }
        hours = (st.get("active_hours") or {}).get("other") or {}
        timing["active_hours"] = sorted(
            (int(h) for h, v in hours.items() if v), key=lambda h: -hours[str(h)])[:4]
    if not timing.get("p50_sec"):
        gaps = []
        for a, b in zip(rows, rows[1:]):
            if b["sender"] == "other" and a["sender"] == "me":
                g = b["ts"] - a["ts"]
                if 0 < g < 86400:
                    gaps.append(g)
        if gaps:
            timing.update({
                "p10_sec": round(statistics.quantiles(gaps, n=10)[0], 1),
                "p50_sec": round(statistics.median(gaps), 1),
                "p90_sec": round(sorted(gaps)[int(len(gaps) * 0.9)], 1),
            })

    # 回复率：我发完之后，她 24h 内回没回
    replied = 0
    total_prompts = 0
    for i, r in enumerate(rows[:-1]):
        if r["sender"] != "me":
            continue
        total_prompts += 1
        nxt = rows[i + 1]
        if nxt["sender"] == "other" and nxt["ts"] - r["ts"] <= 86400:
            replied += 1
    reply_rate = round(replied / total_prompts, 2) if total_prompts else 0.6

    # ---------- 避开的话题 ----------
    avoids = []
    if args.analysis and os.path.exists(args.analysis):
        an = json.load(open(args.analysis, encoding="utf-8"))
        for p in an.get("patterns", []):
            if "边界" in p.get("name", "") or "玩笑" in p.get("name", ""):
                avoids.append(p["name"])
    if not avoids:
        avoids = ["关系定义", "催她做决定"]

    # ---------- 组 prompt ----------
    sample = [t for t in plain if len(t) <= 30][-12:]
    avg_len = round(sum(lens) / len(lens), 1) if lens else 8
    prompt = f"""你在模拟一个真实的人聊天，她叫{name}。

【说话方式】
- 平均每条 {avg_len} 字，很少超过 20 字；短句、口语，不要写完整段落
- {punct_style}；{"偶尔用感叹号" if excl > 3 else "很少用感叹号"}
- 表情包/图片占比约 {round(media / max(1, len(theirs)) * 100)}%，情绪多的时候发 [表情]
- 常用短句：{"、".join(w for w, _ in catch[:6]) or "嗯、知道了"}
- 常出现的词：{"、".join(filler[:6]) or "（无）"}

【语气参考】（只学风格：短、口语、不解释。**不要照抄这些句子**）
{chr(10).join("- " + s for s in sample[:6])}

【边界】
- 被问到 {"、".join(avoids[:2])} 时，她会岔开、敷衍（"再说吧""看情况"），不会正面回答
- 不主动示爱、不写长情书、不追问对方

【规则】
- 只用纯文本，不加引号、不加括号动作、不写旁白
- 不承认自己是 AI；但也绝不编造具体事实（时间、金额、承诺）
- 一次只回一条，长度控制在 {max(3, int(avg_len))} 字左右
- **必须针对对方刚说的那句话来回**，不要答非所问，也不要复述上面的参考句
- 不知道怎么回就很短地应付：「嗯」「知道了」「看情况」「再说吧」
"""
    persona = {
        "name": name,
        "source": os.path.abspath(args.chat),
        "counts": {"total": len(rows), "me": len(mine), "other": len(theirs)},
        "style": {
            "avg_len": avg_len,
            "max_len": max(lens) if lens else 0,
            "sticker_rate": round(sticker / max(1, len(theirs)), 2),
            "media_rate": round(media / max(1, len(theirs)), 2),
            "punctuation": punct_style,
            "catchphrases": [w for w, _ in catch[:8]],
            "filler": filler,
        },
        "timing": {**timing, "reply_rate": reply_rate},
        "sample_lines": sample[:8],
        "recent": [{"role": "me" if r["sender"] == "me" else "her",
                    "text": (r.get("text") or "")[:120]}
                   for r in rows
                   if r.get("kind") not in ("system", "call")
                   and "撤回了一条消息" not in (r.get("text") or "")
                   and "领取了你的红包" not in (r.get("text") or "")][-8:],
        "avoids": avoids,
        "system_prompt": prompt,
    }
    dump_json(args.out, persona)

    md = args.out.replace(".json", ".md")
    with open(md, "w", encoding="utf-8") as f:
        f.write(f"# {name} 的说话档案\n\n")
        f.write(f"- 样本：{len(rows)} 条（她 {len(theirs)} 条）\n")
        f.write(f"- 平均 {avg_len} 字，最长 {persona['style']['max_len']} 字\n")
        f.write(f"- 表情包 {persona['style']['sticker_rate']:.0%}｜"
                f"{punct_style}\n")
        f.write(f"- 回复中位 {timing.get('p50_sec', '—')} 秒，"
                f"P90 {timing.get('p90_sec', '—')} 秒｜回复率 {reply_rate:.0%}\n")
        f.write(f"- 活跃时段：{timing.get('active_hours', '—')}\n")
        f.write(f"- 常用短句：{'、'.join(persona['style']['catchphrases']) or '—'}\n\n")
        f.write("## 她说话的样子\n\n")
        for s in sample[:8]:
            f.write(f"> {s}\n\n")
        f.write("## 喂给模型的 prompt\n\n```\n" + prompt + "\n```\n")

    print(f"写入 {args.out} 和 {md}")
    print(f"  平均 {avg_len} 字 | 回复中位 {timing.get('p50_sec','—')}s | "
          f"回复率 {reply_rate:.0%} | 表情 {persona['style']['sticker_rate']:.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
