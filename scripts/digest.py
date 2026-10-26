# -*- coding: utf-8 -*-
"""把 chat.jsonl 压成按天分块的可读文本，供模型/子 agent 阅读。

用法：python digest.py work/chat.jsonl --out work/digest.txt
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import date_of, load_jsonl  # noqa: E402

MAX_CHARS = 300


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("chat")
    ap.add_argument("--out", default="work/digest.txt")
    ap.add_argument("--max-chars", type=int, default=MAX_CHARS)
    args = ap.parse_args()

    rows = [r for r in load_jsonl(args.chat) if r.get("ts")]
    days = defaultdict(list)
    for r in rows:
        days[date_of(r["ts"])].append(r)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for d in sorted(days):
            rs = days[d]
            f.write(f"\n========== {d} ({len(rs)}条) ==========\n")
            for r in rs:
                who = "我" if r["sender"] == "me" else "对方"
                t = r["time"][11:16]
                text = r["text"].replace("\n", " ")
                if len(text) > args.max_chars:
                    text = text[: args.max_chars] + "…"
                f.write(f"{t} {who}: {text}\n")

    size = os.path.getsize(args.out)
    print(f"写入 {args.out}  {size / 1024:.1f} KB  {len(days)} 天  {len(rows)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
