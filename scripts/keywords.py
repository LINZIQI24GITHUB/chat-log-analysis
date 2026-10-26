# -*- coding: utf-8 -*-
"""关键词与话题漂移：谁在聊什么、哪周冒出了新话题。

有 jieba 用 jieba，没有就退回中文二元组（精度差些，但不装依赖也能跑）。
用法：python keywords.py work/chat.jsonl --out work/keywords.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import dump_json, load_jsonl, week_start  # noqa: E402

STOP = set("""
的 了 吗 呢 啊 吧 嘛 呀 哦 噢 嗯 是 在 有 没 就 都 也 还 又 再 才 只 很 太 最 更 挺 蛮 超 巨 贼
我 你 他 她 它 我们 你们 他们 自己 这 那 这个 那个 这样 那样 这些 那些 什么 怎么 怎么样 为什么
一个 一下 一些 一点 一直 一样 一起 一般 一定 可以 不能 不会 不要 不用 不是 就是 还是 但是 不过
因为 所以 如果 虽然 而且 或者 然后 现在 时候 时间 今天 昨天 明天 刚才 已经 还有 没有 知道 觉得
应该 可能 需要 想要 感觉 东西 事情 问题 地方 有点 真的 其实 反正 随便 没事 好的 好吧 行吧 对吧
哈哈 哈哈哈 哈哈哈哈 笑死 救命 好家伙 无语 离谱 真的假的 不是吧 我去 天啊 哎呀 唉 呃 额 哈 嘿
""".split())

CJK = re.compile(r"[\u4e00-\u9fa5]+")
WORD = re.compile(r"[a-zA-Z][a-zA-Z0-9_+#.]{1,}")


def tokenize(text: str, use_jieba: bool, jieba_mod=None) -> list[str]:
    text = re.sub(r"\[[^\]]{1,8}\]", " ", text)  # 去掉 [图片] 这类占位
    if use_jieba:
        out = []
        for w in jieba_mod.cut(text):
            w = w.strip()
            if len(w) >= 2 and w not in STOP and not w.isdigit():
                out.append(w)
        return out
    # 回退：中文二元组 + 英文词
    out = [w.lower() for w in WORD.findall(text) if len(w) >= 2 and w.lower() not in STOP]
    for run in CJK.findall(text):
        if len(run) == 1:
            continue
        for i in range(len(run) - 1):
            bg = run[i:i + 2]
            if bg not in STOP:
                out.append(bg)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("chat")
    ap.add_argument("--out", default="work/keywords.json")
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args()

    try:
        import jieba  # type: ignore
        jieba.setLogLevel(60)
        use_jieba = True
    except Exception:
        jieba, use_jieba = None, False

    rows = [r for r in load_jsonl(args.chat) if r.get("ts")]
    weekly = defaultdict(lambda: {s: Counter() for s in ("me", "other")})
    overall = {s: Counter() for s in ("me", "other")}
    for r in rows:
        if r["kind"] not in ("text", "voice"):
            continue
        s = r["sender"]
        if s not in overall:
            continue
        w = week_start(dt.datetime.fromtimestamp(r["ts"]))
        for tok in tokenize(r["text"], use_jieba, jieba):
            weekly[w][s][tok] += 1
            overall[s][tok] += 1

    weeks = sorted(weekly)
    drift = {}
    for w in weeks:
        others = Counter()
        for w2 in weeks:
            if w2 != w:
                others.update(weekly[w2]["me"])
                others.update(weekly[w2]["other"])
        scored = []
        merged = Counter(weekly[w]["me"])
        merged.update(weekly[w]["other"])
        for word, cnt in merged.items():
            if cnt < 3:
                continue
            score = cnt * math.log(1 + cnt / (others.get(word, 0) + 1))
            scored.append((word, cnt, round(score, 1)))
        scored.sort(key=lambda x: -x[2])
        drift[w] = [{"word": a, "count": b, "score": c} for a, b, c in scored[:12]]

    out = {
        "tokenizer": "jieba" if use_jieba else "bigram",
        "weeks": weeks,
        "overall_top": {s: overall[s].most_common(args.top) for s in overall},
        "weekly_top": {w: {s: weekly[w][s].most_common(15) for s in ("me", "other")}
                       for w in weeks},
        "weekly_drift": drift,
    }
    dump_json(args.out, out)

    print(f"分词器: {out['tokenizer']} | {len(weeks)} 周")
    for s in ("me", "other"):
        top = " ".join(f"{w}({c})" for w, c in out["overall_top"][s][:12])
        print(f"  {s} 高频: {top}")
    for w in weeks:
        top = " ".join(x["word"] for x in drift[w][:6])
        print(f"  {w} 本周特有: {top}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
