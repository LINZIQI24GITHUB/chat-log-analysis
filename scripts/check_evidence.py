# -*- coding: utf-8 -*-
"""证据校验：报告里每条引用必须能在原文里逐字找到。

这是防模型编造引用的硬闸门。任何一条对不上，就不许出报告。
用法：python check_evidence.py work/chat.jsonl examples/analysis.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_jsonl  # noqa: E402


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("chat")
    ap.add_argument("analysis")
    ap.add_argument("--allow-fuzzy", action="store_true",
                    help="允许去掉标点后匹配（默认逐字）")
    args = ap.parse_args()

    rows = load_jsonl(args.chat)
    corpus = [norm(r["text"]) for r in rows]
    if args.allow_fuzzy:
        corpus = [re.sub(r"[，。！？、,.!?~…—\"'“”‘’]", "", c) for c in corpus]

    with open(args.analysis, encoding="utf-8") as f:
        an = json.load(f)

    checks, bad = [], []
    for v in an.get("verdicts", []):
        for kind in ("support", "against"):
            for e in v.get(kind, []):
                checks.append((v["q"], kind, e))

    for q, kind, e in checks:
        quote = norm(e["quote"])
        if args.allow_fuzzy:
            quote = re.sub(r"[，。！？、,.!?~…—\"'“”‘’]", "", quote)
        if not any(quote and quote in c for c in corpus):
            bad.append((q, kind, e["quote"], e.get("date", "")))

    print(f"引用总数 {len(checks)}，逐字命中 {len(checks) - len(bad)}，失配 {len(bad)}")
    for q, kind, quote, date in bad:
        print(f"  [x] [{q}] {date} 「{quote}」在原文中找不到")
    if bad:
        print("\n[FAIL] 有引用对不上原文，报告不能发布。")
        return 1
    print("[OK] 所有引用都能在原文里找到。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
