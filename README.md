# 微信聊天记录关系分析

**不用导出，不用上传。** 直接读本机微信，把一段聊天变成一份有证据的关系报告。

[为什么不用导出](#为什么不用导出) · [它能回答什么](#它能回答什么) · [快速开始](#快速开始) · [模拟对话](#模拟对话实验功能) · [隐私](#隐私) · [FAQ](#faq)

![报告预览](docs/preview.png)

---

## 为什么不用导出

微信本身不提供聊天记录导出。市面上常见的做法是：装导出工具 → 找密钥 → 解密数据库 → 导出成 txt → 上传给某个网站或模型。步骤多、门槛高，而且原文离开了你的机器。

这个项目把中间那几步省掉了：

- **直接读本机微信**（Windows，微信已登录）：从进程内存只读取密钥，解密到临时目录，分析完删除
- **或者读你已有的解密目录**：`contact/` + `message/`，不解密、不碰进程
- **什么都没有也能用**：在微信里复制几段，脚本合并去重

| | 导出 + 上传类工具 | 本项目 |
|---|---|---|
| 准备 | 装导出工具、找密钥、解密、导出 txt | 直接读本机微信，或读已有解密目录 |
| 原文去向 | 上传到服务器 / 模型 | 不出本机 |
| 引用 | 模型自由发挥 | 逐字校验，找不到就不出报告 |
| 交付 | 聊天式回答 | 单文件 HTML 报告，可离线打开 |
| 账号 | 通常要注册 | 无 |

> `wcdb` 通道需要 Windows + 微信已登录 + 版本白名单。不满足时用 `snapshot` 或 `clipboard`，分析部分完全一样。

## 它能回答什么

- **三个问题**：他爱不爱我 / 是不是渣 / 该不该分——给判断、给分数、给支持证据、给反方向证据、给替代解释
- **关系体检**：条数、发起、收尾、回复速度、活跃时段、最长沉默、断崖式降温
- **互动模式**：谁在追、谁在退、谁在维持对话、话题怎么漂移
- **关系阶段**：从初识到冷却卡在哪一步，转折点在哪
- **红旗清单**：不是贴标签，是列行为密度和出处
- **模拟对话（实验）**：把记录蒸馏成说话档案，用你自己的模型扮演对方继续聊——见下文

它**不**做心理诊断，不贴「NPD」「回避型依恋」这类人格标签，不教操控，也不替你作决定。

## 它和「让 AI 随便聊聊」的区别

1. **数字由脚本算**：条数、发起、收尾、回复中位、沉默时长、活跃时段，全部可复核，不经过模型
2. **每条判断挂原文**：引用必须逐字命中，`check_evidence.py` 是硬闸门，编造的引用进不了报告
3. **每条判断挂框架**：依恋、Gottman、Rusbult 投入模型、Knapp 阶段、中文语境校正，标注证据强度
4. **强制给反方向证据**：只写「他爱你」或只写「他渣」的报告，在这里过不了

## 快速开始

```bash
# 0 采集（四选一）

# A. 直接读本机微信（不用导出）
python scripts/ingest.py --contact 小林 --lane wcdb --out work/chat.jsonl

# B. 读一个已解密的微信数据目录
python scripts/ingest.py --contact 小林 --lane snapshot \
  --snapshot-dir "D:\wechat_data\<账号>" --out work/chat.jsonl

# C. 复制粘贴兜底（需要 pywin32）
python scripts/ingest.py --contact 小林 --lane clipboard --out work/chat.jsonl

# D. 已有导出文本
python scripts/normalize.py chat.txt --self 我 --out work/chat.jsonl

# 1 确定性部分：体检 → 指标 → 关键词 → 分片
python scripts/run_all.py work/chat.jsonl --self 我 --out work

# 2 让模型读 work/shards/*.txt，按 references/rubric.md 写 analysis.json
#    结构见 SKILL.md，示例见 examples/analysis.example.json

# 3 证据校验：任何一条引用对不上原文就不许出报告
python scripts/check_evidence.py work/chat.jsonl analysis.json

# 4 出报告（默认脱敏对方姓名）
python scripts/render_report.py --stats work/stats.json --profile work/profile.json \
  --keywords work/keywords.json --analysis analysis.json \
  --out work/report.md --html work/report.html
```

样例在 `examples/`：20 天的合成聊天 + 判断层，可以直接跑通全流程。

## 采集通道

| 通道 | 前提 | 输出 | 说明 |
|---|---|---|---|
| `wcdb` | Windows + 微信已登录 + 版本白名单 | 全量，含语音 | 默认；直接读本机微信，不用导出 |
| `snapshot` | 已解密的微信目录（`contact/` + `message/`） | 全量文字 | 不解密、不碰进程，最保守 |
| `clipboard` | `pip install pywin32` | 文本 | 在微信里复制几段，脚本合并去重 |
| `normalize` | 无 | 取决于导出格式 | 微信 / WhatsApp / 通用文本都能吃 |
| `ocr` | 未实现 | — | 占位，会明确报错 |

`wcdb` 会先要求确认「我是这段对话的当事人之一」，并比对微信版本；版本不在白名单会拒绝执行并建议改用 `clipboard`。详见 [PRIVACY.md](PRIVACY.md)。

想接自己的数据源：实现 `sources/base.py` 里的两个方法，见 [sources/README.md](sources/README.md)。

## 它怎么读微信（透明说明）

`wcdb` 会调用 `vendor/` 里的第三方工具（MIT）：

- 以只读方式打开微信进程内存，找到数据库密钥；**不注入、不挂钩、不修改**
- 密钥只在内存和临时文件里存在几十秒，解密后立即删除，不落盘
- 解密出的明文副本写到系统临时目录，分析结束自动删除（`--keep-temp` 才保留）
- 全程不联网；唯一的网络行为是你显式开启 `--asr dashscope` 时的语音转写

没有微信在运行、或版本不在白名单时，它什么也读不到，会提示改用 `snapshot` / `clipboard`。

`vendor/` 的许可与上游见 [vendor/NOTICE.md](vendor/NOTICE.md)。

## 语音转写（可选）

**不开启也能分析**：文字消息照常，只是语音部分没有内容，报告里显示为 `[语音]`，并在「看不到什么」里注明「N 条语音未转写」。

要连语音一起分析，需要**阿里云百炼的 API Key**：

1. 打开 [阿里云百炼控制台](https://bailian.console.aliyun.com/) → 右上角选地域 → **API-KEY** → 创建
2. 设环境变量 `DASHSCOPE_API_KEY`，或传 `--asr-key`
3. 采集时加 `--asr dashscope`

```bash
python scripts/ingest.py --contact 小林 --lane wcdb --asr dashscope
```

**音频会上传**：每条语音解码成 wav 后发给阿里云百炼的语音识别服务，不是本地处理。没有 Key 时程序会停下并打印这三步，不会偷偷降级。Key 只从环境变量或参数读取，不写入任何文件。

## 分析框架

判断不是凭直觉，每一条都挂一个理论构念。`references/frameworks/` 有六份可操作指南：

| 文件 | 框架 | 用来回答 |
|---|---|---|
| `00-index.md` | 索引 | 什么问题用哪套理论、证据强度怎么分 |
| `01-attachment.md` | 依恋理论 | 为什么忽冷忽热、为什么越问越退 |
| `02-gottman.md` | Gottman 四骑士与修复尝试 | 为什么吵架伤人、谁先递台阶 |
| `03-investment.md` | Rusbult 投入模型 | 他为什么不走、你为什么不走 |
| `04-communication.md` | 追—逃、连接邀请、自我披露 | 为什么聊不下去、谁在维持对话 |
| `05-stages.md` | Knapp 关系阶段 | 你们卡在哪一步 |
| `06-context-cn.md` | 中文语境与偏差校正 | 催婚压力、家庭介入、单方视角 |

三条规则：**框架只组织观察、不下诊断**；每条判断至少挂一个构念；标注证据强度（强/中/弱）。

## 交付物

`report.html`：单文件、零依赖、可离线打开。六个字号、三种视觉手段，数据图从记录里算出来：

- 按天的活跃度格子（空白就是那段没聊天的日子）
- 最忙一天的节奏条（两行分人，挤压处就是追与等）
- 按周回复速度折线、双方对比条

`report.md` 是同一份内容的纯文本版。

## 模拟对话（实验功能）

分析完还能接着聊：先把记录蒸馏成一份**说话档案**，再用你自己的模型扮演对方。

```bash
python scripts/persona.py work/chat.jsonl --stats work/stats.json --out persona.json
python sim/sim.py --persona persona.json      # 打开 http://127.0.0.1:8777
```

界面是一个只有这条会话的微信窗口：气泡、正在输入、已读不回都在。回复快慢按对方的**真实时延分布**采样，说话长度按平均字数收敛，有概率不回。

配置只要**一个 API Key**：点右上角 ⚙ 粘进去、点连接。程序会挨家试（DeepSeek / 阿里云百炼 / Kimi / 智谱 / OpenAI），谁认就用谁，不用你选服务商和模型。自建或小众服务点「手动设置地址和模型」。

| 从记录里蒸出来的 | 用在哪 |
|---|---|
| 平均字数、单双字占比 | 回复长度 |
| P10/P50/P90 时延 | 隔多久才「正在输入」 |
| 主动开场率、连发率、反问率 | 互动节奏 |
| 语气词、口头禅、表情占比 | 说话形状 |
| 真实对答片段（10 组） | few-shot，学语气不学台词 |
| 性格标签（带数字依据） | 「被动」「爱连发」「回避正面回应」 |
| 情绪曲线 | 基线 + 情绪高/低的那几天 |
| 她亲口说过的事实 | 记住具体细节 |
| 原始记录全文 | 每次回复前检索相关旧事，注入上下文 |

**防编造**：生成后检查有没有出现上下文里没有的数字，有就重写一次，再不行就删掉那句。

注意：

- API Key 只存在**你的浏览器** localStorage，随请求透传，本地服务不写盘、不记日志
- `persona.json` 里有原文片段，已进 `.gitignore`，不要提交
- 界面固定标注「模拟对话 · 基于 N 条记录生成，不是本人」
- 生成的回复**不要转发给对方**：那是模型写的，不是那个人说的

## 隐私

- 全流程本地，原文不出机器；没有服务端、没有账号、没有遥测
- 语音默认不转写；`--asr` 需要你自己配置 ASR key，且音频会离开本机，跑之前要确认
- 报告默认脱敏对方姓名；没有「生成分享图」「一键发朋友圈」
- 中间产物（`work/chat.jsonl`、`work/shards/`）含原文，交付后请自行删除

细节见 [PRIVACY.md](PRIVACY.md)。

## FAQ

**需要先导出聊天记录吗？**
不需要。`wcdb` 直接读本机微信；也可以读已有的解密目录，或在微信里复制粘贴。

**会上传我的聊天记录吗？**
不会。解析、统计、证据校验、渲染都在本地；模型判断发生在你自己的 agent 里。唯一例外是显式开启的语音转写，以及你主动使用的模拟对话（请求发给你自己配置的模型）。

**支持 Mac 吗？**
`wcdb` 通道目前仅 Windows；`snapshot` / `normalize` 跨平台；`clipboard` 需要 pywin32（Windows）。

**支持群聊吗？**
只做 1:1 私聊。群聊需要先指定两个人。

**样本很少能分析吗？**
< 300 条只做描述，不做趋势；< 80 条只做印象式点评。

**这是心理诊断吗？**
不是。它是探索性分析，不能替代专业咨询，也不能替你作决定。

## 边界与免责

- 只支持一对一私聊
- 框架来自公开的亲密关系研究，样本以西方已婚异性恋夫妻为主，跨文化适用性有限
- 只应用于你自己设备上、你自己账号的数据；读取他人数据可能违法
- **探索性分析，不是心理诊断**

## 装成 skill

```bash
git clone https://github.com/LINZIQI24GITHUB/wechat-relationship-analysis \
  ~/.claude/skills/wechat-relationship-analysis
# 或 ~/.kimi-code/skills/、DSH 的 skills 目录
```

之后对 agent 说「分析一下我和 XX 的聊天记录」就会触发。

## 依赖

Python 3.9+。核心分析只用标准库；`zstandard` 读数据库需要，`jieba` 可选（没装退回二元组），`pywin32` 只有剪贴板通道需要。

## License

MIT
