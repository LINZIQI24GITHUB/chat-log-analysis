# -*- coding: utf-8 -*-
"""导入向导：列出聊天窗口 → 你选一个 → 自动分析 + 蒸馏 → 打开模拟器。

前提：有一个**已解密**的微信数据目录（contact/ + message/）。
没有的话先跑一次：
    python scripts/ingest.py --contact 任意名字 --lane wcdb --keep-temp
它会打印解密副本的路径，把那个路径给这个向导。

用法：
    python sim/setup.py                       # 自动找数据目录
    python sim/setup.py --decrypted "D:\\path\\to\\decrypted"
    python sim/setup.py --no-serve            # 只准备数据，不启动服务
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

CANDIDATES = [
    os.environ.get("WECHAT_DECRYPTED") or "",
    os.path.join(os.path.expanduser("~"), "wechat_export", "w661"),
    os.path.join(ROOT, ".cache", "decrypted"),
]


def find_decrypted(explicit: str | None) -> str:
    for d in ([explicit] if explicit else []) + CANDIDATES:
        if d and os.path.isdir(os.path.join(d, "contact")) and os.path.isdir(os.path.join(d, "message")):
            return os.path.abspath(d)
    raise SystemExit(
        "[error] 找不到已解密的数据目录（需要包含 contact/ 和 message/）。\n"
        "        先跑一次：python scripts/ingest.py --contact 任意 --lane wcdb --keep-temp\n"
        "        把它打印的路径用 --decrypted 传进来。"
    )


def load_contacts(d: str) -> dict[str, str]:
    db = os.path.join(d, "contact", "contact.db")
    con = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
    out = {}
    for username, nick, remark in con.execute(
            "SELECT username, nick_name, remark FROM contact"):
        out[username] = (remark or nick or username).strip()
    con.close()
    return out


def list_chats(d: str, limit: int = 20, include_groups: bool = False) -> list[dict]:
    """遍历 message_*.db 的 Msg_* 表，反查联系人名，按最后时间排序。"""
    names = load_contacts(d)
    by_md5 = {hashlib.md5(u.encode()).hexdigest(): u for u in names}

    chats: dict[str, dict] = {}
    for db_name in sorted(os.listdir(os.path.join(d, "message"))):
        if not db_name.endswith(".db"):
            continue
        path = os.path.join(d, "message", db_name)
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
            tables = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
            for t in tables:
                md5 = t[4:]
                user = by_md5.get(md5)
                if not user:
                    continue
                try:
                    cnt, last = con.execute(
                        f"SELECT COUNT(*), MAX(create_time) FROM {t}").fetchone()
                except sqlite3.Error:
                    continue
                if not cnt:
                    continue
                is_group = user.endswith("@chatroom")
                if is_group and not include_groups:
                    continue
                prev = chats.get(user)
                if prev:
                    prev["count"] += cnt
                    prev["last"] = max(prev["last"], last or 0)
                else:
                    chats[user] = {"user": user, "name": names.get(user, user),
                                   "count": cnt, "last": last or 0,
                                   "group": is_group}
            con.close()
        except sqlite3.Error:
            continue

    rows = sorted(chats.values(), key=lambda r: r["last"], reverse=True)
    for r in rows:
        r["when"] = time.strftime("%Y-%m-%d", time.localtime(r["last"])) if r["last"] else "—"
    return rows


def _unused(rows, limit):
    rows = rows[:limit]
    for r in rows:
        r["when"] = time.strftime("%Y-%m-%d", time.localtime(r["last"])) if r["last"] else "—"
    return rows


def run(cmd: list[str], cwd: str = ROOT) -> int:
    print(f"  $ {' '.join(cmd[1:])}")
    p = subprocess.run([sys.executable] + cmd[1:], cwd=cwd)
    return p.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decrypted", default=None, help="已解密的数据目录")
    ap.add_argument("--no-serve", action="store_true", help="只准备数据，不启动模拟")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--groups", action="store_true", help="连群聊一起列出来")
    args = ap.parse_args()

    d = find_decrypted(args.decrypted)
    print(f"\n数据目录：{d}\n")
    print("正在扫描会话（有几万个联系人的话要十几秒）…")
    all_chats = list_chats(d, 10**9, include_groups=args.groups)
    if not all_chats:
        print("[error] 没扫到任何会话")
        return 2
    chats = all_chats[:args.limit]

    print(f"\n最近 {len(chats)} 个窗口（共扫到 {len(all_chats)} 个，"
          f"数据截至 {all_chats[0]['when']}）：\n")
    for i, c in enumerate(chats, 1):
        tag = "群" if c.get("group") else "  "
        print(f"  {i:>2}. {tag} {c['name']:<18} {c['count']:>6} 条   最后 {c['when']}")
    print("\n（只列一对一私聊；群聊加 --groups 也会列出来，但分析只支持私聊）")

    print("\n输入编号，或直接输入名字搜索（回车取消）：", end="")
    raw = input().strip()
    if not raw:
        print("已取消")
        return 0

    if raw.isdigit():
        try:
            pick = chats[int(raw) - 1]
        except IndexError:
            print("[error] 编号超出范围")
            return 2
    else:
        hits = [c for c in all_chats if raw.lower() in c["name"].lower()]
        if not hits:
            print(f"[error] 没有名字包含「{raw}」的会话")
            return 2
        if len(hits) > 1:
            print("\n匹配到多个：")
            for i, c in enumerate(hits, 1):
                print(f"  {i}. {c['name']}  {c['count']} 条  最后 {c['when']}")
            print("输入编号：", end="")
            try:
                pick = hits[int(input().strip()) - 1]
            except (ValueError, IndexError):
                print("[error] 编号不对")
                return 2
        else:
            pick = hits[0]
            print(f"选中：{pick['name']}（{pick['count']} 条，最后 {pick['when']}）")

    if pick.get("group"):
        print("[error] 这是群聊，分析只支持一对一。换一个。")
        return 2
    name = pick["name"]
    work = os.path.join(ROOT, "work")
    os.makedirs(work, exist_ok=True)
    chat = os.path.join(work, "chat.jsonl")

    print(f"\n[1/3] 导出「{name}」的聊天记录…")
    if run(["python", "scripts/ingest.py", "--contact", name, "--lane", "snapshot",
            "--snapshot-dir", d, "--yes", "--i-am-party",
            "--state-dir", os.path.join(ROOT, ".cache", "state"),
            "--out", chat]) != 0:
        return 3

    print("\n[2/3] 统计 + 体检 + 分片…")
    if run(["python", "scripts/run_all.py", chat, "--self", "我", "--other", name,
            "--out", work]) != 0:
        return 4

    print("\n[3/3] 蒸馏说话档案…")
    persona = os.path.join(ROOT, "persona.json")
    if run(["python", "scripts/persona.py", chat,
            "--stats", os.path.join(work, "stats.json"),
            "--name", name, "--out", persona]) != 0:
        return 5

    pj = json.load(open(persona, encoding="utf-8"))
    st = pj["style"]
    print(f"\n完成：{pj['name']}")
    print(f"  平均 {st['avg_len']} 字 | 表情 {st['sticker_rate']:.0%} | "
          f"回复中位 {pj['timing'].get('p50_sec', '—')} 秒 | "
          f"回复率 {pj['timing'].get('reply_rate', 0):.0%}")
    print(f"  档案：{persona}")
    print(f"  分析产物：{work}\\stats.json / profile.json / shards\\")

    if args.no_serve:
        print("\n（--no-serve）没启动模拟器。要开的话：python sim/sim.py --persona persona.json")
        return 0

    print("\n启动模拟器…（Ctrl+C 结束）")
    port = os.environ.get("SIM_PORT", "8777")
    try:
        subprocess.Popen([sys.executable, os.path.join(ROOT, "sim", "sim.py"),
                          "--persona", persona, "--port", port])
        time.sleep(1.5)
        os.startfile(f"http://127.0.0.1:{port}")
        print(f"  浏览器已打开 http://127.0.0.1:{port}")
        print("  点右上角齿轮填 API Key 就能开始聊")
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
