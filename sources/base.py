# -*- coding: utf-8 -*-
"""采集源的公共接口。

新增一个采集方式 = 实现两个方法，不用碰分析层。
"""
from __future__ import annotations

from dataclasses import dataclass, field


class SourceError(RuntimeError):
    """采集失败，消息要能直接给用户看。"""


@dataclass
class Candidate:
    id: str
    display: str
    extra: dict = field(default_factory=dict)


class MessageSource:
    lane = "base"

    def resolve(self, query: str) -> list[Candidate]:
        """把用户给的名字（昵称/备注/微信号）解析成候选会话。"""
        raise NotImplementedError

    def fetch(self, cand: Candidate, since: str | None = None, **kw) -> list[dict]:
        """拉取消息，返回 chat.jsonl 结构的 list。"""
        raise NotImplementedError

    def close(self) -> None:
        pass
