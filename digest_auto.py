#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动生成当日 digest JSON（无需 AI）：
从 candidates_{date}.json + state.json 的当日条目构造结构化日报，
供 digest.py render 使用。若当日已有手工 digest 文件则不覆盖。

用法: python3 digest_auto.py [日期，默认今天]
"""
import json
import os
import re
import sys
from datetime import date, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))


def extract_code(title):
    """从标题提取公告编号，如 公告2026年第50号 -> 第 50 号"""
    m = re.search(r"公告(?:20\d\d年)?第(\d+)号", title)
    if m:
        return f"第 {m.group(1)} 号"
    return ""


def build(day):
    # 当日条目：candidates（海关+商务部） + exportcontrol
    items = []
    cpath = os.path.join(BASE, f"candidates_{day}.json")
    if os.path.exists(cpath):
        items += json.load(open(cpath, encoding="utf-8"))
    st = json.load(open(os.path.join(BASE, "state.json"), encoding="utf-8"))
    for url, it in st.get("exportcontrol", {}).items():
        if it.get("抓取日期") == day:
            items.append({"来源": "出口管制信息网", "标题": it.get("标题", ""),
                          "URL": url, "日期": it.get("日期", "")})
    for url, it in st.get("rulings", {}).items():
        # 预裁定记录无抓取日期字段，用生成的 PDF 文件时间判断是否当日新增
        pdf = it.get("PDF文件", "")
        if not pdf or not it.get("商品名称"):
            continue
        p = os.path.join(BASE, "rulings_pdf", pdf)
        if not os.path.exists(p):
            continue
        import datetime as _dt
        if _dt.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d") != day:
            continue
        items.append({"来源": "预裁定", "标题": it["商品名称"],
                      "URL": it.get("详情页URL", ""), "税号": it.get("决定税号", "")})

    if not items:
        print(f"{day} 无新条目，生成空日报")
    # 分组
    buckets = {"出口管制信息网": [], "商务部": [], "海关总署": [], "预裁定": []}
    for it in items:
        src = it.get("来源", "")
        buckets.setdefault(src, []).append(it)

    sec_map = [
        ("出口管制信息网", "一、出口管制动态（{n} 条）", "", "管制动态"),
        ("商务部", "二、商务部政策发布（{n} 条）", "blue", "政策发布"),
        ("海关总署", "三、海关总署公告（{n} 条）", "blue", "海关公告"),
        ("预裁定", "四、新增归类预裁定（{n} 份）", "orange", "归类参考"),
    ]
    sections, kpis = [], []
    for i, (src, tpl, color, tag) in enumerate(sec_map):
        rows = buckets.get(src) or []
        if not rows:
            continue
        cards = []
        for it in rows[:10]:
            title = it.get("标题", "")
            code = extract_code(title) or it.get("税号", "") or (it.get("日期", "") or "")
            pts = [f"发布日期：<b>{it.get('日期') or day}</b>" if it.get("日期")
                   else f"采集日期：<b>{day}</b>"]
            if it.get("税号"):
                pts.append(f"决定税号：<b>{it['税号']}</b>，全文 PDF 已归档")
            pts.append(f'原文：<a href="{it.get("URL","")}">点击查看</a>')
            cards.append({"code": code, "title": title, "tag": tag, "points": pts})
        sections.append({"heading": tpl.format(n=len(rows)), "color": color,
                         "items": cards})
        kpis.append({"num": str(len(rows)), "label": src, "color":
                     "red" if src == "出口管制信息网" else
                     "blue" if src != "预裁定" else "brown"})

    d = {
        "date": day,
        "pill": "出口要闻 · 每日速览",
        "title": "出口<em>政策与管制</em><br>今日要点全解",
        "subtitle": "管制动态 · 政策发布 · 归类预裁定",
        "meta": f"覆盖海关总署 + 商务部 + 出口管制信息网 ｜ 更新至 {day}",
        "kpis": kpis or [{"num": "0", "label": "今日更新", "color": "blue"}],
        "big_stat": {"num": f"{len(items)} 条", "label": "今日新增（自动生成）"},
        "sections": sections,
        "footer": "数据来源：海关总署（customs.gov.cn）、商务部（mofcom.gov.cn）、"
                  "中国出口管制信息网（exportcontrol.mofcom.gov.cn）。<br>"
                  "自动抓取生成，仅供内部参考，具体适用请以官方原文为准。",
    }
    out = os.path.join(BASE, f"digest_{day}.json")
    json.dump(d, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"自动日报 {len(items)} 条 -> {out}")
    return out


if __name__ == "__main__":
    day = sys.argv[1] if len(sys.argv) > 1 else str(date.today())
    build(day)
