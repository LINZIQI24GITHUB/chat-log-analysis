# -*- coding: utf-8 -*-
"""公共工具：时间、统计、路径。只用标准库。"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

FMT_DATE = "%Y-%m-%d"


def eprint(*a):
    print(*a, file=sys.stderr)


def parse_time(s: str) -> dt.datetime:
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"无法解析时间: {s!r}")


def load_jsonl(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                eprint(f"[warn] 第 {i} 行不是合法 JSON，已跳过: {e}")
    rows.sort(key=lambda r: r["ts"])
    return rows


def dump_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    n = len(xs)
    mid = n // 2
    return float(xs[mid]) if n % 2 else (xs[mid - 1] + xs[mid]) / 2


def pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    idx = min(len(xs) - 1, max(0, int(round((len(xs) - 1) * q))))
    return float(xs[idx])


def mean(xs: list[float]) -> float:
    return float(sum(xs)) / len(xs) if xs else 0.0


def week_start(d: dt.datetime) -> str:
    """返回该周周一的日期字符串。"""
    return (d - dt.timedelta(days=d.weekday())).strftime(FMT_DATE)


def fmt_gap(sec: float) -> str:
    """秒数转人类可读。"""
    sec = int(round(sec))
    if sec < 60:
        return f"{sec} 秒"
    if sec < 3600:
        return f"{sec / 60:.0f} 分钟"
    if sec < 86400:
        return f"{sec / 3600:.1f} 小时"
    return f"{sec / 86400:.1f} 天"


def hhmm(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%H:%M")


def date_of(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime(FMT_DATE)
