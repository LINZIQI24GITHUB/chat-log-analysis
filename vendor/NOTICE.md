# 第三方代码与许可

## vendor/wcdb_key_tool_windows.py

- 来源：https://github.com/TANGandXUE/wcdb-key-tool
- 许可：MIT
- 用途：从运行中的微信进程读取数据库密钥（只读内存，不注入、不挂钩）
- 它同时致谢了上游：
  - [ylytdeng/wechat-decrypt](https://github.com/ylytdeng/wechat-decrypt)（内存扫描基础代码）
  - [lopleec/wxchat-export](https://github.com/lopleec/wxchat-export)（ELF 静态分析方法）

Copyright (c) TANGandXUE and contributors. Licensed under the MIT License.

**升级方式**：从上游拉最新版，覆盖 `vendor/wcdb_key_tool_windows.py` 即可；
如果密钥提取失败，多半是微信改了内存结构，而不是本项目的问题。

## vendor/full_decrypt.py、vendor/decrypt_wal.py

本项目自写（MIT），负责把加密库连同 WAL 一起解成明文 SQLite。
它们调用上面那个工具的 `_decrypt_database()`，不含独立的密钥提取逻辑。

## 免责

这两个通道只应用于**你自己设备上、你自己账号**的数据。读取他人设备或账号的数据
可能违法。使用者自行承担合规责任。
