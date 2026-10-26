# -*- coding: utf-8 -*-
"""微信版本闸门：只对验证过的版本放行读取，其他版本提示回落。

不猜、不硬跑。版本对不上时，明确告诉用户走剪贴板模式，
而不是让人在半路遇到「读出来是空表」。
"""
from __future__ import annotations

import os
import re

# 通过端到端验证的版本（major.minor.patch）
KNOWN_GOOD = {"4.1.15"}

EXE_CANDIDATES = [
    r"C:\Program Files\Tencent\Weixin\Weixin.exe",
    r"C:\Program Files (x86)\Tencent\Weixin\Weixin.exe",
    r"D:\Program Files\Tencent\Weixin\Weixin.exe",
    r"D:\Tencent\Weixin\Weixin.exe",
]


def find_exe() -> str | None:
    env = os.environ.get("WECHAT_EXE")
    if env and os.path.exists(env):
        return env
    for p in EXE_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def _version_from_exe(path: str) -> str | None:
    try:
        import win32api  # pywin32
        info = win32api.GetFileVersionInfo(path, "\\")
        ms, ls = info["FileVersionMS"], info["FileVersionLS"]
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}"
    except Exception:
        pass
    try:
        import subprocess
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-Item '{path}').VersionInfo.ProductVersion"],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        m = re.match(r"(\d+)\.(\d+)\.(\d+)", out)
        return ".".join(m.groups()) if m else None
    except Exception:
        return None


def installed_version() -> tuple[str | None, str | None]:
    """返回 (版本号, exe 路径)。"""
    exe = find_exe()
    if not exe:
        return None, None
    return _version_from_exe(exe), exe


def check_version(ver: str | None, force: bool = False) -> tuple[str, str]:
    """纯函数版本：给定版本号判断是否放行。"""
    if not ver:
        return "not_installed", "没有找到可读版本的微信客户端（或版本号无法解析）"
    major_minor = ".".join(ver.split(".")[:2])
    patch = ".".join(ver.split(".")[:3])
    if force:
        return "ok", f"微信 {ver}（--force-version，未经完整验证）"
    if patch in KNOWN_GOOD or ver in KNOWN_GOOD:
        return "ok", f"微信 {ver}（已验证）"
    if major_minor in {"4.0", "4.1"}:
        return "unknown_version", (
            f"微信 {ver} 没有经过验证（已验证：{', '.join(sorted(KNOWN_GOOD))}）。\n"
            f"  · 可以先用剪贴板模式：--lane clipboard\n"
            f"  · 或者确认无误后加 --force-version 冒险读取"
        )
    return "unknown_version", (
        f"微信 {ver} 是未支持的版本。请用 --lane clipboard，或等 reader 适配。"
    )


def check(force: bool = False) -> tuple[str, str]:
    """返回 (status, message)。"""
    ver, _exe = installed_version()
    return check_version(ver, force=force)


if __name__ == "__main__":
    status, msg = check()
    print(f"[{status}] {msg}")
    raise SystemExit(0 if status == "ok" else 1)
