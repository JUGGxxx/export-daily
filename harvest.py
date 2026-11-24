#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
出口报关知识库采集脚本（每日自动更新）
=====================================
数据源：
1. 海关归类预裁定决定书（gss.customs.gov.cn，官方开放接口，无反爬）
   - 列表接口: POST /CLSouter2020/Search/GetQuerySearchList
   - 详情页:   /CLSouter2020/Home/ClassifyDisplayYCD?SourceGuid=xxx
   - 每条决定书自动排版生成 PDF 归档到 rulings_pdf/
2. 商务部政策发布（mofcom.gov.cn，可直接抓取）
   - 列表页:   /zwgk/zcfb/index.html
   - 输出汇总到 policies/mofcom/
3. 海关总署公告（www.customs.gov.cn，官网有瑞数反爬，需浏览器渲染抓取）
   - 本脚本内置 Playwright(xvfb 有头模式) 抓取列表
   - 输出汇总到 policies/customs/

用法：
    python3 harvest.py --mode init          # 首次全量回填（预裁定全部 2000+ 条）
    python3 harvest.py --mode daily         # 每日增量（只抓新增）
    python3 harvest.py --rulings-pages 3    # 只抓预裁定前 3 页（测试用）
输出：
    rulings_pdf/   每份预裁定决定书一个 PDF（编号_税号.pdf）
    policies/      政策汇总（JSON + Markdown）
    state.json     已归档记录（增量去重）
    index.csv      全量索引清单
"""
import argparse
import csv
import html as html_mod
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
GSS_HOST = "http://gss.customs.gov.cn"
SEARCH_API = GSS_HOST + "/CLSouter2020/Search/GetQuerySearchList"
SEARCH_PAGE = GSS_HOST + "/clsouter2020/Home/ClassifyYCDSearch"
DETAIL_URL = GSS_HOST + "/CLSouter2020/Home/ClassifyDisplayYCD"
MOFCOM_LIST = "https://www.mofcom.gov.cn/zwgk/zcfb/index.html"
MOFCOM_API = ("https://www.mofcom.gov.cn/api-gateway/jpaas-publish-server/"
              "front/page/build/unit")
MOFCOM_QUERY = {
    "parseType": "bulidstatic",
    "webId": "8f43c7ad3afc411fb56f281724b73708",
    "tplSetId": "52551ea0e2c14bca8c84792f7aa37ead",
    "pageType": "column",
    "tagId": "分页列表",
    "editType": "null",
    "pageId": "fc8bdff48fa345a48b651c1285b70b8f",
}

# 中国出口管制信息网（商务部主办）—— 两用物项出口管制清单的官方发布渠道
EC_BASE = "https://exportcontrol.mofcom.gov.cn"
EC_API = EC_BASE + "/edi_ecms_web_front/front/column/getColumnList"
EC_COLUMNS = {15: "管制清单公告", 9: "两用物项清单/目录", 1: "国内动态"}
CUSTOMS_LIST = "http://www.customs.gov.cn/customs/302249/302266/index.html"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

PDF_DIR = os.path.join(BASE, "rulings_pdf")
POLICY_DIR = os.path.join(BASE, "policies")
STATE_FILE = os.path.join(BASE, "state.json")
INDEX_FILE = os.path.join(BASE, "index.csv")


# ---------------------------------------------------------------- 预裁定决定书
def get_session():
    """获取会话：GET 查询页拿 anti-forgery token + cookie"""
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    r = s.get(SEARCH_PAGE, timeout=30)
    r.raise_for_status()
    m = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', r.text)
    if not m:
        raise RuntimeError("未获取到 __RequestVerificationToken，页面结构可能已变化")
    return s, m.group(1)


def list_rulings(sess, token, page=1, page_size=50):
    """查询归类预裁定决定书列表（POST JSON API）"""
    r = sess.post(SEARCH_API, timeout=30, headers={
        "X-Requested-With": "XMLHttpRequest",
        "Referer": SEARCH_PAGE,
    }, data={
        "__RequestVerificationToken": token,
        "page": page, "pageSize": page_size, "Type": "YCD",
        "SourceNo": "", "GName": "", "CodeTS": "", "GMdel": "",
        "EngName": "", "OtherName": "", "IsXiao": "",
    })
    r.raise_for_status()
    return r.json()  # {"total": n, "data": [...]}


def _clean_date(v):
    """ASP.NET /Date(ms)/ -> 日期字符串；空值返回空串"""
    if not v:
        return ""
    m = re.search(r"\((-?\d+)\)", str(v))
    if not m:
        return ""
    ms = int(m.group(1))
    if ms <= 0:
        return ""
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")


def fetch_detail(sess, guid):
    """抓取决定书详情页并解析字段"""
    r = sess.get(DETAIL_URL, params={"SourceGuid": guid}, timeout=30)
    r.raise_for_status()
    t = r.text
    text = re.sub(r"<script.*?</script>", "", t, flags=re.S)

    def field(label):
        # 形如  <td>相关编号：</td><td>R-2-...</td> 或 span 结构，用宽松正则
        m = re.search(label + r"[：:]\s*</[^>]+>\s*<[^>]+>([^<]+)", text)
        return html_mod.unescape(m.group(1)).strip() if m else ""

    return {
        "编号": field("相关编号"),
        "决定税号": field("决定税号"),
        "商品名称中文": field("商品名称（中文）"),
        "商品名称英文": field("商品名称（英文）"),
        "商品名称其他": field("商品名称（其他）"),
        "商品描述": field("商品描述"),
        "发布单位": field("发布单位"),
    }


PDF_TEMPLATE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
  body {{ font-family: "Noto Sans CJK SC", sans-serif; margin: 48px; color:#222; }}
  h1 {{ font-size: 22px; text-align:center; border-bottom: 2px solid #1a5276;
       padding-bottom: 12px; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 24px; }}
  td {{ border: 1px solid #999; padding: 10px 14px; vertical-align: top;
        font-size: 13px; }}
  td.k {{ background: #eaf2f8; width: 140px; font-weight: bold; white-space: nowrap; }}
  .meta {{ color:#666; font-size:11px; margin-top:28px; text-align:center; }}
</style></head><body>
<h1>中华人民共和国海关预裁定决定书（归类）</h1>
<table>
  <tr><td class="k">相关编号</td><td>{no}</td></tr>
  <tr><td class="k">决定税号</td><td>{ts}</td></tr>
  <tr><td class="k">商品名称（中文）</td><td>{gcn}</td></tr>
  <tr><td class="k">商品名称（英文）</td><td>{gen}</td></tr>
  <tr><td class="k">商品名称（其他）</td><td>{goth}</td></tr>
  <tr><td class="k">商品描述</td><td>{desc}</td></tr>
  <tr><td class="k">发布单位</td><td>{dept}</td></tr>
</table>
<p class="meta">来源：海关进出口商品归类系统（gss.customs.gov.cn）　　归档时间：{now}<br>
详情页：{detail_link}</p>
</body></html>"""


def save_ruling_pdf(sess, guid, row, pdf_dir=PDF_DIR):
    """抓详情 -> 生成 PDF，返回 (pdf_path, detail_dict)"""
    os.makedirs(pdf_dir, exist_ok=True)
    detail = fetch_detail(sess, guid)
    no = row.get("SOURCE_NO") or detail["编号"] or guid
    ts = row.get("CODE_TS") or detail["决定税号"] or ""
    fname = re.sub(r"[^\w.-]", "_", f"{no}_{ts}.pdf")
    path = os.path.join(pdf_dir, fname)

    html_txt = PDF_TEMPLATE.format(
        no=detail["编号"] or no, ts=detail["决定税号"] or ts,
        gcn=detail["商品名称中文"], gen=detail["商品名称英文"],
        goth=detail["商品名称其他"], desc=detail["商品描述"],
        dept=detail["发布单位"], now=datetime.now().strftime("%Y-%m-%d %H:%M"),
        detail_link=f"{DETAIL_URL}?SourceGuid={guid}")
    tmp_html = path + ".tmp.html"
    with open(tmp_html, "w", encoding="utf-8") as f:
        f.write(html_txt)
    from weasyprint import HTML
    HTML(filename=tmp_html).write_pdf(path)
    os.remove(tmp_html)
    return path, detail


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"rulings": {}, "mofcom": {}, "customs": {}, "exportcontrol": {}, "last_run": None}


def save_state(st):
    st["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def harvest_rulings(max_pages=None, page_size=50, state=None, new_only=True):
    """抓取预裁定决定书列表+详情+PDF。返回新增记录列表。"""
    sess, token = get_session()
    first = list_rulings(sess, token, 1, page_size)
    total = first["total"]
    pages = max_pages or -(-total // page_size)
    rows = list(first["data"])
    for p in range(2, pages + 1):
        rows += list_rulings(sess, token, p, page_size)["data"]
        time.sleep(0.5)
    print(f"[预裁定] 共 {total} 条，本次拉取 {len(rows)} 条")

    out = []
    for row in rows:
        guid = row["SOURCE_GUID"]
        no = row.get("SOURCE_NO") or guid
        if new_only and guid in state["rulings"]:
            continue
        try:
            path, detail = save_ruling_pdf(sess, guid, row)
        except Exception as e:
            print(f"  ! {no} 失败: {e}")
            continue
        rec = {
            "SOURCE_GUID": guid,
            "编号": no,
            "决定税号": row.get("CODE_TS") or detail["决定税号"],
            "商品名称": detail["商品名称中文"] or row.get("G_NAME") or "",
            "规格型号": row.get("G_MODEL") or "",
            "发布单位": detail["发布单位"] or row.get("DEPARTMENT") or "",
            "生效日期": _clean_date(row.get("INURE_TIME")),
            "失效日期": _clean_date(row.get("EXPIRE_TIME")),
            "失效原因": row.get("EXPIRE_REASON") or "",
            "PDF文件": os.path.basename(path),
            "详情页URL": f"{DETAIL_URL}?SourceGuid={guid}",
        }
        state["rulings"][guid] = rec
        out.append(rec)
        print(f"  + {no} {rec['商品名称'][:20]} -> {rec['PDF文件']}")
        time.sleep(0.4)
    return out


# ---------------------------------------------------------------- 商务部政策
def harvest_mofcom(state, max_items=20):
    """商务部政策发布列表（jpaas 数据接口，需带 Referer）"""
    r = requests.get(MOFCOM_API, params=MOFCOM_QUERY, timeout=30, verify=False,
                     headers={"User-Agent": UA, "Referer": MOFCOM_LIST})
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    r.raise_for_status()
    html = r.json()["data"]["html"]
    items, seen = [], set()
    for m in re.finditer(r'href="([^"]+art[^"]+\.html)"[^>]*title="([^"]+)"', html):
        url = m.group(1)
        if url.startswith("/"):
            url = "https://www.mofcom.gov.cn" + url
        title = html_mod.unescape(m.group(2)).strip()
        if url not in seen and url not in state["mofcom"]:
            seen.add(url)
            items.append({"标题": title, "URL": url,
                          "栏目": "商务部政策发布",
                          "抓取日期": str(date.today())})
    for it in items[:max_items]:
        state["mofcom"][it["URL"]] = it
        print(f"  + [商务部] {it['标题'][:38]}")
    return items[:max_items]


# ---------------------------------------------------------------- 海关总署公告
def harvest_exportcontrol(state, max_items=20):
    """中国出口管制信息网：两用物项清单公告/目录/动态（需模拟浏览器请求头，否则中文被服务端转问号）"""
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    s.verify = False
    try:
        s.get(EC_BASE + "/", timeout=20)
    except Exception:
        pass
    items, seen = [], set()
    for cid, cname in EC_COLUMNS.items():
        try:
            r = s.post(EC_API, data={"pageNumber": 1, "columnID": cid, "title": ""},
                       headers={"X-Requested-With": "XMLHttpRequest",
                                "Referer": f"{EC_BASE}/articleList.shtml?columnID={cid}&num=1",
                                "Origin": EC_BASE,
                                "Accept": "application/json, text/javascript, */*; q=0.01"},
                       timeout=20)
            rows = r.json()["pageInfo"]["rows"]
        except Exception as e:
            print(f"  ! [出口管制网] 栏目{cid} 抓取失败: {str(e)[:80]}")
            continue
        for row in rows:
            url = row.get("url", "")
            if url.startswith("/"):
                url = EC_BASE + url
            if url in seen or url in state["exportcontrol"]:
                continue
            seen.add(url)
            items.append({"标题": (row.get("title") or "").strip(),
                          "URL": url,
                          "栏目": f"出口管制信息网·{cname}",
                          "日期": (row.get("publishTimeStr") or "")[:10],
                          "抓取日期": str(date.today())})
    for it in items[:max_items]:
        state["exportcontrol"][it["URL"]] = it
        print(f"  + [管制] {it['栏目'].split('·')[1]} | {it['标题'][:36]}")

    # 管制清单公告类条目自动下载 PDF/文档附件归档
    att_dir = os.path.join(BASE, "export_policies_pdf")
    os.makedirs(att_dir, exist_ok=True)
    for it in items[:max_items]:
        if "管制清单公告" not in it["栏目"] or it["URL"] in state.get("exportcontrol_att", {}):
            continue
        try:
            r = s.get(it["URL"], timeout=20)
            r.encoding = "utf-8"
            m = re.search(r'href="([^"]+\.(?:pdf|xls|xlsx|doc|docx))"', r.text, re.I)
            if not m:
                continue
            att_url = m.group(1)
            if att_url.startswith("/"):
                att_url = EC_BASE + att_url
            ext = att_url.rsplit(".", 1)[1].lower()
            fname = re.sub(r"[^\w.-]", "_", it["标题"])[:80] + "." + ext
            path = os.path.join(att_dir, fname)
            if not os.path.exists(path):
                with s.get(att_url, timeout=60, stream=True) as fr:
                    fr.raise_for_status()
                    with open(path, "wb") as f:
                        for chunk in fr.iter_content(65536):
                            f.write(chunk)
            state.setdefault("exportcontrol_att", {})[it["URL"]] = fname
            it["附件"] = fname
            print(f"  + [附件] {fname[:50]}")
        except Exception as e:
            print(f"  ! 附件下载失败 {it['标题'][:30]}: {str(e)[:60]}")
    return items[:max_items]



PLAYWRIGHT_SNIPPET = r"""
import asyncio, json, sys
from playwright.async_api import async_playwright

URL = "{url}"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False,
            args=["--no-sandbox","--disable-blink-features=AutomationControlled"])
        ctx = await browser.new_context(
            user_agent="{ua}", viewport={{"width":1440,"height":900}}, locale="zh-CN")
        page = await ctx.new_page()
        for _ in range(3):
            try:
                await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
            await page.wait_for_timeout(6000)
            if len(await page.content()) > 5000:
                break
        links = await page.evaluate('''() => {{
            const out = [];
            document.querySelectorAll("a").forEach(a => {{
                const t = (a.innerText || "").trim();
                const h = a.href;
                if (t && h && h.includes("article_")) out.push({{title: t, url: h}});
            }});
            return out;
        }}''')
        print(json.dumps(links, ensure_ascii=False))
        await browser.close()

asyncio.run(main())
"""


def harvest_customs(state, max_items=20):
    """海关总署官网有瑞数反爬：用 playwright(xvfb 有头模式) 渲染抓列表"""
    os.makedirs("/tmp/kbtool", exist_ok=True)
    script = "/tmp/kbtool/customs_fetch.py"
    with open(script, "w", encoding="utf-8") as f:
        f.write(PLAYWRIGHT_SNIPPET.format(url=CUSTOMS_LIST, ua=UA))
    try:
        proc = subprocess.run(
            ["xvfb-run", "-a", sys.executable, script],
            capture_output=True, text=True, timeout=180)
        out = proc.stdout.strip()
        links = json.loads(out[out.index("["):]) if "[" in out else []
    except Exception as e:
        print(f"  ! 海关官网抓取失败（可改用自动化会话内的 WebFetch 渲染）: {e}")
        return []
    items, seen = [], set()
    for l in links:
        t = re.sub(r"\s+", "", l["title"])
        if not t or l["url"] in seen or l["url"] in state["customs"]:
            continue
        seen.add(l["url"])
        dm = re.search(r"(20\d\d-\d\d-\d\d)", t)
        items.append({"标题": t, "URL": l["url"], "栏目": "海关总署公告",
                      "日期": dm.group(1) if dm else "", "抓取日期": str(date.today())})
    for it in items[:max_items]:
        state["customs"][it["URL"]] = it
        print(f"  + [海关] {it['标题'][:38]}")
    return items[:max_items]


# ---------------------------------------------------------------- 索引输出
def write_index(all_rulings):
    cols = ["编号", "决定税号", "商品名称", "规格型号", "发布单位",
            "生效日期", "失效日期", "PDF文件", "详情页URL"]
    with open(INDEX_FILE, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for rec in sorted(all_rulings.values(), key=lambda r: r["编号"], reverse=True):
            w.writerow(rec)


def write_policy_summary(mofcom_new, customs_new, ec_new=()):
    """把本次新政策汇总成 Markdown 供知识库展示"""
    os.makedirs(POLICY_DIR, exist_ok=True)
    path = os.path.join(POLICY_DIR, f"政策更新_{date.today()}.md")
    lines = [f"# 出口报关政策更新（{date.today()}）\n"]
    if ec_new:
        lines.append("## 出口管制信息网（清单公告/目录/动态）\n")
        for it in ec_new:
            lines.append(f"- [{it['标题']}]({it['URL']}) {it.get('日期','')}")
        lines.append("")
    if customs_new:
        lines.append("## 海关总署公告\n")
        for it in customs_new:
            lines.append(f"- [{it['标题']}]({it['URL']}) {it.get('日期','')}")
        lines.append("")
    if mofcom_new:
        lines.append("## 商务部政策发布\n")
        for it in mofcom_new:
            lines.append(f"- [{it['标题']}]({it['URL']})")
        lines.append("")
    if len(lines) == 2:
        lines.append("今日无新增。")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["init", "daily"], default="daily")
    ap.add_argument("--rulings-pages", type=int, default=None,
                    help="只抓预裁定前 N 页（测试用）")
    ap.add_argument("--skip-customs", action="store_true")
    args = ap.parse_args()

    state = load_state()
    pages = args.rulings_pages
    if args.mode == "daily":
        pages = pages or 3  # 每天增量扫前 3 页即可覆盖当日新增

    print("== 采集归类预裁定决定书 ==")
    rulings_new = harvest_rulings(max_pages=pages, state=state,
                                  new_only=(args.mode == "daily"))

    print("== 采集商务部政策发布 ==")
    mofcom_new = harvest_mofcom(state)

    print("== 采集出口管制信息网 ==")
    ec_new = harvest_exportcontrol(state)

    print("== 采集海关总署公告 ==")
    customs_new = [] if args.skip_customs else harvest_customs(state)

    write_index(state["rulings"])
    summary = write_policy_summary(mofcom_new, customs_new, ec_new)
    save_state(state)
    print(f"\n完成：预裁定新增 PDF {len(rulings_new)} 份；"
          f"商务部新政策 {len(mofcom_new)} 条；海关新公告 {len(customs_new)} 条；"
          f"出口管制网 {len(ec_new)} 条")
    print(f"索引: {INDEX_FILE}\n汇总: {summary}")


if __name__ == "__main__":
    sys.exit(main())
