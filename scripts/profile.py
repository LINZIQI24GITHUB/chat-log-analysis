# -*- coding: utf-8 -*-
"""数据体检：先判断这段记录够不够做分析，不够就降级或劝退。

用法：python profile.py work/chat.jsonl --out work/profile.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import date_of, dump_json, load_jsonl  # noqa: E402

MIN_OK = 300       # 低于此条数：只做描述、不做趋势
MIN_USABLE = 80    # 低于此条数：基本没法分析
MIN_DAYS = 7       # 少于 7 天不给"变化趋势"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("chat")
    ap.add_argument("--out", default="work/profile.json")
    args = ap.parse_args()

    rows = load_jsonl(args.chat)
    if not rows:
        print("[error] 空文件")
        return 2

    stamped = [r for r in rows if r.get("ts")]
    by_sender = Counter(r["sender"] for r in rows)
    by_kind = Counter(r["kind"] for r in rows)

    days = sorted({date_of(r["ts"]) for r in stamped}) if stamped else []
    span_days = 0
    gaps = []
    if len(days) >= 2:
        first = dt.date.fromisoformat(days[0])
        last = dt.date.fromisoformat(days[-1])
        span_days = (last - first).days + 1
        for a, b in zip(days, days[1:]):
            g = (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days
            if g > 1:
                gaps.append({"after": a, "before": b, "missing_days": g - 1})

    per_day = Counter(date_of(r["ts"]) for r in stamped) if stamped else Counter()
    media = sum(v for k, v in by_kind.items() if k != "text")

    warnings, level = [], "ok"
    if len(rows) < MIN_USABLE:
        level = "unusable"
        warnings.append(f"只有 {len(rows)} 条消息，样本太小，任何结论都不可靠")
    elif len(rows) < MIN_OK:
        level = "descriptive"
        warnings.append(f"只有 {len(rows)} 条（<{MIN_OK}），只做描述性分析，不做趋势判断")
    if len(days) < MIN_DAYS:
        level = "descriptive" if level == "ok" else level
        warnings.append(f"只覆盖 {len(days)} 天（<{MIN_DAYS}），看不出关系阶段变化")
    if len(stamped) < len(rows) * 0.5:
        warnings.append(f"{len(rows) - len(stamped)} 条没有时间戳，回复速度/活跃时段不可用")
    if by_sender.get("me", 0) < 10 or by_sender.get("other", 0) < 10:
        warnings.append("一方消息过少，互动结构无法比较（可能只复制了单侧）")
    if media and media > len(rows) * 0.3:
        warnings.append(f"媒体消息占 {media / len(rows):.0%}，文字量偏少，情绪判断证据不足")
    voice_plain = sum(1 for r in rows
                       if r.get("kind") == "voice" and (r.get("text") or "").strip() in ("[语音]", ""))
    if voice_plain:
        warnings.append(
            f"{voice_plain} 条语音没有转写（显示为 [语音]）——"
            f"需要的话用 --asr dashscope，音频会上传阿里云")

    if gaps:
        total_missing = sum(g["missing_days"] for g in gaps)
        if total_missing >= 3:
            warnings.append(f"中间有 {len(gaps)} 段空档，共缺 {total_missing} 天，"
                            f"结论需按「有记录的区间」理解")

    profile = {
        "total": len(rows),
        "stamped": len(stamped),
        "me": by_sender.get("me", 0),
        "other": by_sender.get("other", 0),
        "by_kind": dict(by_kind),
        "media": media,
        "first": rows[0].get("time"),
        "last": rows[-1].get("time"),
        "days": len(days),
        "span_days": span_days,
        "avg_per_day": round(len(rows) / max(1, len(days)), 1),
        "busiest_day": per_day.most_common(1)[0] if per_day else None,
        "quiet_days": sorted(set(days) - set(per_day)),
        "gaps": gaps,
        "level": level,
        "warnings": warnings,
    }
    dump_json(args.out, profile)

    print(f"消息 {len(rows)} 条 | 我 {profile['me']} / 对方 {profile['other']} | "
          f"{profile['days']} 天有记录（跨 {span_days} 天）")
    print(f"日均 {profile['avg_per_day']} 条 | 媒体 {media} 条 | "
          f"时间戳 {len(stamped)}/{len(rows)}")
    print(f"等级: {level}")
    for w in warnings:
        print(f"  [!] {w}")
    if profile["quiet_days"]:
        print(f"  全天无消息: {', '.join(profile['quiet_days'][:8])}"
              + (" ..." if len(profile["quiet_days"]) > 8 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
