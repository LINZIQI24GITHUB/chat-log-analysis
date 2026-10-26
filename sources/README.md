# sources —— 数据从哪来

一个采集通道 = 实现 `base.MessageSource` 的两个方法：

```python
class MySource(MessageSource):
    lane = "mine"

    def resolve(self, query: str) -> list[Candidate]:
        """把用户给的昵称/备注/微信号解析成候选会话"""

    def fetch(self, cand: Candidate, since: str | None = None, **kw) -> list[dict]:
        """返回 chat.jsonl 结构的消息列表"""
```

`fetch` 返回的每条消息长这样：

```json
{"ts": 1758206460, "time": "2026-09-18 22:41:00",
 "sender": "me", "name": "我", "kind": "text", "text": "你好"}
```

- `sender` 只能是 `me` / `other`
- `kind` 用 `text` / `voice` / `image` / `sticker` / `media_other`
- 没有时间戳就填 `ts: 0`，分析层会自动跳过时延类指标

## 本仓库自带

| 文件 | lane | 说明 |
|---|---|---|
| `clipboard.py` | `clipboard` | 读系统剪贴板，用户在微信里复制几段，脚本合并去重 |
| `snapshot.py` | `snapshot` | 读一个**已经解密**的微信数据目录（`contact/` + `message/`） |
| `ocr.py` | `ocr` | 占位，未实现，调用时会给出明确提示 |

## 为什么不带「从运行的微信里取密钥」这条通道

那一步要读另一个进程的内存，属于另一类工具，本仓库不附带：

- 它和「分析」是两件事，混在一起会让这个项目的定位变味
- 杀软会拦，版本一升级就失效，维护成本和收益不成比例

如果你自己有合法的读取方式（例如已解密的数据目录），直接写一个 `sources/mine.py`，
在 `scripts/ingest.py` 的 `build_source()` 里加一行分支即可，分析层完全不用改。

```python
if lane == "mine":
    from mine import MySource
    return MySource(...)
```
