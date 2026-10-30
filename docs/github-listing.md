# GitHub 仓库命名与介绍（可直接复制）

## 推荐仓库名

**`wechat-relationship-analysis`**

理由：GitHub 搜索按 token 匹配，这个名字同时命中 `wechat`、`relationship`、`analysis` 三个高意图词；旧名 `chat-log-analysis` 既没有平台词，又暗示「导出的日志」，和「不用导出」的卖点相反。

备选：

| 名字 | 适合 | 代价 |
|---|---|---|
| `wechat-chat-analysis` | 想覆盖更广的「聊天分析」搜索 | 不够聚焦，容易和通用聊天工具混在一起 |
| `wechat-crush-analysis` | 想在小红书/情感流量里冲点击 | 窄，且「crush」会把友情分析挡在外面 |

> 不建议用中文仓库名：URL 会变成百分号编码，分享和记忆都吃亏。中文关键词放在 Description、Topics 和 README 里。

## Description（About，直接粘贴）

```
微信聊天记录关系分析：直接读本机微信，不用导出、不用上传。回答「他爱不爱我 / 是不是渣 / 该不该分」，每条判断挂原文、引用逐字校验、数字由脚本算。依恋 / Gottman / Rusbult 框架，本地运行。WeChat relationship analysis, no export.
```

## Topics（直接粘贴，逗号分隔）

```
wechat, wechat-analysis, chat-analysis, relationship-analysis, relationship, dating, crush, psychology, attachment-theory, gottman, local-first, privacy, no-export, ai-skill, llm, chinese, python, cli
```

## 改名步骤（需要仓库管理员权限）

1. 打开 `https://github.com/LINZIQI24GITHUB/chat-log-analysis/settings`
2. **Repository name** → 改为 `wechat-relationship-analysis` → **Rename**
3. 回到仓库首页，右侧 **About** 的齿轮 → 粘贴上面的 Description → **Save**
4. 同一面板的 **Topics** → 粘贴上面的列表 → **Save changes**
5. 本地更新 remote：

```bash
git remote set-url origin https://github.com/LINZIQI24GITHUB/wechat-relationship-analysis.git
git push origin main
```

GitHub 会为旧地址保留重定向，但 README、文档、安装命令里的链接要一起更新。

## 为什么旧名字搜不到

1. 名字里没有 `wechat`：搜「微信聊天记录分析」时，仓库名不参与中文匹配
2. Description 实际存成了一串 `?`（中文在提交时被编码破坏），等于没有描述
3. Topics 只有 7 个，缺 `wechat-analysis`、`relationship-analysis`、`dating`、`no-export`
4. README 标题是 `chat-log-analysis`，不是用户会搜的词

## README 首屏建议（已按此重写）

- 第一行就给卖点：**不用导出，不用上传**
- 第二行给场景：直接读本机微信 → 有证据的关系报告
- 第三行给差异：引用逐字校验 / 数字由脚本算 / 框架标注
- 对比表放在首屏下方：导出+上传 vs 本项目
- FAQ 第一条就是「需要先导出聊天记录吗？」
