# -*- coding: utf-8 -*-
"""确定性指标：会话切分、主动发起、回复速度、活跃时段、连发、沉默。

数字只从这里出，模型不许自己编。
用法：python stats.py work/chat.jsonl --out work/stats.json [--gap 1800]
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (date_of, dump_json, load_jsonl, mean, median, pct,  # noqa: E402
                    week_start)

WHO = ("me", "other")



def _rhythm(by_day):
    """最忙的一天：按时间排的消息条，供网页画节奏条。"""
    if not by_day:
        return None
    day, msgs = max(by_day.items(), key=lambda kv: len(kv[1]))
    events = []
    for r in msgs:
        t = r.get("time") or ""
        try:
            hh, mm = int(t[11:13]), int(t[14:16])
        except (ValueError, IndexError):
            continue
        events.append({"m": hh * 60 + mm, "s": r["sender"],
                       "n": min(len(r.get("text") or ""), 80), "k": r.get("kind")})
    return {"date": day, "count": len(msgs), "events": events}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("chat")
    ap.add_argument("--out", default="work/stats.json")
    ap.add_argument("--gap", type=int, default=1800, help="会话切分阈值（秒），默认 30 分钟")
    args = ap.parse_args()

    rows = [r for r in load_jsonl(args.chat) if r.get("ts")]
    if not rows:
        print("[error] 没有带时间戳的消息，先处理时间格式")
        return 2

    senders = {}
    for s in WHO:
        msgs = [r for r in rows if r["sender"] == s]
        texts = [r for r in msgs if r["kind"] == "text"]
        senders[s] = {
            "msgs": len(msgs),
            "text": len(texts),
            "voice": sum(1 for r in msgs if r["kind"] == "voice"),
            "image": sum(1 for r in msgs if r["kind"] == "image"),
            "sticker": sum(1 for r in msgs if r["kind"] == "sticker"),
            "chars": sum(len(r["text"]) for r in texts),
            "avg_len": round(mean([len(r["text"]) for r in texts]), 1) if texts else 0,
            "max_len": max((len(r["text"]) for r in texts), default=0),
        }

    # ---------- 会话切分 ----------
    sessions = []
    cur = None
    for r in rows:
        if cur is None or r["ts"] - cur["end"] > args.gap:
            cur = {"start": r["ts"], "end": r["ts"], "msgs": [],
                   "initiator": r["sender"], "enders": []}
            sessions.append(cur)
        cur["end"] = r["ts"]
        cur["msgs"].append(r)
        cur["ender"] = r["sender"]

    init_total = Counter(s["initiator"] for s in sessions)
    end_total = Counter(s["ender"] for s in sessions)
    init_week = defaultdict(Counter)
    for s in sessions:
        init_week[week_start(dt.datetime.fromtimestamp(s["start"]))][s["initiator"]] += 1

    # ---------- 回复速度（会话内换手） ----------
    lat = {s: [] for s in WHO}
    lat_week = defaultdict(lambda: {s: [] for s in WHO})
    for s in sessions:
        prev = None
        for r in s["msgs"]:
            if prev is not None and r["sender"] != prev["sender"]:
                gap = r["ts"] - prev["ts"]
                if 0 < gap <= args.gap:
                    lat[r["sender"]].append(gap)
                    lat_week[week_start(dt.datetime.fromtimestamp(r["ts"]))][r["sender"]].append(gap)
            prev = r

    def lat_summary(xs):
        if not xs:
            return {"n": 0}
        return {"n": len(xs), "median": round(median(xs), 1), "mean": round(mean(xs), 1),
                "p10": round(pct(xs, 0.1), 1), "p90": round(pct(xs, 0.9), 1),
                "under_5min": round(sum(1 for x in xs if x <= 300) / len(xs), 3)}

    # ---------- 活跃时段 ----------
    hours = {s: Counter() for s in WHO}
    for r in rows:
        hours[r["sender"]][dt.datetime.fromtimestamp(r["ts"]).hour] += 1

    # ---------- 连发 / 单方独白 ----------
    streaks = {s: [] for s in WHO}
    run_sender, run_len = None, 0
    for r in rows:
        if r["sender"] == run_sender:
            run_len += 1
        else:
            if run_sender in streaks and run_len:
                streaks[run_sender].append(run_len)
            run_sender, run_len = r["sender"], 1
    if run_sender in streaks and run_len:
        streaks[run_sender].append(run_len)

    # ---------- 每天谁先开口 ----------
    by_day = defaultdict(list)
    for r in rows:
        by_day[date_of(r["ts"])].append(r)
    openers = Counter(v[0]["sender"] for v in by_day.values())

    # ---------- 最长沉默 ----------
    silences = []
    for a, b in zip(rows, rows[1:]):
        gap = b["ts"] - a["ts"]
        if gap >= 6 * 3600:
            silences.append({"from": a["time"], "to": b["time"], "hours": round(gap / 3600, 1),
                             "after": a["sender"], "resumed_by": b["sender"]})
    silences.sort(key=lambda x: -x["hours"])

    stats = {
        "meta": {
            "total": len(rows),
            "first": rows[0]["time"], "last": rows[-1]["time"],
            "days": len(by_day),
            "session_gap_sec": args.gap,
        },
        "senders": senders,
        "days": {d: {"me": sum(1 for r in v if r["sender"] == "me"),
                     "other": sum(1 for r in v if r["sender"] == "other")}
                 for d, v in sorted(by_day.items())},
        "sessions": {
            "count": len(sessions),
            "initiator": dict(init_total),
            "initiator_by_week": {w: dict(c) for w, c in sorted(init_week.items())},
            "ender": dict(end_total),
            "avg_msgs": round(mean([len(s["msgs"]) for s in sessions]), 1),
            "median_msgs": median([len(s["msgs"]) for s in sessions]),
        },
        "latency": {s: lat_summary(lat[s]) for s in WHO},
        "latency_by_week": {
            w: {s: (round(median(v), 1) if v else None) for s, v in d.items()}
            for w, d in sorted(lat_week.items())
        },
        "active_hours": {s: {str(h): hours[s].get(h, 0) for h in range(24)} for s in WHO},
        "peak_hours": {s: sorted(hours[s].items(), key=lambda x: -x[1])[:3] for s in WHO},
        "streaks": {
            s: {"max": max(streaks[s], default=0),
                "mean": round(mean(streaks[s]), 2) if streaks[s] else 0,
                "double_text": sum(1 for n in streaks[s] if n >= 3)}
            for s in WHO
        },
        "day_openers": dict(openers),
        "silences": silences[:5],
        "rhythm": _rhythm(by_day),
    }
    dump_json(args.out, stats)

    print(f"会话 {stats['sessions']['count']} 段 | 平均 {stats['sessions']['avg_msgs']} 条/段")
    print(f"发起: 我 {init_total.get('me', 0)} / 对方 {init_total.get('other', 0)} | "
          f"收尾: 我 {end_total.get('me', 0)} / 对方 {end_total.get('other', 0)}")
    for s in WHO:
        L = stats["latency"][s]
        if L["n"]:
            print(f"回复[{s}]: 中位 {L['median']}s / P90 {L['p90']}s / "
                  f"5 分钟内 {L['under_5min']:.0%}（n={L['n']}）")
    print(f"每天先开口: {dict(openers)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
