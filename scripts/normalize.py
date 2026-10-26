# -*- coding: utf-8 -*-
"""把各种导出/粘贴进来的聊天文本，归一成 chat.jsonl。

支持：
  1) 微信 PC 多选复制：  "陈屿 2026-09-18 22:41" + 下一行内容
  2) 微信移动端复制：    "陈屿: 内容" / "陈屿 2026-09-18 22:41: 内容"
  3) WhatsApp：          "[2026/09/18, 22:41:03] 陈屿: 内容"
  4) JSONL：             已是 {"ts"/"time","sender","text"}

用法：
  python normalize.py examples/sample_chat.txt --self 我 --out work/chat.jsonl
  python normalize.py chat.txt --self 我 --other 陈屿 --format wechat
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import eprint, parse_time  # noqa: E402

HEADER = re.compile(
    r"^(?P<name>.+?)\s+(?P<d>\d{4}[-/.]\d{1,2}[-/.]\d{1,2})\s+(?P<t>\d{1,2}:\d{2}(?::\d{2})?)\s*:?\s*$"
)
INLINE = re.compile(
    r"^(?P<name>[^:：]{1,40}?)\s+(?P<d>\d{4}[-/.]\d{1,2}[-/.]\d{1,2})\s+(?P<t>\d{1,2}:\d{2}(?::\d{2})?)\s*[:：]\s*(?P<text>.*)$"
)
SIMPLE = re.compile(r"^(?P<name>[^:：]{1,40}?)\s*[:：]\s*(?P<text>.+)$")
WHATSAPP = re.compile(
    r"^\[(?P<d>\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}),?\s+(?P<t>\d{1,2}:\d{2}(?::\d{2})?)\]\s*(?P<name>[^:：]{1,40})\s*[:：]\s*(?P<text>.*)$"
)

MEDIA = {
    "[图片]": "image", "[照片]": "image", "[语音]": "voice", "[视频]": "video",
    "[表情]": "sticker", "[动画表情]": "sticker", "[文件]": "file",
    "[位置]": "location", "[链接]": "link", "[转账]": "transfer", "[红包]": "redpacket",
    "[名片]": "contact", "[聊天记录]": "forward",
}


def classify(text: str) -> str:
    t = text.strip()
    if t in MEDIA:
        return MEDIA[t]
    if len(t) <= 12 and t.startswith("[") and t.endswith("]"):
        return "media_other"
    return "text"


def clean(text: str) -> str:
    return text.replace("\u200b", "").replace("\ufeff", "").strip()


def build(name: str, when: str | None, text: str, self_name: str, other_name: str | None) -> dict:
    text = clean(text)
    time_str = None
    ts = None
    if when:
        d = parse_time(when)
        ts = d.timestamp()
        time_str = d.strftime("%Y-%m-%d %H:%M:%S")
    if name == self_name:
        sender, display = "me", self_name
    elif other_name and name == other_name:
        sender, display = "other", other_name
    else:
        sender, display = "other", name
    return {"ts": ts, "time": time_str, "sender": sender, "name": display,
            "kind": classify(text), "text": text}


def parse_wechat_block(text: str, self_name: str, other_name: str | None) -> list[dict]:
    """处理「头部行 + 若干内容行」的粘贴格式。"""
    rows, cur = [], None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            if cur:
                cur["_body"].append("")
            continue
        m = HEADER.match(line)
        if m:
            if cur:
                rows.append(cur)
            when = f"{m.group('d').replace('/', '-').replace('.', '-')} {m.group('t')}"
            cur = {"name": m.group("name").strip(), "when": when, "_body": []}
        elif cur:
            cur["_body"].append(line)
        else:
            eprint(f"[warn] 首个头部之前的内容被忽略: {line[:40]!r}")
    if cur:
        rows.append(cur)

    out = []
    for r in rows:
        body = "\n".join(r["_body"]).strip()
        if not body:
            continue
        out.append(build(r["name"], r["when"], body, self_name, other_name))
    return out


def parse_inline(text: str, self_name: str, other_name: str | None) -> list[dict]:
    """处理「名字: 内容」逐行格式。"""
    out, pending_date = [], None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m = INLINE.match(line)
        if m:
            when = f"{m.group('d').replace('/', '-').replace('.', '-')} {m.group('t')}"
            out.append(build(m.group("name"), when, m.group("text"), self_name, other_name))
            continue
        m = WHATSAPP.match(line)
        if m:
            d = m.group("d").replace("/", "-").replace(".", "-")
            parts = d.split("-")
            if len(parts[0]) == 4:
                when = f"{d} {m.group('t')}"
            else:  # dd-mm-yyyy
                when = f"{parts[2]}-{parts[1]}-{parts[0]} {m.group('t')}"
            out.append(build(m.group("name"), when, m.group("text"), self_name, other_name))
            continue
        m = SIMPLE.match(line)
        if m and len(m.group("name")) <= 20:
            name = m.group("name").strip()
            if name == self_name or (other_name and name == other_name):
                out.append(build(name, None, m.group("text"), self_name, other_name))
                continue
        # 无名字的续行：接到上一条
        if out:
            out[-1]["text"] = (out[-1]["text"] + "\n" + line).strip()
            out[-1]["kind"] = classify(out[-1]["text"])
        else:
            eprint(f"[warn] 无法归属的行被忽略: {line[:40]!r}")
    return out


def parse_jsonl(path: str, self_name: str, other_name: str | None) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if "ts" in r and r["ts"]:
                d = None
                ts = float(r["ts"])
            else:
                d = parse_time(r["time"])
                ts = d.timestamp()
            sender = r.get("sender") or r.get("who") or r.get("name") or ""
            if sender in (self_name, "me", "我"):
                s = "me"
            elif other_name and sender == other_name:
                s = "other"
            else:
                s = "other"
            out.append({
                "ts": ts,
                "time": r.get("time") or (d.strftime("%Y-%m-%d %H:%M:%S") if d else None),
                "sender": s,
                "name": r.get("name") or sender,
                "kind": r.get("kind") or classify(r.get("text") or ""),
                "text": r.get("text") or r.get("content") or "",
            })
    return out


def detect_format(path: str, text: str) -> str:
    if path.endswith(".jsonl"):
        return "jsonl"
    heads = sum(1 for line in text.splitlines() if HEADER.match(line.rstrip()))
    inlines = sum(1 for line in text.splitlines() if SIMPLE.match(line.rstrip()))
    if heads >= 2 and heads >= inlines:
        return "wechat"
    return "inline"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--self", default="我", dest="self_name")
    ap.add_argument("--other", default=None, dest="other_name")
    ap.add_argument("--format", default="auto", choices=["auto", "wechat", "inline", "jsonl"])
    ap.add_argument("--out", default="work/chat.jsonl")
    ap.add_argument("--preview", type=int, default=12)
    args = ap.parse_args()

    with open(args.input, encoding="utf-8-sig") as f:
        text = f.read()

    fmt = detect_format(args.input, text) if args.format == "auto" else args.format
    if fmt == "jsonl":
        rows = parse_jsonl(args.input, args.self_name, args.other_name)
    elif fmt == "wechat":
        rows = parse_wechat_block(text, args.self_name, args.other_name)
    else:
        rows = parse_inline(text, args.self_name, args.other_name)

    rows = [r for r in rows if r["text"]]
    if not rows:
        eprint("[error] 一条消息都没解析出来，检查 --format / --self 参数")
        return 2

    # 没时间戳的（无日期复制），用当天日期补不了，就标记 unknown
    for r in rows:
        if r["ts"] is None:
            r["ts"] = 0.0
    rows.sort(key=lambda r: (r["ts"], r["text"]))

    names = {}
    for r in rows:
        names[r["name"]] = names.get(r["name"], 0) + 1
    if len(names) > 2 and not args.other_name:
        eprint(f"[warn] 识别到 {len(names)} 个发言人，可能是群聊；本版只做 1:1 分析，"
               f"请用 --other 指定对方。发言分布: {names}")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    me = sum(1 for r in rows if r["sender"] == "me")
    other = len(rows) - me
    with_time = sum(1 for r in rows if r["ts"] > 0)
    print(f"解析完成 -> {args.out}")
    print(f"  格式: {fmt} | 消息 {len(rows)} 条（我 {me} / 对方 {other}）"
          f" | 时间戳 {with_time} 条")
    print(f"  时间范围: {rows[0]['time'] or '?'} -> {rows[-1]['time'] or '?'}")
    print(f"  发言人: {names}")
    print("\n--- 预览（确认解析对不对）---")
    for r in rows[: args.preview]:
        who = "我" if r["sender"] == "me" else r["name"]
        print(f"  {r['time'] or '(无时间)'} {who}: {r['text'][:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
