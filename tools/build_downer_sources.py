# -*- coding: utf-8 -*-
"""Build a three-bucket source set for downer.app and HTTP-verify each candidate.

Buckets (user directive 2026-11-17):
  1. directory        — software / SaaS / tool directories (one-shot listing)
  2. video_tool_blog  — video creation / editing / downloader review blogs
  3. other            — communities, Q&A, launch platforms, bookmarks

Each candidate carries an explicit submit_type so the workbench can derive
its outreach wave (1 = one-shot, 2 = multi-step email exchange). One-shot
types are deliberately assigned wherever a real self-serve path exists;
only editorial / partnership paths get multi-step types.

Writes seeds/seed-downer-sources.json (verified-alive only). This is a
DISCOVERY artifact: importing into the ledger is a separate workbench step.
"""
import json
import ssl
import sys
import urllib.request
import urllib.error
import concurrent.futures as cf
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "seeds" / "seed-downer-sources.json"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"

# (domain, category, submit_type, tier, note, tags)
# category ∈ CATEGORIES of workbench; submit_type ∈ SUBMIT_TYPES of workbench.
SOURCES = [
    # ── 1. directory：自助提交/收录，一次投递 ──────────────────────────
    ("alternativeto.net", "directory", "listing", "High", "软件替代品目录，提交工具条目", ["software directory", "one-shot"]),
    ("producthunt.com", "launch", "listing", "High", "产品发布目录，自助提交", ["launch", "one-shot"]),
    ("saashub.com", "directory", "listing", "Medium", "SaaS 工具目录", ["saas directory", "one-shot"]),
    ("toolify.ai", "directory", "listing", "Medium", "AI/在线工具目录", ["tool directory", "one-shot"]),
    ("softonic.com", "directory", "listing", "High", "软件下载目录投稿收录", ["software directory", "one-shot"]),
    ("download.com", "directory", "listing", "High", "CNET 软件目录提交", ["software directory", "one-shot"]),
    ("freewarehome.com", "directory", "free", "Low", "免费软件目录免费提交", ["freeware", "one-shot"]),
    ("snapfiles.com", "directory", "listing", "Low", "共享软件目录提交", ["software directory", "one-shot"]),
    ("brothersoft.com", "directory", "listing", "Low", "软件下载目录提交", ["software directory", "one-shot"]),
    ("filehorse.com", "directory", "listing", "Low", "免费软件目录提交", ["software directory", "one-shot"]),
    ("softpedia.com", "directory", "apply", "High", "软件目录收录需审核", ["software directory", "multi-step"]),
    ("filehippo.com", "directory", "apply", "High", "软件目录收录需审核", ["software directory", "multi-step"]),
    ("majorgeeks.com", "directory", "apply", "Medium", "软件目录提交审核", ["software directory", "multi-step"]),
    ("appsumo.com", "launch", "apply", "High", "工具特卖平台，需申请审核", ["deal platform", "multi-step"]),
    ("betalist.com", "launch", "listing", "Medium", "Beta 产品目录提交", ["beta directory", "one-shot"]),
    ("thereleasehub.com", "launch", "listing", "Low", "产品发布聚合提交", ["launch", "one-shot"]),
    ("betanet.net", "launch", "posting", "Low", "独立工具分享", ["indie tools", "one-shot"]),
    ("stackshare.io", "community", "register", "Medium", "开发者工具档案注册", ["dev tools", "one-shot"]),
    ("slashdot.org", "news", "pitch", "High", "科技新闻，需投稿沟通", ["tech news", "multi-step"]),
    ("hackernews.cc", "community", "posting", "Low", "科技社区发帖", ["tech community", "one-shot"]),

    # ── 2. video_tool_blog：视频工具/编辑/评测博客 ──────────────────────
    ("filmora.com", "commercial", "guest_post", "High", "视频编辑工具博客，需投稿撰文", ["video tools", "blog", "multi-step"]),
    ("capcut.com", "commercial", "guest_post", "High", "视频工具生态博客，需投稿", ["video tools", "multi-step"]),
    ("canva.com", "commercial", "guest_post", "High", "设计工具博客，社媒内容", ["social media tools", "multi-step"]),
    ("buffer.com", "commercial", "publish", "High", "社媒管理博客，内容发布", ["social media tools", "one-shot"]),
    ("hootsuite.com", "commercial", "publish", "High", "社媒管理博客", ["social media", "one-shot"]),
    ("later.com", "commercial", "guest_post", "Medium", "Instagram 营销博客投稿", ["instagram", "multi-step"]),
    ("metricool.com", "commercial", "guest_post", "Medium", "社媒分析工具博客投稿", ["social media tools", "multi-step"]),
    ("socialbee.com", "commercial", "guest_post", "Medium", "社媒工具博客投稿", ["social media", "multi-step"]),
    ("mailchimp.com", "commercial", "publish", "High", "营销资源博客，内容发布", ["marketing", "one-shot"]),
    ("videotoolbox.net", "resource", "listing", "Low", "视频工具箱资源收录", ["video tools", "one-shot"]),
    ("videohelp.com", "community", "posting", "Medium", "视频格式/工具社区，高度相关", ["video formats", "one-shot"]),
    ("doom9.org", "community", "posting", "Medium", "视频编码技术社区", ["video codec", "one-shot"]),
    ("videolan.org", "community", "posting", "High", "VLC 官方社区，视频格式", ["video formats", "one-shot"]),
    ("ffmpeg.org", "resource", "pr", "High", "视频处理权威资源，开源 PR", ["video formats", "one-shot"]),

    # ── 3. other：社区/问答/发布平台/书签/工具评测 ──────────────────────
    ("dev.to", "community", "publish", "Medium", "开发者社区，工具教程内容发布", ["dev community", "one-shot"]),
    ("speckyboy.com", "resource", "guest_post", "Medium", "Web 工具资源投稿", ["web tools", "multi-step"]),
    ("webdesignerwall.com", "resource", "guest_post", "Medium", "设计/开发工具资源投稿", ["tools", "multi-step"]),
    ("techradar.com", "news", "pitch", "High", "科技评测，媒体征询", ["tech review", "multi-step"]),
    ("zdnet.com", "news", "pitch", "High", "科技新闻，媒体征询", ["tech news", "multi-step"]),
    ("makeuseof.com", "news", "guest_post", "Medium", "软件教程/工具推荐投稿", ["how to", "multi-step"]),
    ("howtogeek.com", "resource", "guest_post", "High", "教程站，视频下载主题投稿", ["how to", "multi-step"]),
    ("lifehacker.com", "news", "pitch", "High", "生活黑客工具推荐，媒体征询", ["tools", "multi-step"]),
    ("theverge.com", "news", "pitch", "High", "科技媒体征询", ["tech", "multi-step"]),
    ("wired.com", "news", "pitch", "High", "科技媒体征询", ["tech", "multi-step"]),
    ("tomsguide.com", "news", "guest_post", "Medium", "软件指南投稿", ["software guide", "multi-step"]),
    ("cnet.com", "news", "pitch", "High", "软件评测媒体征询", ["software review", "multi-step"]),
    ("quora.com", "qna", "answer", "High", "问答平台，工具推荐回答", ["qna", "one-shot"]),
    ("reddit.com", "community", "posting", "High", "社区（需具体 subreddit）", ["community", "one-shot"]),
    ("stackexchange.com", "qna", "answer", "High", "技术问答回答", ["qna", "one-shot"]),
    ("privacyguides.org", "resource", "apply", "Medium", "隐私工具指南收录申请", ["privacy", "multi-step"]),
]


def probe(url):
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=12, context=CTX) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return type(e).__name__


def main():
    # drop placeholders and dedupe by domain
    seen, uniq = set(), []
    for d, cat, st, tier, note, tags in SOURCES:
        if d in seen:
            continue
        seen.add(d)
        uniq.append((d, cat, st, tier, note, tags))
    print("candidates: %d" % len(uniq))
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        codes = list(ex.map(lambda x: probe("https://" + x[0]), uniq))
    rows = []
    buckets = {}
    bot_blocked = 0
    # 403/429/412 = 服务器有响应，只是拒绝机器人（Cloudflare / 限流）。
    # 站点本身健康、人工浏览器可正常提交，不能当死链丢掉 ——
    # 否则会误杀 alternativeto / producthunt / quora 这类核心目录。
    BOT_BLOCK_CODES = {401, 403, 405, 406, 412, 429, 503}
    for (d, cat, st, tier, note, tags), code in zip(uniq, codes):
        ok = isinstance(code, int) and 200 <= code < 400
        blocked = isinstance(code, int) and code in BOT_BLOCK_CODES
        if not ok and not blocked:
            print("  DEAD %-28s %s" % (d, code))
            continue
        if blocked:
            bot_blocked += 1
            print("  BOT! %-28s %s (人工可访问)" % (d, code))
        buckets.setdefault(cat, 0)
        buckets[cat] += 1
        rows.append({
            "url": "https://" + d,
            "category": cat,
            "submit_type": st,
            "title": note,
            "authorityTier": tier,
            "tags": tags + ["downer", "video downloader", "wave-source"] +
                    (["bot-blocked"] if blocked else []),
            "note": note,
            "source": "seed-curated-verified",
            "verified_status": code,
            "verify_note": "bot-blocked, human access OK" if blocked else "ok",
            "domains": ["downer.app"],
        })
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nalive: %d / %d (其中反爬拦截 %d)" % (len(rows), len(uniq), bot_blocked))
    for k in sorted(buckets):
        print("  %-16s %d" % (k, buckets[k]))
    print("wrote %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
