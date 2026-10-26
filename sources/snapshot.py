# -*- coding: utf-8 -*-
"""离线快照通道：直接读一个已经解密的目录（含 contact/ 和 message/）。

这是本仓库唯一自带的「读本地数据库」通道，前提是**数据已经是明文**。
它不解密、不取密钥、不碰任何进程——如果你还没有明文库，先自己解决那一步，
或者改用剪贴板通道。

目录结构（微信 PC 版导出后的样子）：

    <snapshot>/
        contact/contact.db
        message/message_0.db
        message/message_1.db
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import sqlite3
import zstandard

from base import Candidate, MessageSource, SourceError

ZSTD_MAGIC = bytes([0x28, 0xB5, 0x2F, 0xFD])
DZ = zstandard.ZstdDecompressor()

TYPE_MAP = {
    1: ("text", None),
    3: ("image", "[图片]"),
    34: ("voice", "[语音]"),
    42: ("card", "[名片]"),
    43: ("video", "[视频]"),
    47: ("sticker", "[表情]"),
    48: ("location", "[位置]"),
    49: ("link", "[链接]"),
    50: ("call", "[通话]"),
    10000: ("system", "[系统]"),
}


def _decode(blob, compress_blob=None) -> str:
    for b in (blob, compress_blob):
        if not b:
            continue
        if isinstance(b, str):
            return b
        data = bytes(b)
        if data[:4] == ZSTD_MAGIC:
            try:
                data = DZ.decompress(data, max_output_size=8_000_000)
            except Exception:
                try:
                    data = DZ.stream_reader(data).read()
                except Exception:
                    pass
        try:
            return data.decode("utf-8", "replace")
        except Exception:
            continue
    return ""


def _xml_field(s: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", s, re.S)
    return m.group(1).strip() if m else ""


class SnapshotSource(MessageSource):
    lane = "snapshot"

    def __init__(self, snapshot_dir: str, self_wxid: str | None = None):
        if not snapshot_dir:
            raise SourceError("缺少 --snapshot-dir")
        if not os.path.isdir(snapshot_dir):
            raise SourceError(f"快照目录不存在：{snapshot_dir}")
        self.dir = os.path.abspath(snapshot_dir)
        self.self_wxid = self_wxid

    # ---------- 解析会话 ----------
    def resolve(self, query: str) -> list[Candidate]:
        db = os.path.join(self.dir, "contact", "contact.db")
        if not os.path.exists(db):
            raise SourceError(f"快照里没有 contact/contact.db：{self.dir}")
        con = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
        like = f"%{query}%"
        rows = con.execute(
            "SELECT username, nick_name, remark, alias FROM contact "
            "WHERE remark LIKE ? OR nick_name LIKE ? OR alias LIKE ? OR username LIKE ? "
            "LIMIT 30", (like, like, like, like)).fetchall()
        con.close()
        out = []
        for username, nick, remark, alias in rows:
            label = remark or nick or alias or username
            out.append(Candidate(id=username, display=f"{label}  {username}".strip(),
                                 extra={"username": username, "nick": nick,
                                        "remark": remark}))
        if not out:
            raise SourceError(f"联系人里没有匹配「{query}」的会话")
        return out

    # ---------- 导出消息 ----------
    def fetch(self, cand: Candidate, since: str | None = None, **kw) -> list[dict]:
        username = cand.extra["username"]
        display = cand.extra.get("remark") or cand.extra.get("nick") or username
        table = "Msg_" + hashlib.md5(username.encode()).hexdigest()

        rows: dict = {}
        uid_count: dict[str, int] = {}
        for db_name in ("message_1.db", "message_0.db"):  # 旧的先读
            path = os.path.join(self.dir, "message", db_name)
            if not os.path.exists(path):
                continue
            con = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
            if not con.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
                con.close()
                continue
            n2i = {r[0]: r[1] for r in con.execute("SELECT rowid, user_name FROM Name2Id")}
            cur = con.execute(
                f"SELECT local_id, server_id, local_type, real_sender_id, create_time, "
                f"message_content, compress_content FROM {table} ORDER BY create_time, sort_seq")
            for lid, sid, lt, rs, ct, mc, cc in cur:
                uid = n2i.get(rs, "")
                uid_count[uid] = uid_count.get(uid, 0) + 1
                kind, fixed = TYPE_MAP.get(lt, ("other", f"[type{lt}]"))
                text = _decode(mc, cc)
                if fixed:
                    if lt == 49 and "title" in (text or ""):
                        text = "[链接] " + _xml_field(text, "title")
                    elif lt == 10000:
                        text = re.sub(r"<[^>]+>", "", text)[:80] or "[系统]"
                    else:
                        text = fixed
                rows[sid if sid else (db_name, lid)] = {
                    "ts": ct,
                    "time": dt.datetime.fromtimestamp(ct).strftime("%Y-%m-%d %H:%M:%S"),
                    "uid": uid,
                    "kind": kind,
                    "text": text,
                }
            con.close()

        if not self.self_wxid:
            others = sorted(((c, u) for u, c in uid_count.items() if u and u != username),
                            reverse=True)
            if others:
                self.self_wxid = others[0][1]
                print(f"  [infer] 本机 wxid = {self.self_wxid}")

        for rec in rows.values():
            is_me = bool(self.self_wxid) and rec.pop("uid") == self.self_wxid
            rec["sender"] = "me" if is_me else "other"
            rec["name"] = "我" if is_me else display

        msgs = sorted(rows.values(), key=lambda r: (r["ts"], r["text"]))
        print(f"  [ok] {display}：{len(msgs)} 条"
              f"（{msgs[0]['time']} → {msgs[-1]['time']}）" if msgs else "  [!] 没有消息")
        if since:
            msgs = [m for m in msgs if m["time"][:10] >= since]
        return msgs
