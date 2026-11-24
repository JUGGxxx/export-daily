#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
出口要闻日报 · 长图生成器
=========================
两步：
1) collect  : 从 state.json 筛出当日出口相关条目 -> candidates.json（供 AI 提炼要点）
2) render   : 读 digest.json（含 AI 提炼的要点）-> HTML -> PNG 长图

用法:
    python3 digest.py collect                 # 生成当日候选条目
    python3 digest.py render digest.json      # 渲染长图（输出 digest_YYYY-MM-DD.png）
"""
import html
import json
import os
import re
import sys
from datetime import date

BASE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(BASE, "state.json")

# 出口相关性关键词（命中即视为出口相关；进口检疫/反倾销等不计）
EXPORT_KEYS = ["出口管制", "两用物项", "出口许可", "出口配额", "出口关税", "出口退税",
               "原产地", "报关", "通关", "归类", "检验检疫", "自贸", "关税", "管制清单",
               "出口", "境外", "跨境"]
NOISE = ["微博", "微信", "热线", "网站地图", "关于我们"]


def collect(day=None):
    """筛出当日采集到的出口相关条目"""
    day = day or str(date.today())
    st = json.load(open(STATE, encoding="utf-8"))
    out = []
    for src, key in (("海关总署", "customs"), ("商务部", "mofcom")):
        for url, it in st.get(key, {}).items():
            title = it.get("标题", "")
            if any(n in title for n in NOISE):
                continue
            if it.get("抓取日期") and it["抓取日期"] != day:
                continue
            score = sum(1 for k in EXPORT_KEYS if k in title)
            if score:
                out.append({"来源": src, "标题": title, "URL": url,
                            "相关度": score, "抓取日期": it.get("抓取日期", "")})
    out.sort(key=lambda x: -x["相关度"])
    path = os.path.join(BASE, f"candidates_{day}.json")
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"出口相关候选 {len(out)} 条 -> {path}")
    return out


# ---------------------------------------------------------------- 渲染
HTML_TPL = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{width:1080px;font-family:"Noto Sans CJK SC","Noto Sans SC",sans-serif;
      background:#eef1f7;color:#1c2434;}}
.cover{{position:relative;background:linear-gradient(135deg,#12296b 0%,#1f47a8 55%,#2a5fd0 100%);
  padding:56px 52px 120px;overflow:hidden;}}
.cover:before{{content:"";position:absolute;inset:0;
  background-image:linear-gradient(rgba(255,255,255,.055) 1px,transparent 1px),
                   linear-gradient(90deg,rgba(255,255,255,.055) 1px,transparent 1px);
  background-size:54px 54px;}}
.cover:after{{content:"";position:absolute;width:620px;height:620px;border-radius:50%;
  right:-260px;top:-260px;background:rgba(255,255,255,.05);}}
.pill{{position:relative;display:inline-block;border:1px solid rgba(255,255,255,.55);
  color:#fff;font-size:22px;padding:9px 26px;border-radius:999px;letter-spacing:1px;}}
h1{{position:relative;margin-top:30px;font-size:62px;line-height:1.22;color:#fff;
    font-weight:800;letter-spacing:1px;}}
h1 em{{font-style:normal;color:#FFD24A;}}
.line{{position:relative;width:120px;height:6px;background:#FFD24A;margin:30px 0 26px;
       border-radius:3px;}}
.sub{{position:relative;font-size:25px;color:#dce6ff;line-height:1.5;}}
.meta{{position:relative;margin-top:14px;font-size:19px;color:#a9bdf0;}}
.kpis{{position:relative;display:flex;gap:20px;margin-top:40px;}}
.kpi{{flex:1;background:#fff;border-radius:18px;padding:26px 16px;text-align:center;
  box-shadow:0 8px 24px rgba(10,26,70,.18);}}
.kpi b{{display:block;font-size:56px;line-height:1.1;font-weight:800;}}
.kpi span{{display:block;margin-top:8px;font-size:19px;color:#5b6b8c;line-height:1.35;}}
.sum{{position:relative;margin-top:18px;background:#fff;border-radius:18px;padding:24px;
  text-align:center;box-shadow:0 8px 24px rgba(10,26,70,.18);}}
.sum b{{font-size:52px;color:#1f4fd8;font-weight:800;}}
.sum span{{display:block;margin-top:6px;font-size:19px;color:#5b6b8c;}}
.body{{padding:46px 52px 60px;}}
h2{{font-size:34px;font-weight:800;margin:14px 0 24px;padding-left:18px;
    border-left:8px solid #1f4fd8;line-height:1.3;}}
.card{{background:#fff;border-radius:16px;border-left:6px solid #2e9e5b;padding:26px 28px;
  margin-bottom:20px;box-shadow:0 4px 14px rgba(20,40,90,.07);}}
.card.blue{{border-left-color:#1f4fd8;}}
.card.orange{{border-left-color:#e08a1e;}}
.code{{display:inline-block;background:#e8f5ec;color:#1d7a45;font-size:20px;font-weight:700;
  padding:5px 14px;border-radius:8px;margin-right:12px;}}
.card h3{{display:inline;font-size:24px;font-weight:700;line-height:1.5;}}
.tag{{display:inline-block;margin-left:10px;background:#eef1f7;color:#61708f;font-size:17px;
  padding:4px 12px;border-radius:999px;vertical-align:middle;}}
.card ul{{margin:14px 0 0 6px;}}
.card li{{list-style:none;position:relative;padding-left:22px;font-size:20px;color:#3c4a63;
  line-height:1.62;margin-top:7px;}}
.card li:before{{content:"";position:absolute;left:4px;top:12px;width:8px;height:8px;
  border-radius:50%;background:#1f4fd8;}}
.card li b{{color:#1c2434;}}
.foot{{margin:34px 0 0;padding:22px 0 0;border-top:1px dashed #c9d3e6;font-size:17px;
  color:#7b88a3;line-height:1.7;}}
</style></head><body>
<div class="cover">
  <span class="pill">{pill}</span>
  <h1>{title}</h1>
  <div class="line"></div>
  <div class="sub">{subtitle}</div>
  <div class="meta">{meta}</div>
  <div class="kpis">{kpis}</div>
  <div class="sum"><b>{big_num}</b><span>{big_label}</span></div>
</div>
<div class="body">
{sections}
<div class="foot">{footer}</div>
</div>
</body></html>"""

KPI_COLORS = {"red": "#C0392B", "blue": "#1f4fd8", "brown": "#8a5a12", "green": "#1d7a45"}


def render(digest_path):
    d = json.load(open(digest_path, encoding="utf-8"))
    kpis = "".join(
        f'<div class="kpi"><b style="color:{KPI_COLORS.get(k.get("color","blue"))}">'
        f'{k["num"]}</b><span>{k["label"]}</span></div>' for k in d["kpis"])

    secs = []
    for s in d["sections"]:
        cards = []
        for it in s["items"]:
            pts = "".join(f"<li>{p}</li>" for p in it.get("points", []))
            tag = f'<span class="tag">{it["tag"]}</span>' if it.get("tag") else ""
            code = f'<span class="code">{it["code"]}</span>' if it.get("code") else ""
            cards.append(f'<div class="card {s.get("color","")}">{code}'
                         f'<h3>{it["title"]}</h3>{tag}<ul>{pts}</ul></div>')
        secs.append(f'<h2>{s["heading"]}</h2>' + "".join(cards))

    markup = HTML_TPL.format(
        pill=d["pill"], title=d["title"], subtitle=d["subtitle"], meta=d["meta"],
        kpis=kpis, big_num=d["big_stat"]["num"], big_label=d["big_stat"]["label"],
        sections="".join(secs), footer=d["footer"])

    html_path = os.path.join(BASE, "digest_tmp.html")
    open(html_path, "w", encoding="utf-8").write(markup)

    png = os.path.join(BASE, f"出口要闻日报_{d['date']}.png")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--no-sandbox"])
        pg = b.new_page(viewport={"width": 1080, "height": 1400}, device_scale_factor=2)
        pg.goto("file://" + html_path)
        pg.wait_for_timeout(600)
        pg.screenshot(path=png, full_page=True)
        b.close()
    os.remove(html_path)
    print(f"长图已生成: {png}")
    return png


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    if sys.argv[1] == "collect":
        collect(sys.argv[2] if len(sys.argv) > 2 else None)
    elif sys.argv[1] == "render":
        render(sys.argv[2])
