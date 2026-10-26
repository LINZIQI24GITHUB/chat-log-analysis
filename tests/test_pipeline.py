# -*- coding: utf-8 -*-
"""冒烟测试：样例能跑通，且数字对得上。直接 python tests/test_pipeline.py。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "examples", "sample_chat.txt")


def run(*args: str) -> str:
    r = subprocess.run([sys.executable] + list(args), cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr, file=sys.stderr)
        raise SystemExit(f"命令失败: {args}")
    return r.stdout


def main() -> int:
    tmp = os.path.join(ROOT, "work", "_test_run")
    if os.path.isdir(tmp):
        shutil.rmtree(tmp, ignore_errors=True)  # 上一轮残留的 consent 会干扰断言
    os.makedirs(tmp, exist_ok=True)
    chat = os.path.join(tmp, "chat.jsonl")

    run("scripts/normalize.py", SAMPLE, "--self", "我", "--out", chat)
    rows = [json.loads(l) for l in open(chat, encoding="utf-8")]
    assert len(rows) == 189, f"期望 189 条，实际 {len(rows)}"
    assert rows[0]["sender"] == "other" and rows[1]["sender"] == "me"
    assert all(r["ts"] > 0 for r in rows), "时间戳解析失败"
    assert rows[0]["time"] == "2026-09-18 22:41:00"

    run("scripts/profile.py", chat, "--out", os.path.join(tmp, "profile.json"))
    prof = json.load(open(os.path.join(tmp, "profile.json"), encoding="utf-8"))
    assert prof["days"] == 20
    assert prof["me"] + prof["other"] == 189
    assert prof["level"] in ("ok", "descriptive")

    run("scripts/stats.py", chat, "--out", os.path.join(tmp, "stats.json"))
    st = json.load(open(os.path.join(tmp, "stats.json"), encoding="utf-8"))
    assert st["sessions"]["count"] > 0
    assert st["sessions"]["initiator"].get("me", 0) + st["sessions"]["initiator"].get("other", 0) > 0
    for s in ("me", "other"):
        if st["latency"][s]["n"]:
            assert st["latency"][s]["median"] > 0
    # 回复中位应当随时间变慢（样例的设定）
    wk = [v["other"] for v in st["latency_by_week"].values() if v.get("other")]
    assert wk == sorted(wk), f"样例里对方的回复速度应当单调变慢，实际 {wk}"

    run("scripts/digest.py", chat, "--out", os.path.join(tmp, "digest.txt"))
    run("scripts/shard.py", os.path.join(tmp, "digest.txt"),
        "--by", "week", "--out", os.path.join(tmp, "shards"))
    manifest = json.load(open(os.path.join(tmp, "shards", "manifest.json"), encoding="utf-8"))
    assert manifest["count"] >= 3

    run("scripts/keywords.py", chat, "--out", os.path.join(tmp, "keywords.json"))

    # 证据校验：样例必须是全命中
    out = run("scripts/check_evidence.py", chat, os.path.join(ROOT, "examples", "analysis.example.json"))
    assert "失配 0" in out, out

    run("scripts/render_report.py",
        "--stats", os.path.join(tmp, "stats.json"),
        "--profile", os.path.join(tmp, "profile.json"),
        "--keywords", os.path.join(tmp, "keywords.json"),
        "--analysis", os.path.join(ROOT, "examples", "analysis.example.json"),
        "--out", os.path.join(tmp, "report.md"),
        "--html", os.path.join(tmp, "report.html"))
    md = open(os.path.join(tmp, "report.md"), encoding="utf-8").read()
    assert "他爱不爱我" in md and "是不是渣" in md and "该不该分" in md
    assert "另一种解释" in md
    assert "分析框架" in md, "报告应包含分析框架章节"
    assert "置信度" in md, "判断应标注置信度"
    assert "Rusbult" in md, "应显示所用框架"
    # 默认脱敏：对方真名不应出现
    assert "陈屿" not in md, "默认应该脱敏对方姓名"
    assert "对方姓名已脱敏" in md

    # --reveal 才显示真名
    run("scripts/render_report.py",
        "--stats", os.path.join(tmp, "stats.json"),
        "--profile", os.path.join(tmp, "profile.json"),
        "--analysis", os.path.join(ROOT, "examples", "analysis.example.json"),
        "--out", os.path.join(tmp, "report_reveal.md"), "--reveal")
    md2 = open(os.path.join(tmp, "report_reveal.md"), encoding="utf-8").read()
    assert "陈屿" in md2

    # ---------- 采集层 ----------
    import subprocess as sp

    def rc(*args):
        return sp.run([sys.executable] + list(args), cwd=ROOT,
                      capture_output=True, text=True, encoding="utf-8")

    # 版本闸门：白名单内 / 外
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import version_guard
    assert version_guard.check_version("4.1.15.56")[0] == "ok"
    assert version_guard.check_version("9.9.9")[0] == "unknown_version"
    assert version_guard.check_version("9.9.9", force=True)[0] == "ok"

    # 资格确认：记录一次，版本小改仍有效，大版本变化要重新确认
    import consent
    state = os.path.join(tmp, "state")
    assert not consent.has_consent("wcdb", "4.1.15", state)
    assert consent.ensure("wcdb", "4.1.15", state, accept=True, i_am_party=False) is False
    assert consent.ensure("wcdb", "4.1.15", state, accept=True, i_am_party=True) is True
    assert consent.has_consent("wcdb", "4.1.15", state)
    assert consent.has_consent("wcdb", "4.1.16", state)
    assert not consent.has_consent("wcdb", "4.2.0", state), "大版本变化应重新确认"

    # OCR 通道：明确拒绝，而不是乱按键鼠
    r = rc("scripts/ingest.py", "--contact", "测试", "--lane", "ocr",
           "--state-dir", state, "--yes", "--i-am-party", "--out",
           os.path.join(tmp, "ocr.jsonl"))
    assert r.returncode == 4, (r.returncode, r.stdout, r.stderr)
    assert "还没实现" in (r.stdout + r.stderr)

    # wcdb 通道：没有 reader 时要给出可读的指引，而不是崩栈
    r = rc("scripts/ingest.py", "--contact", "测试", "--lane", "wcdb",
           "--state-dir", state, "--yes", "--i-am-party",
           "--reader-dir", os.path.join(tmp, "no-reader"),
           "--db-dir", os.path.join(tmp, "no-db", "db_storage"),
           "--self-wxid", "wxid_test",
           "--out", os.path.join(tmp, "wcdb.jsonl"))
    # 2 = 版本/平台闸门拦下；4 = 缺少 reader 或账号目录
    assert r.returncode in (2, 4), (r.returncode, r.stdout, r.stderr)
    assert any(k in (r.stdout + r.stderr).lower()
               for k in ("wcdb", "snapshot", "clipboard", "微信")), (r.stdout, r.stderr)

    print("全部通过：解析 / 体检 / 指标 / 分片 / 证据校验 / 渲染 / 脱敏 / 采集层")
    print("临时目录:", tmp)
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
