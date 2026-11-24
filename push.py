#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把出口要闻长图推送到微信（GitHub Actions 版）：
  serverchan  Server酱（推荐：免费5条/天、微信内接收）
  pushplus    PushPlus
  wecom       企业微信群机器人

图床：sm.ms（主） -> catbox.moe（备），匿名上传，无需配置。
配置（环境变量或项目目录 .webhook）：
    SERVERCHAN_KEY=SCTxxxx
    PUSHPLUS_TOKEN=xxxx
    WECOM_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
    KB_URL=https://...   # 可选
"""
import argparse
import base64
import hashlib
import json
import os

import requests
from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(BASE, ".webhook")


def conf(key, default=""):
    v = os.environ.get(key, "").strip()
    if v:
        return v
    if os.path.exists(CFG):
        for line in open(CFG, encoding="utf-8"):
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    return default


def _quiet_ssl():
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def shrink(path, limit_mb=4.5):
    if os.path.getsize(path) <= limit_mb * 1024 * 1024:
        return path
    im = Image.open(path).convert("RGB")
    out = path.rsplit(".", 1)[0] + "_s.jpg"
    im.save(out, "JPEG", quality=86, optimize=True)
    print(f"图片过大，已压缩: {os.path.getsize(out) / 1048576:.1f}MB")
    return out


def host_image(path, dest_name=None):
    """长图公网直链：
    GitHub Actions 内：提交到仓库 images/ 目录，走 jsDelivr CDN（国内可达、永久）
    本地运行：sm.ms（需匿名可用时） -> catbox.moe 兜底
    """
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    branch = os.environ.get("JSDELIVR_BRANCH", "main")
    name = dest_name or os.path.basename(path)
    if repo:
        url = f"https://cdn.jsdelivr.net/gh/{repo}@{branch}/images/{name}"
        print("图床: jsdelivr (repo:", repo + ")")
        return url
    img = shrink(path)
    try:
        r = requests.post("https://sm.ms/api/v2/upload",
                          files={"smfile": (name, open(img, "rb").read())},
                          headers={"User-Agent": "export-daily/1.0"},
                          timeout=90, verify=False)
        d = r.json()
        if d.get("success"):
            print("图床: sm.ms")
            return d["data"]["url"]
        if d.get("code") == "image_repeated" and d.get("images"):
            return d["images"]
        print("sm.ms 失败:", str(d)[:120])
    except Exception as e:
        print("sm.ms 异常:", str(e)[:100])
    r = requests.post("https://catbox.moe/user/api.php",
                      data={"reqtype": "fileupload"},
                      files={"fileToUpload": (name, open(img, "rb").read())},
                      headers={"User-Agent": "export-daily/1.0"},
                      timeout=120, verify=False)
    url = r.text.strip()
    if url.startswith("http"):
        print("图床: catbox.moe")
        return url
    raise SystemExit(f"图床上传失败，最后响应: {r.text[:120]}")


def push_serverchan(title, summary, img_url, kb_url):
    key = conf("SERVERCHAN_KEY")
    if not key:
        raise SystemExit("未配置 SERVERCHAN_KEY")
    _quiet_ssl()
    desp = summary + (f"\n\n![出口要闻日报]({img_url})" if img_url else "") \
        + (f"\n\n[查看完整知识库]({kb_url})" if kb_url else "")
    r = requests.post(f"https://sctapi.ftqq.com/{key}.send",
                      data={"title": title[:32], "desp": desp},
                      timeout=30, verify=False)
    print("serverchan:", r.status_code, r.text[:200])
    if r.json().get("code") != 0:
        raise SystemExit(f"Server酱推送失败: {r.text[:200]}")


def push_pushplus(title, summary, img_url, kb_url):
    token = conf("PUSHPLUS_TOKEN")
    if not token:
        raise SystemExit("未配置 PUSHPLUS_TOKEN")
    _quiet_ssl()
    html = (f'<p style="font-size:15px;line-height:1.7;">{summary}</p>'
            + (f'<p><img src="{img_url}" style="width:100%;border-radius:8px;"/></p>'
               if img_url else "")
            + (f'<p><a href="{kb_url}">查看完整知识库</a></p>' if kb_url else ""))
    r = requests.post("https://www.pushplus.plus/send", json={
        "token": token, "title": title, "content": html, "template": "html"},
        timeout=30, verify=False)
    print("pushplus:", r.status_code, r.text[:300])


def push_wecom(image, title, summary, kb_url):
    hook = conf("WECOM_WEBHOOK")
    if not hook:
        raise SystemExit("未配置 WECOM_WEBHOOK")
    _quiet_ssl()
    img = shrink(image, 1.8)
    raw = open(img, "rb").read()
    r = requests.post(hook, json={"msgtype": "image", "image": {
        "base64": base64.b64encode(raw).decode(),
        "md5": hashlib.md5(raw).hexdigest()}}, timeout=60, verify=False)
    print("图片:", r.text[:150])
    md = f"**{title}**\n{summary}" + (f"\n[查看完整知识库]({kb_url})" if kb_url else "")
    requests.post(hook, json={"msgtype": "markdown",
                              "markdown": {"content": md[:4000]}},
                  timeout=30, verify=False)


CHANNELS = {"serverchan": push_serverchan, "pushplus": push_pushplus,
            "wecom": push_wecom}


def detect_channel():
    for k in ("SERVERCHAN_KEY", "PUSHPLUS_TOKEN", "WECOM_WEBHOOK"):
        if conf(k):
            return {"SERVERCHAN_KEY": "serverchan", "PUSHPLUS_TOKEN": "pushplus",
                    "WECOM_WEBHOOK": "wecom"}[k]
    return None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--title", default="出口要闻日报")
    ap.add_argument("--summary", default="")
    ap.add_argument("--kb-url", default="")
    ap.add_argument("--channel", choices=list(CHANNELS), default=None)
    ap.add_argument("--no-host", action="store_true", help="跳过图床上传")
    ap.add_argument("--img-url", default="")
    a = ap.parse_args()
    ch = a.channel or detect_channel()
    if not ch:
        raise SystemExit("未配置任何推送通道（SERVERCHAN_KEY / PUSHPLUS_TOKEN / "
                         "WECOM_WEBHOOK）")
    img_url = a.img_url or ("" if a.no_host or ch == "wecom" else host_image(a.image))
    if ch == "wecom":
        CHANNELS[ch](a.image, a.title, a.summary, a.kb_url or conf("KB_URL"))
    else:
        CHANNELS[ch](a.title, a.summary, img_url, a.kb_url or conf("KB_URL"))
