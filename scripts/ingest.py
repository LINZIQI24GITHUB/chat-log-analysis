# -*- coding: utf-8 -*-
"""采集入口：把「分析和 XX 的聊天」变成 chat.jsonl。

用法：
  python scripts/ingest.py --contact 小林                    # 默认 wcdb
  python scripts/ingest.py --contact 小林 --lane clipboard   # 兜底
  python scripts/ingest.py --contact 小林 --asr dashscope    # 带语音转写

流程：版本闸门 → 资格确认 → 解析会话 → 拉取 → 落盘 → 打印下一步
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "sources"))

import consent  # noqa: E402
import version_guard  # noqa: E402
from base import SourceError  # noqa: E402




ASR_HELP = """
=== 语音转写是可选项：需要阿里云百炼的 API Key ===

  用途：把聊天里的语音消息转成文字。不转写，这部分内容就分析不到。

  · Key 从哪来
      阿里云百炼控制台  https://bailian.console.aliyun.com/
      → 右上角选地域 → 左侧「API-KEY」→ 创建
      （那串 key 只显示一次，先存好）

  · 音频去哪
      每条语音会解码成 wav，上传到阿里云百炼的语音识别服务做转写。
      音频会离开本机，不是本地处理。

  · 不给 Key 也能分析
      文字消息照常分析，只是语音部分没有内容：报告里显示为 [语音]，
      并在「看不到什么」里注明「N 条语音未转写」。
      所以没有 key 时，去掉 --asr 继续跑就行，不用停下来。
"""

def lane_available(lane: str) -> bool:
    """这个渠道的实现是否存在（开源版不带 wcdb）。"""
    mod = {"wcdb": "wcdb", "clipboard": "clipboard",
           "ocr": "ocr", "snapshot": "snapshot"}.get(lane)
    if not mod:
        return False
    try:
        __import__(mod)
        return True
    except ImportError:
        return False


def build_source(lane: str, args):
    if lane == "wcdb":
        try:
            from wcdb import WcdbSource
        except ImportError:
            raise SourceError(
                "本仓库不附带 wcdb 通道（需要从运行中的微信进程取密钥，属于另一类工具）。\n"
                "  · 有明文数据目录 → --lane snapshot --snapshot-dir <目录>\n"
                "  · 没有 → --lane clipboard，复制几段粘贴\n"
                "  · 想自己接 → 见 sources/README.md"
            )
        return WcdbSource(reader_dir=args.reader_dir, db_storage=args.db_dir,
                          self_wxid=args.self_wxid, asr=args.asr,
                          asr_key=args.asr_key, keep_temp=args.keep_temp,
                          wechat_version=args.wechat_version or "n/a",
                          interactive=not args.non_interactive,
                          keys_file=args.keys)
    if lane == "clipboard":
        from clipboard import ClipboardSource
        return ClipboardSource(self_name=args.self_name, other_name=args.contact,
                               interactive=not args.non_interactive)
    if lane == "ocr":
        from ocr import OcrSource
        return OcrSource(self_name=args.self_name)
    if lane == "snapshot":
        from snapshot import SnapshotSource
        return SnapshotSource(args.snapshot_dir, self_wxid=args.self_wxid)
    raise SourceError(f"未知 lane: {lane}")


def pick(cands: list, pick_index: int | None, non_interactive: bool):
    if len(cands) == 1:
        return cands[0]
    print("\n匹配到多个会话：")
    for i, c in enumerate(cands, 1):
        print(f"  {i}. {c.display}")
    if pick_index:
        if not (1 <= pick_index <= len(cands)):
            raise SourceError(f"--pick 超出范围（1..{len(cands)}）")
        return cands[pick_index - 1]
    if non_interactive:
        raise SourceError("匹配到多个会话，请用 --pick N 指定")
    try:
        raw = input(f"选第几个（1..{len(cands)}）> ").strip()
    except (EOFError, KeyboardInterrupt):
        raise SourceError("已取消")
    if not raw.isdigit():
        raise SourceError("输入无效")
    idx = int(raw)
    if not (1 <= idx <= len(cands)):
        raise SourceError("输入无效")
    return cands[idx - 1]


def main() -> int:
    ap = argparse.ArgumentParser(description="采集聊天记录为 chat.jsonl")
    ap.add_argument("--contact", required=True, help="聊天对象：昵称 / 备注 / 微信号")
    ap.add_argument("--lane", default="clipboard",
                    choices=["wcdb", "clipboard", "ocr", "snapshot"])
    ap.add_argument("--snapshot-dir", default=None,
                    help="离线快照目录（含 contact/ 和 message/ 的已解密目录）")
    ap.add_argument("--out", default="work/chat.jsonl")
    ap.add_argument("--since", default=None, help="只取该日期之后（YYYY-MM-DD）")
    ap.add_argument("--self-name", default="我", dest="self_name")
    ap.add_argument("--pick", type=int, default=None, help="多个候选时选第几个")
    ap.add_argument("--asr", default="off", choices=["off", "dashscope"],
                    help="语音转写：默认关闭；仅 wcdb 通道支持，snapshot/clipboard 忽略")
    ap.add_argument("--asr-key", default=None, help="默认读 DASHSCOPE_API_KEY")
    ap.add_argument("--reader-dir", default=None, help="本地 reader 工具包目录")
    ap.add_argument("--keys", default=None,
                    help="复用之前提取的密钥文件（不读微信进程，可完全离线）")
    ap.add_argument("--db-dir", default=None, help="微信 db_storage 目录")
    ap.add_argument("--self-wxid", default=None, help="本机微信 wxid（自动推断失败时用）")
    ap.add_argument("--keep-temp", action="store_true", help="保留解密临时目录（调试用）")
    ap.add_argument("--state-dir", default=None, help="consent 记录目录")
    ap.add_argument("--non-interactive", action="store_true")
    ap.add_argument("--yes", action="store_true", help="跳过确认（需配合 --i-am-party）")
    ap.add_argument("--i-am-party", action="store_true", dest="i_am_party",
                    help="确认你是这段对话的当事人之一")
    ap.add_argument("--force-version", action="store_true", help="忽略版本白名单")
    ap.add_argument("--wechat-version", default=None)
    args = ap.parse_args()

    # 1) 版本闸门（只有本机读取通道需要）
    version = args.wechat_version or "n/a"
    if args.lane == "wcdb" and lane_available("wcdb"):
        status, msg = version_guard.check(force=args.force_version)
        print(f"[version] {msg}")
        if status != "ok":
            print("\n[fallback] 改用剪贴板模式："
                  f"python scripts/ingest.py --contact {args.contact} --lane clipboard",
                  file=sys.stderr)
            return 2
        version = version_guard.installed_version()[0] or "n/a"
        args.wechat_version = version

    # 2) 资格确认
    if not consent.ensure(args.lane, version, args.state_dir,
                          accept=args.yes, i_am_party=args.i_am_party):
        return 3

    # 2.5) 语音转写：没有 key 就当场说清楚，别等解密五分钟才报错
    if args.asr != "off":
        if not (args.asr_key or os.environ.get("DASHSCOPE_API_KEY")):
            print(ASR_HELP, file=sys.stderr)
            return 5

    # 3) 解析 + 拉取
    try:
        src = build_source(args.lane, args)
    except SourceError as e:
        print(f"\n[error] {e}", file=sys.stderr)
        return 4
    try:
        print(f"\n[lane] {args.lane}  目标：{args.contact}")
        cands = src.resolve(args.contact)
        cand = pick(cands, args.pick, args.non_interactive)
        print(f"[pick] {cand.display}")
        rows = src.fetch(cand, since=args.since)
    except SourceError as e:
        print(f"\n[error] {e}", file=sys.stderr)
        return 4
    finally:
        src.close()

    voice_plain = sum(1 for r in rows
                      if r.get("kind") == "voice" and (r.get("text") or "").strip() in ("[语音]", ""))
    if voice_plain and args.asr == "off":
        print(f"\n[提示] 这个会话有 {voice_plain} 条语音，本次没有转写（报告里显示为 [语音]）。")
        print("       想连语音一起分析：准备一个阿里云百炼 API Key")
        print("       （https://bailian.console.aliyun.com/ → API-KEY），")
        print("       重跑并加 --asr dashscope。音频会上传到阿里云，不是本地处理。")
        print("       不加也照样能出报告，只是少了语音这部分内容。")

    if not rows:
        print("[error] 没有取到消息", file=sys.stderr)
        return 5

    # 4) 落盘
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    meta = {
        "lane": args.lane,
        "contact_query": args.contact,
        "target": cand.extra.get("username") or cand.id,
        "target_label": cand.extra.get("remark") or cand.extra.get("nick") or args.contact,
        "count": len(rows),
        "first": rows[0]["time"],
        "last": rows[-1]["time"],
        "asr": args.asr,
        "wechat_version": args.wechat_version or "n/a",
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "source_note": "本机读取" if args.lane == "wcdb" else "剪贴板",
    }
    meta_path = os.path.join(os.path.dirname(os.path.abspath(args.out)), "ingest_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)

    voice = sum(1 for r in rows if r.get("kind") == "voice")
    print(f"\n[ok] {len(rows)} 条 → {args.out}")
    print(f"     {rows[0]['time']} → {rows[-1]['time']}"
          f" | 语音 {voice} 条 | 微信 {meta['wechat_version']}")
    print(f"     元信息 → {meta_path}")
    print("\n下一步：")
    print(f"  python scripts/run_all.py {args.out} --self {args.self_name} --other "
          f"{meta['target_label']} --out work")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
