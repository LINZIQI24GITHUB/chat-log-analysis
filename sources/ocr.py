# -*- coding: utf-8 -*-
"""OCR 采集通道（占位，尚未实现）。

为什么先留空：滚屏抓取需要真实微信窗口做回归，没有验证过的自动化
不应该塞进用户电脑里乱按键鼠。等 wcdb 和 clipboard 两条通道跑顺了再补。

真要做的时候，这里需要三块：
  1. 窗口定位 + 滚动（user32 SendInput/PostMessage，或 UIA ScrollPattern）
  2. 截图 + OCR（rapidocr_onnxruntime 或 paddleocr）
  3. 跨屏去重（用最后 3 条 message 的时间+文本序列做锚点）
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from base import Candidate, MessageSource, SourceError  # noqa: E402


class OcrSource(MessageSource):
    lane = "ocr"

    def __init__(self, self_name: str = "我"):
        self.self_name = self_name

    def resolve(self, query: str) -> list[Candidate]:
        raise SourceError(
            "OCR 通道还没实现（需要真实微信窗口做回归，暂不提供）。\n"
            "  请用 --lane wcdb（本机读取）或 --lane clipboard（剪贴板）。"
        )

    def fetch(self, cand: Candidate, since: str | None = None, **kw) -> list[dict]:
        raise SourceError("OCR 通道还没实现")
