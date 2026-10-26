# -*- coding: utf-8 -*-
"""一条命令跑完确定性部分（不含模型判断）。

python scripts/run_all.py examples/sample_chat.txt --self 我 --out work

之后：
  1. 读 work/shards/*.txt，让子 agent 按 references/rubric.md 打分
  2. 把汇总写成 analysis.json（结构见 SKILL.md）
  3. python scripts/check_evidence.py work/chat.jsonl analysis.json
  4. python scripts/render_report.py --stats work/stats.json --profile work/profile.json \
         --keywords work/keywords.json --analysis analysis.json --out work/report.md --html work/report.html
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def run(title: str, args: list[str]) -> int:
    print(f"\n=== {title} ===")
    print("$ python " + " ".join(args))
    r = subprocess.run([sys.executable] + args, cwd=os.path.dirname(HERE))
    return r.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--self", default="我")
    ap.add_argument("--other", default=None)
    ap.add_argument("--out", default="work")
    ap.add_argument("--by", choices=["week", "month"], default="week")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    chat = os.path.join(args.out, "chat.jsonl")

    norm = ["scripts/normalize.py", args.input, "--self", args.self, "--out", chat]
    if args.other:
        norm += ["--other", args.other]
    steps = [
        ("1/5 归一化", norm),
        ("2/5 数据体检", ["scripts/profile.py", chat, "--out", os.path.join(args.out, "profile.json")]),
        ("3/5 指标", ["scripts/stats.py", chat, "--out", os.path.join(args.out, "stats.json")]),
        ("4/5 关键词", ["scripts/keywords.py", chat, "--out", os.path.join(args.out, "keywords.json")]),
        ("5/5 分片", ["scripts/digest.py", chat, "--out", os.path.join(args.out, "digest.txt")]),
    ]
    for title, cmd in steps:
        if run(title, cmd) != 0:
            print(f"[fail] {title}")
            return 1

    if run("切分", ["scripts/shard.py", os.path.join(args.out, "digest.txt"),
                    "--by", args.by, "--out", os.path.join(args.out, "shards")]) != 0:
        return 1

    print("\n确定性部分完成。接下来交给模型：")
    print(f"  1) 读 {args.out}/shards/*.txt（每片一个子 agent），按 references/rubric.md 打分")
    print(f"  2) 汇总成 analysis.json")
    print(f"  3) python scripts/check_evidence.py {chat} analysis.json")
    print(f"  4) python scripts/render_report.py --stats {args.out}/stats.json "
          f"--profile {args.out}/profile.json --keywords {args.out}/keywords.json "
          f"--analysis analysis.json --out {args.out}/report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
