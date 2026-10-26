# -*- coding: utf-8 -*-
"""读取前的资格确认与用途告知。

这不是「对方同意书」——个人事务范围内的分析不需要对方签字。
这里确认的是两件事：
  1. 使用者本人是这段对话的当事人之一（否则不属于个人事务）
  2. 使用者知道数据里包含对方的信息、结果仅供本人参考

记录写本地，不进网络。微信大版本变化时重新确认一次。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

TOOL_VERSION = "0.1.0"

BANNER = """
┌──────────────────────────────────────────────────────────────┐
│  即将读取本机微信数据                                        │
│                                                              │
│  会做：                                                      │
│    · 从正在运行的微信进程读取数据库密钥                       │
│    · 解密本机数据库，只取你指定的那一个会话                   │
│  不会：                                                      │
│    · 上传任何聊天内容到服务器                                 │
│    · 修改或删除微信数据                                       │
│    · 读取你没有指定的会话                                     │
│                                                              │
│  这段记录包含对方的信息。请勿公开传播，或用于对对方不利的用途。│
│                                                              │
│  确认后输入「我已了解」继续（回车取消）：                     │
└──────────────────────────────────────────────────────────────┘
"""


def state_dir(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    env = os.environ.get("CHATLOG_STATE_DIR")
    if env:
        return env
    return os.path.join(os.path.expanduser("~"), ".chat-log-analysis")


def consent_path(dirpath: str | None = None) -> str:
    return os.path.join(state_dir(dirpath), "consent.json")


def load(dirpath: str | None = None) -> dict:
    p = consent_path(dirpath)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def record(lane: str, wechat_version: str, dirpath: str | None = None,
           note: str = "互动确认") -> dict:
    d = state_dir(dirpath)
    os.makedirs(d, exist_ok=True)
    data = load(dirpath)
    data[lane] = {
        "accepted_at": dt.datetime.now().isoformat(timespec="seconds"),
        "wechat_version": wechat_version or "n/a",
        "tool_version": TOOL_VERSION,
        "attestation": "party_to_conversation",
        "note": note,
    }
    with open(consent_path(dirpath), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return data[lane]


def has_consent(lane: str, wechat_version: str, dirpath: str | None = None) -> bool:
    rec = load(dirpath).get(lane)
    if not rec:
        return False
    # 微信大版本变了，重新确认一次（新的读取方式可能不同）
    old = (rec.get("wechat_version") or "").split(".")
    new = (wechat_version or "").split(".")
    if old[:2] != new[:2]:
        return False
    return rec.get("attestation") == "party_to_conversation"


def ensure(lane: str, wechat_version: str = "n/a", dirpath: str | None = None,
           accept: bool = False, i_am_party: bool = False) -> bool:
    """返回 True 表示可以继续。"""
    if has_consent(lane, wechat_version, dirpath):
        return True

    if accept:
        if not i_am_party:
            print("[error] --yes 必须同时带 --i-am-party（确认你是对话当事人之一）",
                  file=sys.stderr)
            return False
        record(lane, wechat_version, dirpath, note="非交互确认（--yes --i-am-party）")
        print(f"[consent] 已记录：{consent_path(dirpath)}")
        return True

    print(BANNER)
    if not sys.stdin.isatty():
        print("[error] 当前不是交互终端。请手动运行一次，或使用 --yes --i-am-party。",
              file=sys.stderr)
        return False
    try:
        answer = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if answer != "我已了解":
        print("[cancel] 未确认，已退出。")
        return False
    rec = record(lane, wechat_version, dirpath)
    print(f"[consent] 已记录：{rec['accepted_at']}  lane={lane}  "
          f"wechat={rec['wechat_version']}")
    return True


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--lane", default="wcdb")
    ap.add_argument("--wechat-version", default="n/a")
    ap.add_argument("--state-dir", default=None)
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()
    if args.show:
        print(json.dumps(load(args.state_dir), ensure_ascii=False, indent=1))
        return 0
    return 0 if ensure(args.lane, args.wechat_version, args.state_dir) else 1


if __name__ == "__main__":
    raise SystemExit(main())
