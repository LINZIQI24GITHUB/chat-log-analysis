# -*- coding: utf-8 -*-
"""剪贴板采集：用户复制，脚本收。

最稳的一条路——文本 100% 准确、带时间戳、不碰任何进程内存。
代价是需要用户点几下，所以默认放在兜底位置。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from base import Candidate, MessageSource, SourceError  # noqa: E402
import normalize  # noqa: E402


def read_clipboard() -> str:
    try:
        import win32clipboard
    except ImportError as e:
        raise SourceError("缺少 pywin32，无法读剪贴板：pip install pywin32") from e
    try:
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT) or ""
            return ""
        finally:
            win32clipboard.CloseClipboard()
    except Exception as e:
        raise SourceError(f"读剪贴板失败：{e}") from e


def parse_text(text: str, self_name: str, other_name: str | None) -> list[dict]:
    """复用 normalize 的解析器，兼容「名字+时间」和「名字: 内容」两种复制格式。"""
    fmt = normalize.detect_format("", text)
    if fmt == "wechat":
        return normalize.parse_wechat_block(text, self_name, other_name)
    return normalize.parse_inline(text, self_name, other_name)


class ClipboardSource(MessageSource):
    lane = "clipboard"

    def __init__(self, self_name: str = "我", other_name: str | None = None,
                 interactive: bool = True):
        self.self_name = self_name
        self.other_name = other_name
        self.interactive = interactive

    def resolve(self, query: str) -> list[Candidate]:
        self.other_name = self.other_name or query
        return [Candidate(id="clipboard", display=f"剪贴板：{query}", extra={"query": query})]

    def fetch(self, cand: Candidate, since: str | None = None, **kw) -> list[dict]:
        if not self.interactive:
            raise SourceError("剪贴板模式需要交互输入")
        print(BANNER.format(query=cand.extra.get("query", "")))
        seen: dict[tuple, dict] = {}
        rounds = 0
        while True:
            try:
                cmd = input("准备好后按回车读取剪贴板（输入 q 结束）> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                break
            if cmd == "q":
                break
            text = read_clipboard()
            if not text.strip():
                print("  [!] 剪贴板是空的，先复制消息再回车")
                continue
            batch = parse_text(text, self.self_name, self.other_name)
            batch = [r for r in batch if r.get("text")]
            if not batch:
                print("  [!] 没解析出消息，确认复制的是「昵称 + 时间 + 内容」的格式")
                print(f"      剪贴板开头：{text[:80]!r}")
                continue
            for r in batch:
                key = (r.get("ts"), r["text"])
                seen[key] = r
            rounds += 1
            print(f"  [ok] 第 {rounds} 段：{len(batch)} 条（累计 {len(seen)} 条）"
                  f"  {batch[0].get('time')} → {batch[-1].get('time')}")

        rows = sorted(seen.values(), key=lambda r: (r.get("ts") or 0, r.get("text", "")))
        if not rows:
            raise SourceError("一条消息都没收到")
        if since:
            rows = [r for r in rows if (r.get("time") or "") >= since]
        return rows


BANNER = """
==== 剪贴板采集：{query} ====
1) 打开与「{query}」的会话
2) 右键任意消息 → 多选 → 选择范围（或按住 Shift 连选）
3) Ctrl+C 复制
4) 回到这里按回车

可以分几段复制（每次往上滚一段再复制），脚本会自动合并去重。
"""
