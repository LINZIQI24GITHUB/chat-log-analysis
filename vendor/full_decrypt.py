# -*- coding: utf-8 -*-
"""完整解密: db + WAL 合并, 输出单一明文 sqlite db"""
import json
import os
import shutil
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wcdb_key_tool_windows import _decrypt_database
from decrypt_wal import decrypt_wal

HERE = os.path.dirname(os.path.abspath(__file__))

def full_decrypt(keys_file, rel, out_dir):
    with open(keys_file, encoding="utf-8") as f:
        keys = json.load(f)
    db_dir = keys["_db_dir"]
    key_info = None
    for k, v in keys.items():
        if k.replace("\\", "/") == rel.replace("\\", "/"):
            key_info = v
            break
    if not key_info:
        print(f"NO KEY: {rel}")
        return
    enc_key = bytes.fromhex(key_info["enc_key"])
    src_db = os.path.join(db_dir, rel.replace("/", os.sep))
    src_wal = src_db + "-wal"

    os.makedirs(out_dir, exist_ok=True)
    out_db = os.path.join(out_dir, os.path.basename(rel))

    # 在临时副本上操作, 不碰原文件
    tmp_db = out_db + ".enccopy"
    shutil.copyfile(src_db, tmp_db)
    if os.path.exists(src_wal) and os.path.getsize(src_wal) > 32:
        shutil.copyfile(src_wal, tmp_db + "-wal")

    # 1. 解密主库
    ok = _decrypt_database(tmp_db, out_db, enc_key)
    print(("OK  " if ok else "FAIL") + " db: " + rel)
    if not ok:
        return

    # 2. 解密 WAL
    if os.path.exists(tmp_db + "-wal"):
        n = decrypt_wal(tmp_db + "-wal", out_db + "-wal", enc_key)
        print(f"  wal frames: {n}")

    # 3. sqlite3 打开回放 WAL 并 checkpoint 合并
    conn = sqlite3.connect(out_db)
    try:
        cnt = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        rows = 0
        for (tb,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"):
            rows += conn.execute(f"SELECT COUNT(*) FROM {tb}").fetchone()[0]
        print(f"  replay ok: {cnt} tables, Msg rows total = {rows}")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA journal_mode=DELETE")
    finally:
        conn.close()
    for suf in (".enccopy", ".enccopy-wal", "-wal", "-shm"):
        p = out_db + suf
        if os.path.exists(p):
            os.remove(p)
    print(f"  merged -> {out_db} ({os.path.getsize(out_db)/1024/1024:.1f}MB)")

if __name__ == "__main__":
    keys_file = sys.argv[1]
    out_dir = sys.argv[2]
    for rel in sys.argv[3:]:
        full_decrypt(keys_file, rel, out_dir)
