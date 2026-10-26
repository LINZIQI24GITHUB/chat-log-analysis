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
| `wcdb.py` | `wcdb` | 读本机正在登录的微信：调 `vendor/` 取密钥 → 解密 → 导出（Windows） |
| `snapshot.py` | `snapshot` | 读一个**已经解密**的微信数据目录（`contact/` + `message/`） |
| `ocr.py` | `ocr` | 占位，未实现，调用时会给出明确提示 |

## 关于 `wcdb` 通道

它读微信进程的内存来取密钥，只应该用在**你自己设备、你自己账号**上：

- 密钥不落盘、不联网，解密副本分析完即删
- 微信版本一变就可能失效——失效时先升级 `vendor/wcdb_key_tool_windows.py`（见 `vendor/NOTICE.md`）
- 杀软可能误报，这是这类工具的常态

想换成别的方式，直接写一个 `sources/mine.py`，
在 `scripts/ingest.py` 的 `build_source()` 里加一行分支即可，分析层完全不用改。

```python
if lane == "mine":
    from mine import MySource
    return MySource(...)
```
