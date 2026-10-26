# -*- coding: utf-8 -*-
"""模拟微信对话的本地小服务。

只做三件事：
  1. 把 sim.html 和 persona.json 发给浏览器
  2. 收前端的一条消息，转发给用户自己填的 OpenAI 兼容接口
  3. 按 persona 的时延分布，返回「多久之后回」「回不回」

API Key 只在前端 localStorage 里，随请求透传，本服务不写盘、不记日志。

用法：
  python sim/sim.py --persona persona.json --port 8777
然后浏览器打开 http://127.0.0.1:8777
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PERSONA: dict = {}
LAST_SILENT = {"v": False}
MAX_DELAY_S = 20.0   # 单条回复最长等待（可 --max-delay 调）
REPLY_RATE_OVERRIDE = {"v": None}


def _num(x, default):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def sample_delay_ms(persona: dict) -> int:
    """按 P10/P50/P90 采样一个回复延迟。

    真人不是均匀分布的：多数很快，偶尔很久。用对数正态近似，
    再用 P10/P90 截断，避免出现「3 小时后才回」。"""
    t = persona.get("timing") or {}
    p10 = _num(t.get("p10_sec"), 3)
    p50 = _num(t.get("p50_sec"), 15)
    p90 = _num(t.get("p90_sec"), 120)
    p50 = max(p50, p10 + 1)
    # 对数正态拟合：sigma 用 P90/P50 在 log 空间估，别用线性差
    sigma = math.log(max(p90, p50 + 1) / max(p50, 1)) / 1.28
    sigma = max(0.25, min(1.15, sigma))
    v = random.lognormvariate(math.log(max(p50, 1)), sigma)
    v = min(max(v, p10), max(p90, p10 + 1))
    v = min(v, MAX_DELAY_S)          # 模拟对话里不能真让人等 20 分钟
    return int(v * 1000)


def call_model(cfg: dict, persona: dict, history: list[dict]) -> str:
    base = (cfg.get("base_url") or "").rstrip("/")
    key = cfg.get("key") or ""
    model = cfg.get("model") or "gpt-4o-mini"
    if not base or not key:
        raise ValueError("还没填 API：点右上角齿轮，填 base_url 和 key")

    msgs = [{"role": "system", "content": persona.get("system_prompt", "")}]
    for h in history[-14:]:
        role = "user" if h.get("role") == "me" else "assistant"
        msgs.append({"role": role, "content": str(h.get("text", ""))[:500]})
    msgs.append({"role": "system",
                 "content": "只输出她这一条回复的纯文本，不要引号、不要解释。"})

    body = json.dumps({"model": model, "messages": msgs,
                       "temperature": 0.9, "max_tokens": 120,
                       "frequency_penalty": 0.7, "presence_penalty": 0.5}).encode("utf-8")
    req = urllib.request.Request(
        base + "/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        hint = ""
        if e.code == 401 and len(key) != 35:
            hint = f"（key 长度 {len(key)}，应该是 35，多半是粘贴不全）"
        elif e.code == 401:
            hint = ("（key 和 Base URL 不配套？常见：阿里云地址 + DeepSeek key。"
                    "DeepSeek 用 https://api.deepseek.com/v1 + deepseek-chat；"
                    "阿里云用 https://dashscope.aliyuncs.com/compatible-mode/v1 + qwen-plus）")
        raise ValueError(f"接口返回 {e.code}{hint}：{detail}")
    except urllib.error.URLError as e:
        raise ValueError(f"连不上 {base}：{e.reason}")

    text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    if os.environ.get("SIM_DEBUG") == "1":
        print(f"[raw] {text!r} finish={(data.get('choices') or [{}])[0].get('finish_reason')}",
              file=sys.stderr, flush=True)
    text = re.sub(r"^[\"'「『]|[\"'」』]$", "", text.strip())
    text = re.sub(r"（.*?）|\(.*?\)", "", text).strip()   # 去掉旁白
    avg = int((persona.get("style") or {}).get("avg_len") or 10)
    text = text[: max(30, avg * 4)]
    said = {str(h.get("text")) for h in history if h.get("role") != "me"}
    if text and text in said:
        # 复读机：把刚才那句塞回去，要求换一句
        msgs.append({"role": "assistant", "content": text})
        msgs.append({"role": "system", "content": "你刚才说的和之前一模一样了。换一句，别重复。"})
        body = json.dumps({"model": model, "messages": msgs, "temperature": 1.0,
                           "max_tokens": 120, "frequency_penalty": 0.9,
                           "presence_penalty": 0.7}).encode("utf-8")
        req = urllib.request.Request(
            base + "/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + key})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))
            retry = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
            retry = re.sub(r"^[\"'「『]|[\"'」』]$", "", retry)
            if retry and retry not in said:
                text = retry[: max(30, avg * 4)]
        except Exception:
            pass
    return text



# 按「最可能」排序：先用 key 挨家试，谁认就用谁。用户只需要填一个 key。
PROVIDERS = [
    ("DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat"),
    ("阿里云百炼", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    ("阿里云百炼(国际)", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    ("Kimi", "https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    ("智谱", "https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
    ("OpenAI", "https://api.openai.com/v1", "gpt-4o-mini"),
]


def detect_provider(key: str) -> dict:
    """拿这把 key 挨家试一次；第一个通的就定下来。"""
    tried = []
    for name, base, model in PROVIDERS:
        cfg = {"base_url": base, "model": model, "key": key}
        try:
            call_model(cfg, {"system_prompt": "你是连通性测试。只回一个字：好"},
                       [{"role": "me", "text": "在吗"}])
            print(f"[detect] {name} 通过", file=sys.stderr, flush=True)
            return {"ok": True, "provider": name, "base_url": base, "model": model}
        except ValueError as e:
            msg = str(e)
            tried.append({"provider": name, "error": msg[:120]})
            print(f"[detect] {name} 失败: {msg[:100]}", file=sys.stderr, flush=True)
    return {"ok": False, "tried": tried}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # 不记请求日志（里面可能有对话内容）

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            path = os.path.join(HERE, "sim.html")
            self._send(200, open(path, "rb").read(), "text/html; charset=utf-8")
        elif self.path == "/persona.json":
            self._send(200, json.dumps(PERSONA, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path == "/api/detect":
            n = int(self.headers.get("Content-Length") or 0)
            try:
                key = ((json.loads(self.rfile.read(n) or b"{}").get("key")) or "").strip()
            except json.JSONDecodeError:
                key = ""
            if not key:
                self._send(200, json.dumps({"ok": False, "error": "没有填 key"},
                                           ensure_ascii=False).encode(),
                           "application/json; charset=utf-8")
                return
            out = detect_provider(key)
            self._send(200, json.dumps(out, ensure_ascii=False).encode(),
                       "application/json; charset=utf-8")
            return
        if self.path == "/api/ping":
            n = int(self.headers.get("Content-Length") or 0)
            try:
                cfg = (json.loads(self.rfile.read(n) or b"{}").get("config") or {})
            except json.JSONDecodeError:
                cfg = {}
            key = cfg.get("key") or ""
            print(f"[ping] base={cfg.get('base_url')!r} model={cfg.get('model')!r} "
                  f"key_len={len(key)} key_head={key[:5]} key_tail={key[-4:] if key else ''}",
                  file=sys.stderr, flush=True)
            try:
                probe = {"system_prompt": "你是测试。只回一个字：好"}
                text = call_model(cfg, probe, [{"role": "me", "text": "在吗"}])
                out = {"ok": True, "sample": text, "key_len": len(key)}
            except ValueError as e:
                out = {"ok": False, "error": str(e), "key_len": len(key)}
            self._send(200, json.dumps(out, ensure_ascii=False).encode(),
                       "application/json; charset=utf-8")
            return
        if self.path != "/api/reply":
            self._send(404, b"not found", "text/plain")
            return
        n = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            self._send(400, b'{"error":"bad json"}', "application/json")
            return

        persona = PERSONA
        history = payload.get("history") or []
        cfg = payload.get("config") or {}
        turn = int(payload.get("turn") or 0)          # 这是第几次发消息

        reply_rate = _num((persona.get("timing") or {}).get("reply_rate"), 0.8)
        if REPLY_RATE_OVERRIDE["v"] is not None:
            reply_rate = max(0.0, min(1.0, REPLY_RATE_OVERRIDE["v"]))
        else:
            # 真人不回是常态，但连续不回会让体验像坏了：回复率下限 35%
            reply_rate = max(0.35, min(0.95, reply_rate))
        silent = random.random() > reply_rate
        if silent and LAST_SILENT["v"]:
            silent = False
        if turn <= 3:                                  # 热身：前 3 句一定回
            silent = False
        LAST_SILENT["v"] = silent
        if silent:
            # 她不回的情况：给一个更长的延迟，前端显示「正在输入」然后静默
            print(f"[reply] turn={turn} silent=True key_len={len(cfg.get('key') or '')}",
                  file=sys.stderr, flush=True)
            self._send(200, json.dumps({
                "reply": False, "delay_ms": min(12000, int(sample_delay_ms(persona) * 1.2)),
                "typing_ms": random.randint(2500, 6000)}, ensure_ascii=False).encode(),
                "application/json; charset=utf-8")
            return

        try:
            text = call_model(cfg, persona, history)
        except ValueError as e:
            print(f"[reply] 失败 key_len={len(cfg.get('key') or '')} err={str(e)[:120]}",
                  file=sys.stderr, flush=True)
            self._send(200, json.dumps({"error": str(e)}, ensure_ascii=False).encode(),
                       "application/json; charset=utf-8")
            return

        delay = sample_delay_ms(persona)
        print(f"[reply] turn={turn} silent=False delay={delay/1000:.1f}s "
              f"len={len(text)} key_len={len(cfg.get('key') or '')}",
              file=sys.stderr, flush=True)
        self._send(200, json.dumps({
            "reply": True, "text": text, "delay_ms": delay,
            "typing_ms": max(900, int(delay * 0.35)),
        }, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8")


def main() -> int:
    global PERSONA
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", default="persona.json")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--max-delay", type=float, default=20.0,
                    help="单条回复最长等待秒数（默认 20）")
    ap.add_argument("--reply-rate", type=float, default=None,
                    help="调试用：覆盖回复概率（0~1）")
    args = ap.parse_args()

    path = args.persona
    if not os.path.exists(path):
        print(f"[error] 找不到 {path}，先跑 scripts/persona.py 生成", file=sys.stderr)
        return 2
    PERSONA = json.load(open(path, encoding="utf-8"))
    global MAX_DELAY_S
    MAX_DELAY_S = args.max_delay
    REPLY_RATE_OVERRIDE["v"] = args.reply_rate

    ThreadingHTTPServer.allow_reuse_address = False   # Windows 上否则会重复绑定同一端口
    try:
        srv = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as e:
        print(f"[error] 端口 {args.port} 被占用或无法监听：{e}\n"
              f"        换一个：--port {args.port + 1}", file=sys.stderr)
        return 3
    print(f"模拟对话已启动：http://{args.host}:{args.port}")
    print(f"  对象：{PERSONA.get('name')} ｜ 样本 {PERSONA.get('counts', {}).get('total')} 条")
    print("  点右上角齿轮填 base_url / model / key（只存在浏览器里）")
    print("  Ctrl+C 退出")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
