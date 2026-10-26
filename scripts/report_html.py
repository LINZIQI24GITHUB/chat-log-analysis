# -*- coding: utf-8 -*-
"""报告网页渲染：单文件、零依赖、可离线打开。

设计取舍（参考 design-taste-frontend 的房规，针对"报告"这种体裁做减法）：
  · 只有 3 种视觉手段：大字、整块色场、真实数据图
  · 不用小字大写字母间距标签、不用卡片阴影、不用渐变
  · 数字由数据画出来（活跃度格子、节奏条、折线、对比条），不是装饰
  · 段落用衬线，数字与标签用无衬线；全程两个字体
"""
from __future__ import annotations

import datetime as dt
import html
import re

# ---------------------------------------------------------------- 调色 token

PAPER = "#f6f2e8"
INK = "#17150f"
MUTED = "#6d6659"
RULE = "#d8d1c0"
ACCENT = "#8e3b2a"
HEAT = ["#e9e2d2", "#d9b7a6", "#c1856f", "#a4553f", "#8e3b2a"]


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def fmt_sec(s) -> str:
    if not s:
        return "—"
    s = float(s)
    if s < 60:
        return f"{s:.0f} 秒"
    if s < 3600:
        return f"{s / 60:.1f} 分"
    return f"{s / 3600:.1f} 小时"


def fmt_n(n) -> str:
    return f"{n:,}"


# ---------------------------------------------------------------- 数据图

def _heatmap(stats: dict, profile: dict) -> str:
    """按天的活跃度：一行一周，一格一天。空白本身就是信息。"""
    days = stats.get("days") or {}
    if not days:
        return ""
    dates = sorted(days)
    d0 = dt.date.fromisoformat(dates[0])
    d1 = dt.date.fromisoformat(dates[-1])
    start = d0 - dt.timedelta(days=d0.weekday())
    total_days = (d1 - start).days + 1
    weeks = (total_days + 6) // 7

    counts = {d: v["me"] + v["other"] for d, v in days.items()}

    def level(n: int) -> int:
        if n == 0:
            return 0
        if n <= 3:
            return 1
        if n <= 9:
            return 2
        if n <= 29:
            return 3
        return 4

    CS, GAP = 9, 3.2
    W = weeks * (CS + GAP)
    H = 7 * (CS + GAP)
    cells, months = [], []
    last_month = None
    for i in range(total_days):
        d = start + dt.timedelta(days=i)
        col, row = i // 7, d.weekday()
        n = counts.get(d.isoformat(), 0)
        x = col * (CS + GAP)
        y = row * (CS + GAP)
        cells.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{CS}" height="{CS}" '
                     f'fill="{HEAT[level(n)]}"/>')
        if d.month != last_month and d.day <= 7 and col > 0:
            months.append(f'<text x="{x:.1f}" y="-6" class="hm-m">{d.month}月</text>')
            last_month = d.month
    return f"""
    <figure class="viz">
      <svg viewBox="0 0 {W} {H + 4}" role="img" aria-label="按天的消息活跃度">
        <g transform="translate(0,4)">{''.join(cells)}</g>
        <g>{''.join(months)}</g>
      </svg>
      <figcaption>每个方格是一天，从 {esc(dates[0])} 起共 {weeks} 周。
        空白的地方，是真的没有消息。</figcaption>
    </figure>"""


def _rhythm(stats: dict) -> str:
    """最忙的一天：按实际时间范围铺开的消息条，两行分人。"""
    r = stats.get("rhythm")
    if not r or not r.get("events"):
        return ""
    W, H, PAD = 640, 96, 34
    lane_h, gap = 24, 10
    ms = [e["m"] for e in r["events"]]
    lo, hi = min(ms), max(ms)
    if hi - lo < 40:
        hi = lo + 40
    span = hi - lo
    me_b, ot_b = [], []
    for e in r["events"]:
        x = PAD + (e["m"] - lo) / span * (W - 2 * PAD)
        w = max(2.0, e["n"] * 0.16)
        y = PAD if e["s"] == "me" else PAD + lane_h + gap
        rect = f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="{lane_h}"/>'
        (me_b if e["s"] == "me" else ot_b).append(rect)

    def hm(m):
        return f"{m // 60:02d}:{m % 60:02d}"

    ticks = "".join(
        f'<text x="{PAD + (t - lo) / span * (W - 2 * PAD):.1f}" y="{H - 2}" '
        f'class="hm-m" text-anchor="{anchor}">{hm(t)}</text>'
        for t, anchor in ((lo, "start"), ((lo + hi) // 2, "middle"), (hi, "end")))
    return f"""
    <figure class="viz">
      <svg viewBox="0 0 {W} {H}" role="img" aria-label="最忙一天的消息节奏">
        <g class="rh-me">{''.join(me_b)}</g>
        <g class="rh-ot">{''.join(ot_b)}</g>
        <text x="0" y="{PAD + 17}" class="hm-l">我</text>
        <text x="0" y="{PAD + lane_h + gap + 17}" class="hm-l o">对方</text>
        {ticks}
      </svg>
      <figcaption>{esc(r["date"])}，全天 {r["count"]} 条，从 {hm(lo)} 到 {hm(hi)}。
        一块是一条消息，宽度代表它有多长；同一行里的挤压，就是那天的追与等。</figcaption>
    </figure>"""


def _bars_row(label: str, me, other, fmt: str) -> str:
    me_n, other_n = (me or 0), (other or 0)
    top = max(me_n, other_n) or 1
    return f"""
    <div class="brow">
      <div class="bl">{esc(label)}</div>
      <div class="btrack">
        <i class="bme" style="width:{me_n / top * 100:.1f}%"></i>
        <i class="bother" style="width:{other_n / top * 100:.1f}%"></i>
      </div>
      <div class="bn"><span>{esc(fmt(me))}</span><span class="o">{esc(fmt(other))}</span></div>
    </div>"""


def _spark(stats: dict) -> str:
    wk = stats.get("latency_by_week") or {}
    weeks = sorted(wk)
    if len(weeks) < 2:
        return ""
    W, H, PAD = 640, 150, 24
    series = {}
    for key in ("me", "other"):
        series[key] = [(w, float(wk[w][key])) for w in weeks if wk[w].get(key)]
    all_v = [v for pts in series.values() for _, v in pts]
    if not all_v:
        return ""
    vmin, vmax = min(all_v), max(all_v)
    if vmax == vmin:
        vmax = vmin + 1
    idx = {w: i for i, w in enumerate(weeks)}

    def xy(w, v):
        x = PAD + idx[w] / (len(weeks) - 1) * (W - 2 * PAD)
        y = H - PAD - (v - vmin) / (vmax - vmin) * (H - 2 * PAD)
        return x, y

    def path(pts):
        return " ".join(f"{'M' if i == 0 else 'L'}{xy(w, v)[0]:.1f},{xy(w, v)[1]:.1f}"
                        for i, (w, v) in enumerate(pts))

    def dots(pts):
        return "".join(f'<circle cx="{xy(w, v)[0]:.1f}" cy="{xy(w, v)[1]:.1f}" r="3"/>'
                       for w, v in pts)

    return f"""
    <figure class="viz">
      <svg viewBox="0 0 {W} {H}" role="img" aria-label="回复速度按周变化">
        <path class="line me" d="{path(series['me'])}"/>
        <path class="line other" d="{path(series['other'])}"/>
        <g class="dot me">{dots(series['me'])}</g>
        <g class="dot other">{dots(series['other'])}</g>
        <text x="{PAD}" y="14" class="hm-m">{esc(fmt_sec(vmax))}</text>
        <text x="{PAD}" y="{H - 6}" class="hm-m">{esc(weeks[0][5:])}</text>
        <text x="{W - PAD}" y="{H - 6}" class="hm-m" text-anchor="end">{esc(weeks[-1][5:])}</text>
      </svg>
      <figcaption>会话内换手中位数，越低越快。红线是对方。</figcaption>
    </figure>"""



def _title_class(title: str) -> str:
    """中文字按 1 个宽度、拉丁字母按 0.55 估算；超过 10 就往下降一档。"""
    w = 0.0
    for ch in title:
        w += 1.0 if ord(ch) > 0x2E80 else 0.55
    return "h1-long" if w > 10 else ""


# ---------------------------------------------------------------- 版块

def _verdict(v: dict) -> str:
    conf = v.get("confidence")
    fw = v.get("framework") or []
    support = "".join(
        f'<li><span class="d">{esc(e.get("date",""))}</span>'
        f'<q>{esc(e.get("quote",""))}</q>'
        f'<span class="why">{esc(e.get("why",""))}</span></li>'
        for e in v.get("support", []))
    against = "".join(
        f'<li><span class="d">{esc(e.get("date",""))}</span>'
        f'<q>{esc(e.get("quote",""))}</q>'
        f'<span class="why">{esc(e.get("why",""))}</span></li>'
        for e in v.get("against", []))
    alt_txt = (v.get("alt", "") or "").strip()
    if alt_txt and not alt_txt.startswith("另一种解释"):
        alt_txt = "另一种解释：" + alt_txt
    alt = (f'<p class="alt">{esc(alt_txt)}</p>' if alt_txt else "")
    line = (f'<p class="pull">{esc(v["verdict_line"])}</p>'
            if v.get("verdict_line") else "")
    fw_html = (f'<p class="fw">{" · ".join(esc(x) for x in fw)}</p>' if fw else "")
    return f"""
    <article class="verdict">
      <h2>{esc(v["q"])}</h2>
      <p class="v-score">{esc(v["score"])}{
        f'<span class="conf">置信度 {esc(conf)}</span>' if conf else ""}</p>
      {fw_html}
      <p class="answer">{esc(v["answer"])}</p>
      <div class="ev">
        <div class="ev-col"><h3>支持</h3><ul>{support}</ul></div>
        <div class="ev-col"><h3>反方向</h3><ul>{against}</ul></div>
      </div>
      {alt}
      {line}
    </article>"""


# ---------------------------------------------------------------- 主模板

def build(stats: dict, profile: dict, kw: dict, an: dict, masked: bool = True) -> str:
    m = an["meta"]
    s = stats["senders"]
    ses = stats["sessions"]
    lat = stats["latency"]
    other_label = "对方" if masked else (m.get("other_name") or "对方")

    verdicts = "".join(_verdict(v) for v in an.get("verdicts", []))

    fw_items = "".join(
        f'<li><b>{esc(f.get("name",""))}</b>：{esc(f.get("why",""))}</li>'
        for f in (an.get("frameworks_used") or []))

    phases = "".join(
        f'<tr><td class="ph-range">{esc(p["range"])}</td>'
        f'<td class="ph-label">{esc(p["label"])}</td>'
        f'<td>{esc(p["note"])}</td></tr>'
        for p in an.get("phases", []))

    flags = "".join(
        f'<tr><td>{esc(r["behavior"])}</td><td class="num">{esc(r["count"])}</td>'
        f'<td>{esc(r["evidence"])}</td>'
        f'<td><span class="sev s{esc(r["severity"])}">{esc(r["severity"])}</span></td>'
        f'<td class="fwk">{esc(r.get("framework","—"))}</td></tr>'
        for r in an.get("red_flags", []))

    def _pattern(p: dict) -> str:
        fw = p.get("framework")
        k = f'<p class="k">{esc(fw)}</p>' if fw else ""
        return (f'<div class="pattern"><h3>{esc(p["name"])}</h3>{k}'
                f'<p>{esc(p["desc"])}</p></div>')

    patterns = "".join(_pattern(p) for p in an.get("patterns", []))
    advice = "".join(f"<li>{esc(a['text'])}</li>" for a in an.get("advice", []))
    limits = "".join(f"<li>{esc(x)}</li>" for x in an.get("limits", []))

    pulls = "".join(
        f'<blockquote><p>{esc(v.get("verdict_line",""))}</p>'
        f'<cite>{esc(v["q"])}</cite></blockquote>'
        for v in an.get("verdicts", []) if v.get("verdict_line"))

    level_text = {"ok": "可以做趋势判断", "descriptive": "样本偏少，只做描述",
                  "unusable": "样本不足"}.get(profile.get("level"), "—")
    warns = "".join(f"<li>{esc(w)}</li>" for w in profile.get("warnings", []))

    doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(m["title"])}</title>
<style>
:root{{
  --paper:#f2f0eb; --ink:#17150f; --muted:#6a6357; --rule:#d9d6cc; --accent:#8e3b2a;
  --on-dark:#b8ae9c;
  --t1:68px; --t2:36px; --t3:24px; --t4:18px; --t5:16px; --t6:13px;
  --serif:"Songti SC","Noto Serif SC","Source Han Serif SC",Georgia,serif;
  --sans:"Inter","Helvetica Neue","PingFang SC","Microsoft YaHei",sans-serif;
  --measure:54rem;
}}
*{{box-sizing:border-box}}
html{{-webkit-text-size-adjust:100%}}
body{{margin:0;background:var(--paper);color:var(--ink);font-family:var(--serif);
  font-size:var(--t4);line-height:1.75}}
main{{max-width:var(--measure);margin:0 auto;padding:52px 32px 88px}}
q,cite,em{{font-style:normal}}

h1{{font-size:clamp(44px,7vw,var(--t1));line-height:1.04;letter-spacing:-.025em;
  margin:0 0 22px;font-weight:600}}
h1.h1-long{{font-size:clamp(34px,4.8vw,50px);line-height:1.12}}
.lede{{font-size:var(--t3);line-height:1.5;margin:0 0 34px;max-width:24em}}
.meta{{font-family:var(--sans);font-size:var(--t6);color:var(--muted);margin:0;
  line-height:1.9;max-width:40em}}

section{{margin:56px 0 0}}
.sec{{font-size:var(--t3);line-height:1.35;font-weight:600;margin:0 0 30px}}

.verdict{{margin:0 0 46px}}
.verdict:last-child{{margin-bottom:0}}
.verdict h2{{font-size:var(--t2);line-height:1.18;margin:0 0 10px;letter-spacing:-.02em;font-weight:600}}
.v-score{{font-family:var(--sans);font-size:var(--t5);color:var(--accent);
  margin:0 0 6px;display:flex;gap:14px;align-items:baseline;flex-wrap:wrap}}
.conf{{font-size:var(--t6);color:var(--muted)}}
.fw{{font-family:var(--sans);font-size:var(--t6);color:var(--muted);margin:0 0 20px}}
.answer{{font-size:var(--t4);line-height:1.72;margin:0 0 28px;max-width:36em}}
.ev{{display:grid;grid-template-columns:1fr 1fr;gap:0 44px}}
.ev h3{{font-family:var(--sans);font-size:var(--t6);color:var(--muted);margin:0 0 12px;font-weight:500}}
.ev ul{{list-style:none;margin:0;padding:0}}
.ev li{{padding:0 0 20px;font-size:var(--t5);line-height:1.65}}
.ev li:last-child{{padding-bottom:0}}
.ev .d{{font-family:var(--sans);font-size:var(--t6);color:var(--accent);margin-right:8px}}
.ev q{{display:block;margin:2px 0 3px;color:#241f18}}
.ev q::before{{content:'「'}} .ev q::after{{content:'」'}}
.ev .why{{display:block;color:var(--muted);font-size:var(--t5)}}
.alt{{background:#e9e6de;padding:18px 22px;font-size:var(--t5);line-height:1.7;margin:24px 0 0}}
.pull{{font-size:var(--t3);line-height:1.5;margin:28px 0 0;padding-left:20px;
  border-left:3px solid var(--accent)}}

.stats{{display:flex;flex-wrap:wrap;gap:26px 52px;margin:0 0 32px}}
.stat-n{{font-family:var(--sans);font-size:var(--t2);line-height:1;letter-spacing:-.03em;
  font-variant-numeric:tabular-nums}}
.stat-l{{font-family:var(--sans);font-size:var(--t6);color:var(--muted);margin-top:8px}}
.stat-s{{font-family:var(--sans);font-size:var(--t6);color:var(--muted);margin-top:1px}}
.brow{{display:grid;grid-template-columns:5rem 1fr 3.6rem;gap:16px;align-items:center;padding:11px 0}}
.bl{{font-family:var(--sans);font-size:var(--t6);color:var(--muted)}}
.btrack i{{display:block;height:12px}}
.bme{{background:var(--ink);margin-bottom:3px}}
.bother{{background:var(--accent)}}
.bn{{font-family:var(--sans);font-size:var(--t6);color:var(--muted);
  font-variant-numeric:tabular-nums;text-align:right;line-height:1.45}}
.bn span{{display:block}} .bn .o{{color:var(--accent)}}
.viz{{margin:32px 0 0}}
.viz svg{{width:100%;height:auto;display:block}}
.viz figcaption{{font-family:var(--sans);font-size:var(--t6);color:var(--muted);
  margin-top:12px;line-height:1.6}}
.hm-m{{font-family:var(--sans);font-size:11px;fill:var(--muted)}}
.hm-l{{font-family:var(--sans);font-size:11px;fill:var(--ink)}}
.hm-l.o{{fill:var(--accent)}}
.rh-me rect{{fill:var(--ink)}} .rh-ot rect{{fill:var(--accent)}}
.line{{fill:none;stroke-width:1.8}}
.line.me{{stroke:#a89d8a}} .line.other{{stroke:var(--accent)}}
.dot.me circle{{fill:#a89d8a}} .dot.other circle{{fill:var(--accent)}}

.field{{width:100vw;margin-left:calc(50% - 50vw);background:var(--ink);color:var(--paper);
  padding:64px 0}}
.field-inner{{max-width:var(--measure);margin:0 auto;padding:0 32px}}
.field .sec{{color:var(--paper);margin-bottom:40px}}
.field blockquote{{margin:0 0 44px}}
.field blockquote:last-child{{margin-bottom:0}}
.field p{{font-size:var(--t2);line-height:1.42;margin:0 0 12px;letter-spacing:-.015em;max-width:26em}}
.field p::before{{content:'“';color:var(--accent)}} .field p::after{{content:'”';color:var(--accent)}}
.field cite{{font-family:var(--sans);font-size:var(--t6);color:var(--on-dark)}}

.phases{{width:100%;border-collapse:collapse;table-layout:fixed}}
.phases col.c1{{width:26%}} .phases col.c2{{width:14%}}
.phases td{{padding:16px 14px 16px 0;border-top:1px solid var(--rule);vertical-align:top}}
.phases tr:last-child td{{border-bottom:1px solid var(--rule)}}
.phases td.ph-range{{font-family:var(--sans);font-size:var(--t6);color:var(--muted)}}
.phases td.ph-label{{font-size:var(--t5);font-weight:600}}
.phases td:last-child{{font-size:var(--t5);line-height:1.65;color:#39332a}}

table.flags{{width:100%;border-collapse:collapse;font-size:var(--t6);table-layout:fixed}}
table.flags col.c-beh{{width:25%}} table.flags col.c-num{{width:7%}}
table.flags col.c-evi{{width:30%}} table.flags col.c-sev{{width:10%}} table.flags col.c-fwk{{width:28%}}
table.flags th{{font-family:var(--sans);font-size:var(--t6);color:var(--muted);text-align:left;font-weight:500;padding:0 10px 10px 0;border-bottom:1px solid var(--rule);white-space:nowrap}}
table.flags td{{padding:12px 10px 12px 0;border-bottom:1px solid var(--rule);vertical-align:top}}
table.flags td.num{{font-family:var(--sans);font-variant-numeric:tabular-nums}}
table.flags td.fwk{{font-family:var(--sans);font-size:var(--t6);color:var(--muted)}}
.sev{{font-family:var(--sans);font-size:var(--t6);padding:2px 7px;background:#e7dfcd}}
.sev.s高{{background:var(--accent);color:var(--paper)}}
.sev.s中{{background:#d9c3a1}}
.sev.s低{{background:#e2dbca;color:var(--muted)}}

.pattern{{padding:32px 0 0}}
.pattern h3{{margin:0 0 4px;font-size:var(--t5);font-weight:600}}
.pattern .k{{font-family:var(--sans);font-size:var(--t6);color:var(--muted);margin:0 0 10px}}
.pattern p:last-child{{margin:0;font-size:var(--t5);line-height:1.7;color:#2f2b24}}
ol.advice{{margin:0;padding-left:1.2em}}
ol.advice li{{margin:0 0 16px;font-size:var(--t5);line-height:1.7}}
.notes{{font-size:var(--t6);color:var(--muted);line-height:1.7}}
.notes h3{{font-family:var(--sans);font-size:var(--t6);font-weight:500;color:var(--muted);margin:24px 0 8px}}
.notes ul{{margin:0;padding-left:1.1em}}
.notes li{{margin:0 0 6px}}

@media (prefers-reduced-motion: no-preference){{
  .js-on .verdict, .js-on .pattern, .js-on .field blockquote, .js-on .viz,
  .js-on .phases, .js-on table.flags, .js-on ol.advice{{transition:opacity .55s ease,
    transform .55s ease}}
  .js-on .is-out{{opacity:0;transform:translateY(16px)}}
}}
footer{{margin-top:56px;font-family:var(--sans);font-size:var(--t6);color:var(--muted);
  display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}}

@media (max-width:900px){{
  main{{padding:44px 20px 80px}}
  h1{{font-size:clamp(30px,8.4vw,44px)}}
  section{{margin-top:64px}}
  .ev{{grid-template-columns:1fr;gap:26px}}
  .brow{{grid-template-columns:4rem 1fr 3.2rem;gap:10px}}
  .field{{padding:56px 0}}
  .stats{{gap:26px 40px}}
  .field p{{font-size:var(--t3)}}
  .verdict h2{{font-size:var(--t3)}}
}}
@media print{{
  :root{{--paper:#fff}}
  body{{font-size:11pt}}
  main{{max-width:none;padding:0}}
  .field{{width:auto;margin:0;background:#fff;color:#000;padding:24px 0}}
  .field .sec,.field p,.field cite{{color:#000}}
  .verdict,.pattern,.phases tr{{break-inside:avoid}}
  section{{margin-top:28px}}
}}
</style>
</head>
<body>
<main>

<header class="cover">
  <h1 class="{_title_class(m["title"])}">{esc(m["title"])}</h1>
  <p class="lede">{esc(m["one_line"])}</p>
  <p class="meta">与{esc(other_label)} · {esc(m["period"])} ·
    {fmt_n(profile.get("total", 0))} 条消息 · {profile.get("days", 0)} 天有记录 ·
    {ses.get("count", 0)} 段会话</p>
</header>

<section>
  {verdicts}
</section>

<section>
  <h2 class="sec">数字</h2>
  <div class="stats">
    <div><div class="stat-n">{fmt_n(profile.get("total", 0))}</div><div class="stat-l">条消息</div></div>
    <div><div class="stat-n">{ses.get("initiator", {}).get("me", 0)}<span style="font-size:.5em"> : </span>{ses.get("initiator", {}).get("other", 0)}</div><div class="stat-l">发起 · 我 : 对方</div></div>
    <div><div class="stat-n">{esc(fmt_sec(lat.get("me", {}).get("median")))}</div><div class="stat-l">我回复中位</div><div class="stat-s">对方 {esc(fmt_sec(lat.get('other', {}).get('median')))}</div></div>
    <div><div class="stat-n">{profile.get("days", 0)}</div><div class="stat-l">有消息的天</div><div class="stat-s">跨 {profile.get("span_days", 0)} 天</div></div>
  </div>
  {_bars_row("消息数", s["me"]["msgs"], s["other"]["msgs"], fmt_n)}
  {_bars_row("发起会话", ses["initiator"].get("me", 0), ses["initiator"].get("other", 0), fmt_n)}
  {_bars_row("连发次数", stats.get("streaks", {}).get("me", {}).get("double_text", 0),
             stats.get("streaks", {}).get("other", {}).get("double_text", 0), fmt_n)}
  {_heatmap(stats, profile)}
  {_rhythm(stats)}
</section>

<div class="field">
  <div class="field-inner">
    <h2 class="sec">原话</h2>
    {pulls}
  </div>
</div>

<section>
  <h2 class="sec">走势</h2>
  <table class="phases">
    <colgroup><col class="c1"><col class="c2"></colgroup>
    <tbody>{phases}</tbody>
  </table>
  {_spark(stats)}
</section>

<section>
  <h2 class="sec">红旗</h2>
  <table class="flags">
    <colgroup><col class="c-beh"><col class="c-num"><col class="c-evi"><col class="c-sev"><col class="c-fwk"></colgroup>
    <thead><tr><th>行为</th><th>次数</th><th>出处</th><th>程度</th><th>框架</th></tr></thead>
    <tbody>{flags}</tbody>
  </table>
</section>

<section>
  <h2 class="sec">模式</h2>
  {patterns}
</section>

<section>
  <h2 class="sec">建议</h2>
  <ol class="advice">{advice}</ol>
</section>

<section class="notes">
  <h2 class="sec">框架与局限</h2>
  <h3>用到的框架</h3>
  <ul>{fw_items}</ul>
  <h3>这份分析看不到什么</h3>
  <ul>{limits}</ul>
  <h3>数据提示</h3>
  <ul>{warns or "<li>无</li>"}</ul>
  <h3>方法</h3>
  <ul>
    <li>数字由脚本从聊天记录直接计算；判断由模型基于原文与上述框架给出。</li>
    <li>每条引用逐字比对原文，找不到的不会出现在报告里。</li>
    <li>框架来自公开的亲密关系研究，样本以西方已婚异性恋夫妻为主，跨文化适用性有限。</li>
    <li>探索性分析，不是心理诊断，也不能替你做出决定。</li>
  </ul>
</section>

<footer>
  <span>chat-log-analysis · {esc(m["period"])}</span>
  <span>本地生成 · 原文未上传</span>
</footer>

</main>
<script>
(function(){{
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  var els = [].slice.call(document.querySelectorAll('.verdict,.pattern,.field blockquote,.viz,.phases,table.flags,ol.advice'));
  if (!('IntersectionObserver' in window) || !els.length) return;
  document.body.classList.add('js-on');
  els.forEach(function(el){{ el.classList.add('is-out'); }});
  var io = new IntersectionObserver(function(entries){{
    entries.forEach(function(e){{
      if (e.isIntersecting) {{ e.target.classList.remove('is-out'); io.unobserve(e.target); }}
    }});
  }}, {{threshold:0.12, rootMargin:'0px 0px -8% 0px'}});
  els.forEach(function(el){{ io.observe(el); }});
}})();
</script>
</body>
</html>
"""
    if masked and m.get("other_name"):
        doc = doc.replace(esc(m["other_name"]), "对方").replace(m["other_name"], "对方")
    return doc
