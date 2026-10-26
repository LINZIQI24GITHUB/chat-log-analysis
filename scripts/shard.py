# -*- coding: utf-8 -*-
"""按周/月切分 digest，生成分片文件和 manifest，交给子 agent 并行读。

用法：
  python shard.py work/digest.txt --by week  --out work/shards
  python shard.py work/digest.txt --by month --out work/shards
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys

MARK = re.compile(r"========== (\d{4}-\d{2}-\d{2}) \((\d+)条\) ==========")

# 单分片建议不超过这个字符数，超了继续按周/月拆会更碎，这里只做提示
SOFT_LIMIT = 90_000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("digest")
    ap.add_argument("--by", choices=["week", "month"], default="week")
    ap.add_argument("--out", default="work/shards")
    args = ap.parse_args()

    content = open(args.digest, encoding="utf-8").read()
    marks = list(MARK.finditer(content))
    if not marks:
        print("[error] 没找到日期分块标记，检查 digest 格式")
        return 2

    buckets: dict[str, list[str]] = {}
    for i, m in enumerate(marks):
        start = m.start()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(content)
        d = dt.date.fromisoformat(m.group(1))
        if args.by == "week":
            key = (d - dt.timedelta(days=d.weekday())).isoformat()
            name = f"week_{key}"
        else:
            key = d.strftime("%Y-%m")
            name = f"month_{key}"
        buckets.setdefault(name, []).append(content[start:end])

    os.makedirs(args.out, exist_ok=True)
    manifest = []
    for name, blocks in sorted(buckets.items()):
        path = os.path.join(args.out, f"{name}.txt")
        body = "".join(blocks)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        days = len(blocks)
        manifest.append({"name": name, "path": os.path.abspath(path),
                         "days": days, "chars": len(body),
                         "oversize": len(body) > SOFT_LIMIT})
        print(f"{name}: {days} 天, {len(body) / 1024:.1f} KB"
              + ("  [!] 偏大，考虑再拆" if len(body) > SOFT_LIMIT else ""))

    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"by": args.by, "count": len(manifest), "shards": manifest},
                  f, ensure_ascii=False, indent=1)
    print(f"\n{len(manifest)} 个分片 -> {args.out}/manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
