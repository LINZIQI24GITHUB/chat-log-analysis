# -*- coding: utf-8 -*-
"""发布前干净度检查：确保仓库里没有任何人的聊天记录、分析结果或密钥。

用法：
    python tools/verify_clean.py            # 检查当前仓库
    python tools/verify_clean.py --path .   # 指定目录

CI 里也会跑这个。任何一条命中都会 exit 1。
"""
from __future__ import annotations

import argparse
import os
import re
import sys

# 这些文件名说明是运行产物，不该出现在仓库里
BAD_NAMES = {
    "chat.jsonl", "digest.txt", "stats.json", "keywords.json", "profile.json",
    "ingest_meta.json", "consent.json", "all_keys.json",
}

# 目录名：work/ 和 work-xxx/ 都是产物
BAD_DIRS = re.compile(r"^(work|work-.*|_smoke|_test_run|\.taste-skill)$")

# 内容特征：只匹配「真的值」，不匹配变量名或文档里的说明
BAD_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "疑似 API Key 明文"),
    (re.compile(r"dashscope_api_key\W{0,4}sk-", re.I), "疑似 API Key 配置文件"),
    (re.compile(r'"enc_key"\s*:\s*"[0-9a-f]{32,}"'), "疑似数据库密钥"),
    (re.compile(r"wxid_[0-9a-z]{8,}"), "微信 wxid"),
    (re.compile(r"\d{6,}@chatroom"), "微信群 ID"),
    (re.compile(r"Msg_[0-9a-f]{32}"), "消息表名（真实会话）"),
    (re.compile(r"C:\\Users\\"), "本机绝对路径"),
    (re.compile(r"/home/[A-Za-z]"), "本机绝对路径"),
]

# 检查器自己会包含这些模式，跳过
SKIP_FILES = {"verify_clean.py"}

SKIP_DIRS = {".git", "__pycache__", "docs", "node_modules"}
TEXT_EXT = {".py", ".md", ".txt", ".json", ".yml", ".yaml", ".toml", ".cmd", ".sh"}


def scan(root: str) -> list[str]:
    problems: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        parts = [] if rel_dir == "." else rel_dir.split(os.sep)
        if any(p in SKIP_DIRS for p in parts):
            dirnames[:] = []
            continue
        for d in list(dirnames):
            if BAD_DIRS.match(d):
                problems.append(f"[目录] 运行产物不该入库：{os.path.join(rel_dir, d)}")
                dirnames.remove(d)

        for name in filenames:
            rel = os.path.join(rel_dir, name) if rel_dir != "." else name
            if name in SKIP_FILES:
                continue
            if name in BAD_NAMES:
                problems.append(f"[文件] 运行产物不该入库：{rel}")
            if name.endswith((".log",)) or name.startswith(".tmp-"):
                problems.append(f"[文件] 临时文件不该入库：{rel}")
            ext = os.path.splitext(name)[1].lower()
            if ext not in TEXT_EXT:
                continue
            path = os.path.join(dirpath, name)
            try:
                text = open(path, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            for rx, label in BAD_PATTERNS:
                m = rx.search(text)
                if m:
                    line = text[:m.start()].count("\n") + 1
                    problems.append(f"[内容] {label}：{rel}:{line}  {m.group(0)[:40]}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=".")
    args = ap.parse_args()
    root = os.path.abspath(args.path)
    problems = scan(root)
    if problems:
        print(f"发现 {len(problems)} 处不该发布的内容：\n")
        for p in problems:
            print("  " + p)
        print("\n[FAIL] 修掉之后重跑。")
        return 1
    print("[OK] 干净：没有运行产物、密钥、wxid 或本机路径。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
