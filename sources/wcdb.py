# -*- coding: utf-8 -*-
"""本机读取通道（需要本地 reader 工具包）。

这个文件**不含**密钥提取和解密的实现，只负责把本地 reader 接进流程：
    reader_dir/
        wcdb_key_tool_windows.py   # 取密钥（第三方开源工具，需自行准备）
        full_decrypt.py            # 解密主库 + WAL 合并
        decrypt_wal.py

流程：取密钥（只在临时目录存在几十秒）→ 解密到临时目录 → 导出 → 删除临时目录。
分析层不接触密文，也不接触密钥。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zstandard

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from base import Candidate, MessageSource, SourceError  # noqa: E402

DEFAULT_READER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor")

DATA_ROOTS = [
    os.environ.get("WECHAT_DATA_DIR") or "",
    os.path.join(os.path.expanduser("~"), "Documents", "xwechat_files"),
    os.path.join(os.path.expanduser("~"), "Documents", "WeChat Files"),
    r"D:\微信聊天记录\xwechat_files",
    r"E:\微信聊天记录\xwechat_files",
    r"D:\xwechat_files",
]

ACCOUNT_RE = re.compile(r"^(?P<wxid>.+)_[0-9a-f]{4}$")
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


def find_accounts() -> list[dict]:
    """扫描常见数据目录，返回 [{account_dir, db_storage, self_wxid}]。"""
    out = []
    for root in DATA_ROOTS:
        if not root or not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            db = os.path.join(root, name, "db_storage")
            if not os.path.isdir(db):
                continue
            m = ACCOUNT_RE.match(name)
            out.append({
                "account_dir": os.path.join(root, name),
                "db_storage": db,
                "self_wxid": m.group("wxid") if m else None,
            })
    return out


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


def _account_mtime(acc: dict) -> float:
    """账号活跃度：取 message 目录下所有 db/wal 的最新修改时间。"""
    d = os.path.join(acc["db_storage"], "message")
    latest = 0.0
    try:
        for name in os.listdir(d):
            if ".db" in name:
                latest = max(latest, os.path.getmtime(os.path.join(d, name)))
    except OSError:
        pass
    return latest


class WcdbSource(MessageSource):
    lane = "wcdb"

    def __init__(self, reader_dir: str | None = None, db_storage: str | None = None,
                 self_wxid: str | None = None, asr: str = "off",
                 asr_key: str | None = None, keep_temp: bool = False,
                 wechat_version: str = "n/a", interactive: bool = True,
                 keys_file: str | None = None):
        self.reader_dir = os.path.abspath(
            reader_dir or os.environ.get("WECHAT_READER_DIR") or DEFAULT_READER)
        self.db_storage = db_storage
        self.self_wxid = self_wxid
        self.asr = asr
        self.asr_key = asr_key or os.environ.get("DASHSCOPE_API_KEY")
        self.keep_temp = keep_temp
        self.wechat_version = wechat_version
        self.interactive = interactive
        self.keys_file = os.path.abspath(keys_file) if keys_file else None
        self._tmp: str | None = None
        self._accounts: list[dict] = []

    # ---------- 基础设施 ----------
    def _reader(self, name: str) -> str:
        p = os.path.join(self.reader_dir, name)
        if not os.path.exists(p):
            raise SourceError(
                f"找不到本地 reader：{p}\n"
                f"  这个通道需要 reader 工具包（取密钥 + 解密），请用 --reader-dir 指定，\n"
                f"  或改用 --lane clipboard。"
            )
        return p

    def _account(self) -> dict:
        if self._accounts:
            return self._accounts[0]
        if self.db_storage:
            db = self.db_storage
            name = os.path.basename(os.path.dirname(db.rstrip("\\/")))
            m = ACCOUNT_RE.match(name)
            acc = {"account_dir": os.path.dirname(db.rstrip("\\/")), "db_storage": db,
                   "self_wxid": self.self_wxid or (m.group("wxid") if m else None)}
            self._accounts = [acc]
            return acc
        accounts = find_accounts()
        if not accounts:
            raise SourceError(
                "没有找到微信数据目录。用 --db-dir 指定 <账号目录>\\db_storage，"
                "或设置 WECHAT_DATA_DIR。"
            )
        accounts.sort(key=_account_mtime, reverse=True)
        if len(accounts) > 1:
            print("\n找到多个微信账号目录（按最近使用排序）：")
            for i, a in enumerate(accounts, 1):
                ts = dt.datetime.fromtimestamp(_account_mtime(a)).strftime("%Y-%m-%d %H:%M")
                wxid = a.get("self_wxid") or "?"
                print(f"  {i}. {wxid:32s} {ts}  {a['db_storage']}")
            if not self.interactive:
                raise SourceError("多个账号目录，请用 --db-dir 指定其中一个（或用 --pick 逻辑自行选择）")
            try:
                raw = input(f"选哪个账号（1..{len(accounts)}，默认 1）> ").strip() or "1"
            except (EOFError, KeyboardInterrupt):
                raise SourceError("已取消")
            if not raw.isdigit() or not (1 <= int(raw) <= len(accounts)):
                raise SourceError("输入无效")
            accounts = [accounts[int(raw) - 1]]
        if self.self_wxid:
            accounts[0]["self_wxid"] = self.self_wxid
        self._accounts = accounts
        return accounts[0]

    def _run(self, args: list[str], timeout: int, label: str) -> str:
        print(f"  [{label}] {os.path.basename(args[0])} {' '.join(args[1:3])} …", flush=True)
        p = subprocess.Popen([sys.executable] + args, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace")
        tail: list[str] = []
        try:
            for line in p.stdout:  # 流式打印，长任务才看得见进度
                line = line.rstrip()
                if not line:
                    continue
                tail.append(line)
                tail = tail[-60:]
                print(f"    {line[:200]}", flush=True)
            rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            raise SourceError(f"{label} 超时（{timeout}s）")
        if rc != 0:
            raise SourceError(f"{label} 失败（exit {rc}）：\n" + "\n".join(tail[-15:]))
        return "\n".join(tail)

    def _extract_keys(self) -> str:
        """返回密钥文件路径。优先复用 --keys，其次现场提取。"""
        if self.keys_file:
            if not os.path.exists(self.keys_file):
                raise SourceError(f"密钥文件不存在：{self.keys_file}")
            with open(self.keys_file, encoding="utf-8") as f:
                n = sum(1 for k, v in json.load(f).items()
                        if k != "_db_dir" and v.get("enc_key"))
            print(f"  [keys] 复用已有密钥：{n} 个库（不读微信进程）")
            return self.keys_file
        key_tool = self._reader("wcdb_key_tool_windows.py")
        tmp = self._tmpdir()
        out = os.path.join(tmp, "keys.json")
        self._run([key_tool, "extract", "--db-dir", self._account()["db_storage"],
                   "--output", out], timeout=300, label="取密钥")
        if not os.path.exists(out):
            raise SourceError("取密钥没有产出文件：微信是否已登录并保持运行？")
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        n = sum(1 for k, v in data.items() if k != "_db_dir" and v.get("enc_key"))
        if not n:
            raise SourceError("密钥为空：确认微信已登录、未被其他安全软件拦截")
        print(f"  [ok] 拿到 {n} 个库的密钥（临时文件马上删除）")
        return out

    def _decrypt(self, keys_file: str, rels: list[str], out_dir: str) -> None:
        full = self._reader("full_decrypt.py")
        self._run([full, keys_file, out_dir] + rels, timeout=1800, label="解密")

    def _drop_keys(self, path: str) -> None:
        """只删自己生成的临时密钥；用户 --keys 传进来的不动。"""
        if self.keys_file and os.path.abspath(path) == self.keys_file:
            return
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    def _tmpdir(self) -> str:
        if not self._tmp:
            base = os.environ.get("CHATLOG_TMP") or tempfile.gettempdir()
            # 不用 mkdtemp：它会创建 0700 目录，在部分受限环境下连子目录都写不进去
            d = os.path.join(base, f"chatlog-wcdb-{os.getpid()}")
            os.makedirs(d, exist_ok=True)
            self._tmp = d
        return self._tmp

    def _cleanup(self) -> None:
        if self._tmp and not self.keep_temp:
            shutil.rmtree(self._tmp, ignore_errors=True)
            self._tmp = None

    def close(self) -> None:
        self._cleanup()

    # ---------- 解析会话 ----------
    def resolve(self, query: str) -> list[Candidate]:
        # 先确认 reader 在，报错更可读（复用密钥时不需要取密钥工具）
        self._reader("full_decrypt.py" if self.keys_file else "wcdb_key_tool_windows.py")
        acc = self._account()
        if not acc.get("self_wxid"):
            raise SourceError("无法推断本机微信账号 wxid，请用 --self-wxid 指定")
        self.self_wxid = acc["self_wxid"]
        tmp = self._tmpdir()
        keys = self._extract_keys()
        try:
            self._decrypt(keys, ["contact/contact.db"], os.path.join(tmp, "db"))
        finally:
            self._drop_keys(keys)

        contact_db = os.path.join(tmp, "db", "contact.db")
        con = sqlite3.connect(f"file:{contact_db}?mode=ro&immutable=1", uri=True)
        like = f"%{query}%"
        rows = con.execute(
            "SELECT username, nick_name, remark, alias FROM contact "
            "WHERE remark LIKE ? OR nick_name LIKE ? OR alias LIKE ? OR username LIKE ? "
            "LIMIT 30", (like, like, like, like)
        ).fetchall()
        con.close()

        out = []
        for username, nick, remark, alias in rows:
            label = remark or nick or alias or username
            extra = "（群聊）" if (username or "").endswith("@chatroom") else ""
            out.append(Candidate(
                id=username,
                display=f"{label}  {username} {extra}".strip(),
                extra={"username": username, "nick": nick, "remark": remark,
                       "self_wxid": self.self_wxid, "db_storage": acc["db_storage"]},
            ))
        if not out:
            raise SourceError(f"联系人里没有匹配「{query}」的会话")
        return out

    # ---------- 会话导出 ----------
    def _export_chat(self, db_dir: str, username: str, display: str) -> list[dict]:
        table = "Msg_" + hashlib.md5(username.encode()).hexdigest()
        rows: dict = {}
        uid_count: dict[str, int] = {}
        for db_name in ("message_1.db", "message_0.db"):  # 旧的先读
            path = os.path.join(db_dir, db_name)
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
                    if lt == 34:
                        text = "[语音]"
                    elif lt == 49 and "title" in (text or ""):
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
                    "server_id": sid,
                }
            con.close()

        # 本机 wxid 未知时，用「这个会话里除对方外发言最多的人」推断
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
        return sorted(rows.values(), key=lambda r: (r["ts"], r["text"]))

    # ---------- 拉取消息 ----------
    def fetch(self, cand: Candidate, since: str | None = None, **kw) -> list[dict]:
        username = cand.extra["username"]
        self.self_wxid = cand.extra.get("self_wxid") or self.self_wxid
        if self.self_wxid == username:
            raise SourceError("目标会话是你自己，无法做双人分析")

        db_dir = self._prepare()
        display = cand.extra.get("remark") or cand.extra.get("nick") or username
        msgs = self._export_chat(db_dir, username, display)
        print(f"  [ok] {display}：{len(msgs)} 条"
              f"（{msgs[0]['time']} → {msgs[-1]['time']}）" if msgs else "  [!] 没有消息")

        if self.asr != "off":
            msgs = self._add_voice(msgs, db_dir, username)

        if since:
            msgs = [m for m in msgs if m["time"][:10] >= since]
        for m in msgs:
            m.pop("server_id", None)
        return msgs

    def _prepare(self) -> str:
        """准备可读的 message 目录：取密钥 → 解密到临时目录。"""
        tmp = self._tmpdir()
        keys = self._extract_keys()
        rels = ["message/message_0.db", "message/message_1.db"]
        if self.asr != "off":
            mdir = os.path.join(self._account()["db_storage"], "message")
            try:
                rels += ["message/" + n for n in sorted(os.listdir(mdir))
                         if n.startswith("media_") and n.endswith(".db")]
            except OSError:
                pass
        try:
            self._decrypt(keys, rels, os.path.join(tmp, "db"))
        finally:
            self._drop_keys(keys)
        return os.path.join(tmp, "db")

    # ---------- 语音 ----------
    def _add_voice(self, msgs: list[dict], db_dir: str, username: str) -> list[dict]:
        import glob as _glob
        voices = [m for m in msgs if m["kind"] == "voice"]
        if not voices:
            return msgs
        media_files = sorted(_glob.glob(os.path.join(db_dir, "media_*.db")))
        if not media_files:
            print("  [!] 没有 media_*.db，跳过语音")
            return msgs
        if self.asr == "dashscope" and not self.asr_key:
            print("  [!] 缺少 DASHSCOPE_API_KEY，语音只保留占位")
            return msgs
        try:
            import pysilk  # noqa: F401
        except ImportError:
            print("  [!] 缺少 pysilk，无法解码 silk，语音只保留占位")
            return msgs

        silk_dir = os.path.join(os.path.dirname(db_dir), "silk")
        os.makedirs(silk_dir, exist_ok=True)
        n = 0
        for media in media_files:
            con = sqlite3.connect(f"file:{media}?mode=ro&immutable=1", uri=True)
            try:
                row = con.execute("SELECT rowid FROM Name2Id WHERE user_name=?",
                                  (username,)).fetchone()
                if not row:
                    continue
                for svr_id, blob in con.execute(
                        "SELECT svr_id, voice_data FROM VoiceInfo WHERE chat_name_id=?",
                        (row[0],)):
                    if not blob:
                        continue
                    data = bytes(blob)
                    if data[:1] == b"\\x02" and data[1:9] == b"#!SILK_V":
                        data = data[1:]
                    with open(os.path.join(silk_dir, f"{svr_id}.silk"), "wb") as f:
                        f.write(data)
                    n += 1
            except Exception as e:
                print(f"  [!] {os.path.basename(media)}: {type(e).__name__}: {e}")
            finally:
                con.close()
        if not n:
            print("  [!] 本地没有可用的语音数据")
            return msgs
        print(f"  [ok] 导出 {n} 条语音（{len(media_files)} 个 media 库），开始转写（{self.asr}）…")

        texts = self._transcribe(silk_dir)
        hit = 0
        for m in msgs:
            if m["kind"] == "voice":
                t = texts.get(str(m.get("server_id") or ""))
                if t:
                    m["text"] = t
                    hit += 1
        print(f"  [ok] 语音转写命中 {hit}/{len(voices)}")
        return msgs

    def _transcribe(self, silk_dir: str) -> dict:
        import glob
        import io
        import tempfile
        import threading
        import wave
        from concurrent.futures import ThreadPoolExecutor

        import pysilk
        import dashscope
        from dashscope.audio.asr import Recognition

        dashscope.api_key = self.asr_key
        files = sorted(glob.glob(os.path.join(silk_dir, "*.silk")))
        out: dict[str, str] = {}
        lock = threading.Lock()
        missing = []

        def one(path):
            sid = os.path.splitext(os.path.basename(path))[0]
            tmp_pcm = tempfile.NamedTemporaryFile(suffix=".pcm", delete=False,
                                                    dir=self._tmpdir())
            tmp_pcm.close()
            wav = tmp_pcm.name + ".wav"
            try:
                with open(path, "rb") as fi, open(tmp_pcm.name, "wb") as fo:
                    pysilk.decode(fi, fo, 24000)
                pcm = open(tmp_pcm.name, "rb").read()
                if len(pcm) < 2000:
                    return sid, ""
                with wave.open(wav, "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(24000)
                    w.writeframes(pcm)
                rec = Recognition(model="paraformer-realtime-v2", format="wav",
                                  sample_rate=24000, language_hints=["zh", "en"],
                                  callback=None)
                res = rec.call(wav)
                sents = res.get_sentence() or []
                return sid, "".join(s.get("text", "") for s in sents if isinstance(s, dict))
            except Exception as e:
                missing.append(f"{sid}: {type(e).__name__}")
                return sid, ""
            finally:
                for p in (tmp_pcm.name, wav):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

        done = 0
        with ThreadPoolExecutor(max_workers=8) as ex:
            for sid, text in ex.map(one, files):
                done += 1
                if text:
                    with lock:
                        out[sid] = text
                if done % 200 == 0:
                    print(f"    …{done}/{len(files)}")
        if missing:
            print(f"    [!] {len(missing)} 条转写失败（示例 {missing[:3]}）")
        return out


class SnapshotSource(WcdbSource):
    """离线快照：直接用已经解密的目录（含 contact/、message/），不取密钥、不解密。

    适合：之前导出过一份明文库，想直接分析；或者微信没开、只想看历史。
    """

    lane = "snapshot"

    def __init__(self, snapshot_dir: str, self_wxid: str | None = None,
                 asr: str = "off", asr_key: str | None = None):
        if not os.path.isdir(snapshot_dir):
            raise SourceError(f"快照目录不存在：{snapshot_dir}")
        super().__init__(db_storage=None, self_wxid=self_wxid, asr=asr, asr_key=asr_key)
        self.snapshot_dir = os.path.abspath(snapshot_dir)
        m = ACCOUNT_RE.match(os.path.basename(self.snapshot_dir.rstrip("\\/")))
        self.self_wxid = self_wxid or (m.group("wxid") if m else None)

    def _prepare(self) -> str:
        return os.path.join(self.snapshot_dir, "message")

    def close(self) -> None:
        pass  # 不删用户的目录

    def resolve(self, query: str) -> list[Candidate]:
        contact_db = os.path.join(self.snapshot_dir, "contact", "contact.db")
        if not os.path.exists(contact_db):
            raise SourceError(f"快照里没有 contact/contact.db：{self.snapshot_dir}")
        con = sqlite3.connect(f"file:{contact_db}?mode=ro&immutable=1", uri=True)
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
                                        "remark": remark, "self_wxid": self.self_wxid}))
        if not out:
            raise SourceError(f"联系人里没有匹配「{query}」的会话")
        return out
