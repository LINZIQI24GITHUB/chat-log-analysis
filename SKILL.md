---
name: chat-log-analysis
description: >-
  分析用户和某个人的聊天记录，产出有证据的关系报告：他爱不爱我、是不是渣、
  该不该分，以及互动模式、情绪曲线、话题变化、关系阶段。
  触发场景：分析聊天记录、复盘一段关系、看看我们怎么相处的、他到底怎么想的、
  这段关系该不该继续、分析我和 XX 的聊天。
  可以直接从本机微信读（需本地 reader），也可以用剪贴板/已导出的文本。
version: 0.3.0
---

# 聊天记录关系分析

用户说「分析我和小林的聊天」，就走完整条链路：采集 → 指标 → 分片打分 →
汇总 → 证据校验 → 出报告。核心不是算命，是把记录里已经存在、但当事人看不清的
模式摊开，每一条都挂上原文。

## 何时使用

- 用户贴了一段聊天记录，或说「分析我和 XX 的聊天」
- 用户问「他爱不爱我」「我们这样正常吗」「该不该继续」
- 用户想复盘一段关系，要情绪曲线 / 互动模式 / 关键节点

## 什么时候先停下来

- **不是本人参与的对话** → 不做（这是资格问题，不是授权问题）
- **群聊** → 本版只做 1:1，请用户指定主要对话的两个人
- **条数 < 80** → 说明只能做印象式点评，不给趋势结论
- **只有截图** → 先请用户复制文字或走剪贴板通道

## 采集：三条通道

```bash
# 1) 已有明文数据目录（contact/ + message/）
python scripts/ingest.py --contact 小林 --lane snapshot \
  --snapshot-dir "D:\wechat_data\<账号>" --out work/chat.jsonl

# 2) 什么都没有，复制粘贴
python scripts/ingest.py --contact 小林 --lane clipboard --out work/chat.jsonl

# 3) 已导出的文本
python scripts/normalize.py chat.txt --self 我 --out work/chat.jsonl
```

| 通道 | 前提 | 输出质量 | 说明 |
|---|---|---|---|
| `snapshot` | 已解密的微信数据目录 | 全量文字，语音为占位 | 最省事，**不解密、不碰进程** |
| `clipboard` | pywin32 | 文本 100%，无时间戳时降级 | 用户在微信里复制几段，脚本合并去重 |
| `normalize` | 任意文本/JSONL | 取决于导出格式 | 微信/WhatsApp/通用格式都能吃 |
| `ocr` | 未实现 | — | 会明确报错，不乱按键鼠 |

> 仓库**不附带**「从运行中的微信进程取密钥」那条通道。它属于另一类工具，和「分析」
> 是两件事。你有合法读取方式的话，按 `sources/README.md` 自己接一个即可。

### 资格确认（读取前必弹）

第一次读取会要求输入「我已了解」，记录在 `~/.chat-log-analysis/consent.json`。
确认的是**资格**，不是**对方授权**：个人事务范围内的分析不需要对方签字，
但前提是「你是这段对话的当事人之一」。

非交互场景用 `--yes --i-am-party`，两个参数缺一不可。

## 流程

### 第 0 步：采集 + 确认解析

```bash
python scripts/ingest.py --contact <名字> --lane snapshot --snapshot-dir <目录> --out work/chat.jsonl
python scripts/run_all.py work/chat.jsonl --self 我 --out work
```

`ingest.py` 会打印条数、时间范围、语音条数；`normalize.py` 会打印前 12 条。
**把这段预览转述给用户确认**，格式错位是这类任务最常见的翻车点。

体检结果在 `work/profile.json`：

- `ok` → 可以做趋势判断
- `descriptive` → 只做描述，不许写「越来越」「明显下降」
- `unusable` → 直接说样本不足，别硬出报告

### 第 1 步：确定性指标（脚本，不许手算）

```bash
python scripts/stats.py work/chat.jsonl --out work/stats.json
python scripts/keywords.py work/chat.jsonl --out work/keywords.json
```

报告里所有数字只能来自这两个文件。

### 第 2 步：分片 + 子 agent 打分

```bash
python scripts/shard.py work/digest.txt --by week --out work/shards
```

每个分片交给一个子 agent（并行）。prompt 模板：

```
你要分析一段微信私聊的一个时间片。文件：{abs_path}

背景：{用户描述的一两句}。记录里 "我" 是提问方，"对方" 是另一方。
每天以 "========== YYYY-MM-DD (N条) ==========" 分隔，每行 "HH:MM 我/对方: 内容"。

通读全文，对【每一天】输出一条 JSON：
{
  "date": "YYYY-MM-DD",
  "score_me": -2..2,
  "score_other": -2..2,
  "mood": "当天整体氛围一句话，≤15字",
  "topics": ["2-4 个当天话题"],
  "events": "具体事件/约定/转折；没有就写「日常闲聊」",
  "quote": "1-2 句最有代表性的原话（原文照抄，标注谁说的）"
}

注意：
- 区分「撒娇/互怼/玩笑」和「真正的冲突」（明确不满、冷淡、拒绝、沉默）
- 注意转折点：吵架、约定、称呼变化、深夜长谈、突然变短
- 语音转写可能有错字，不要过度解读单句

只输出 JSON 数组，不要任何解释文字。
```

子 agent 返回后逐条断言：

- `date` 落在分片时间范围内（防 `2029-09-22` 这类错年份）
- 分数 ∈ [-2, 2]
- `topics` ≤ 4 个
- `quote` 必须能在该分片里找到，找不到就丢弃 quote、保留分数

### 第 2.5 步：选框架（别跳过）

打开 `references/frameworks/00-index.md`，按用户问的问题选 **1 个主框架 + 1–2 个辅助框架**。
读对应文件，记下要看的**可观察标记**，再去看数据。

常用组合：

| 用户问 | 主框架 | 辅助 |
|---|---|---|
| 他爱不爱我 | 投入模型（Rusbult） | 依恋维度、未来指向 |
| 为什么总吵架 | Gottman 四骑士 + 修复尝试 | 追—逃模式 |
| 该不该继续 | 投入模型 + 相互依赖 | 阶段模型 |

框架只给「看什么」，不给「他是什么人」。**不许用类型标签**（回避型依恋、NPD）。

### 第 3 步：汇总成 `analysis.json`

把日分数合成周曲线，结合第 1 步的统计和第 2.5 步的框架，写成 `analysis.json`。
这一步是主 agent 的活，不要把子 agent 的输出直接拼起来交差。

每条判断都要标 `framework`（构念）和 `confidence`（强/中/弱）。

### 第 4 步：证据校验（硬闸门）

```bash
python scripts/check_evidence.py work/chat.jsonl analysis.json
```

任何一条引用对不上原文，就不许出报告。改了重跑，不许绕过。

### 第 5 步：出报告

```bash
python scripts/render_report.py --stats work/stats.json --profile work/profile.json \
  --keywords work/keywords.json --analysis analysis.json \
  --out work/report.md --html work/report.html
```

默认**对方姓名脱敏**为「对方」；用户明确要求时才加 `--reveal`。

## `analysis.json` 结构

```json
{
  "meta": {"title": "...", "self_name": "我", "other_name": "陈屿",
           "period": "2026-09-18 ~ 2026-10-07", "one_line": "一句话结论",
           "scope": "单方视角 · 189 条文字 · 无语音转写"},
  "frameworks_used": [
    {"name": "Rusbult 投入模型", "why": "判断他留下/离开的成本结构"},
    {"name": "Gottman 四骑士", "why": "看冲突方式，不只看吵不吵"}
  ],
  "verdicts": [
    {"q": "他爱不爱我", "score": "6/10", "confidence": "中",
     "framework": ["Rusbult · 已投入成本", "Gottman · 修复尝试"],
     "answer": "直接回答",
     "support": [{"date": "09-22", "quote": "原文", "why": "它证明了什么"}],
     "against": [{"date": "10-06", "quote": "原文", "why": "它推翻了什么"}],
     "alt": "另一种解释", "verdict_line": "更锋利的那句"}
  ],
  "phases": [{"range": "09-18 ~ 09-24", "label": "升温", "note": "..."}],
  "red_flags": [{"behavior": "...", "count": 3, "evidence": "日期",
                 "severity": "高/中/低", "framework": "Gottman · 筑墙"}],
  "patterns": [{"name": "...", "desc": "...", "framework": "依恋 · 追—退循环"}],
  "advice": [{"text": "..."}],
  "limits": ["..."]
}
```

`verdicts` 至少三条，顺序固定：爱不爱 → 是不是渣 → 该不该分。

## 回答契约（硬规则）

1. **不拒答**。这三类问题都要正面回答——拒答只会把用户推给更不靠谱的人。
2. **给分**。「爱不爱」必须落到可比较的分值，不许用「感情是复杂的」收尾。
3. **每条结论挂证据**：至少 1 条原文 + 1 条统计；没有统计就注明。
4. **每条推断给替代解释**：至少一个，防止单线叙事。
5. **「该不该」回到用户自己的标准**：从记录里挖她说过的底线，不替她发明。
6. **每条判断挂框架**：写清用的是哪个构念，标 `confidence`（强/中/弱）。
7. **允许说「记录里没有」**，不许脑补对方动机。

## 三条边界

1. **不做临床标签**：不说「NPD」「回避型依恋」「PUA 人格」。可以说「行为符合高回避维度的特征」，不能说「他是回避型」。框架只提供观察角度，不提供诊断。
2. **不教操控**：不写「怎么让对方服从」的具体话术；「怎么把需求说清楚」可以。
3. **必须声明单方视角**：只有一方提供的记录，看不到对方没发出去的话。

## 输出与清理

- `work/report.md` / `work/report.html`：成品（默认脱敏）
- `work/analysis.json`：可复核的判断与证据
- `work/stats.json` / `keywords.json` / `profile.json`：数字底稿
- `work/chat.jsonl`、`work/shards/`：含原文，**敏感中间产物**，交付后提示删除
- `wcdb` 通道的解密副本写在系统临时目录，`ingest.py` 结束即删；`--keep-temp` 才会保留

## 成本与隐私

- 分析全程本地，原文不出机器；没有服务端，没有账号
- 模型调用发生在用户自己的 agent 里，用用户自己的额度
- 语音默认**不**转写；`--asr dashscope` 会把音频上传到阿里云，跑之前要明确告知
- 一次 200 条左右的分析：4 个分片 × 2~3K tokens 输出，成本很低
