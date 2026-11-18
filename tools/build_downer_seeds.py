# -*- coding: utf-8 -*-
"""Build a curated seed set for downer.app (video downloader tool) and
HTTP-verify each candidate. Writes seeds/seed-downer.app.json.

Logic: tool sites get backlinks from software directories, downloader/tool
review sites, social-media marketing blogs and video-tech blogs — NOT from
the platforms themselves (instagram.com/tiktok.com are noise, not targets).
Candidates are hand-picked by category; verification drops dead hosts.

This is the "refine" step after keyword extraction: keywords defined WHAT the
site is; seeds define WHERE its backlinks can realistically come from.
"""
import json
import ssl
import sys
import urllib.request
import urllib.error
import concurrent.futures as cf
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "seeds" / "seed-downer.app.json"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"

# (domain, type, tier, note, tags) — hand-curated, niche-relevant
SEEDS = [
    # software / tool directories
    ("alternativeto.net", "directory", "High", "软件替代品目录，可投 downer 作为下载器条目", ["video downloader", "tool directory"]),
    ("producthunt.com", "launch", "High", "产品发布站，适合工具型站点曝光", ["tool launch", "saas"]),
    ("betanet.net", "launch", "Low", "独立工具分享", ["indie tools"]),
    ("saashub.com", "directory", "Medium", "SaaS 工具目录", ["saas directory"]),
    ("toolify.ai", "directory", "Medium", "在线工具目录", ["tool directory"]),
    ("thereleasehub.com", "launch", "Low", "产品发布聚合", ["tool launch"]),
    ("stackshare.io", "community", "Medium", "开发者工具分享社区", ["dev tools"]),
    ("slashdot.org", "news", "High", "科技新闻，工具发布可投稿", ["tech news"]),
    ("hackernews.cc", "community", "Low", "科技社区", ["tech community"]),
    ("dev.to", "community", "Medium", "开发者社区，工具教程型软文", ["dev community", "tutorial"]),
    ("speckyboy.com", "resource", "Medium", "Web 工具资源站", ["web tools", "resource"]),
    ("webdesignerwall.com", "resource", "Medium", "设计/开发工具资源", ["tools"]),
    ("freewarehome.com", "directory", "Low", "免费软件目录", ["freeware"]),
    ("softonic.com", "directory", "High", "软件下载目录（投稿/收录）", ["software directory"]),
    ("download.com", "directory", "High", "CNET 软件目录", ["software directory"]),
    # video / creator tool blogs
    ("videotoolbox.net", "resource", "Low", "视频工具箱", ["video tools"]),
    ("filmora.com", "commercial", "High", "视频编辑工具博客，工具评测", ["video tools", "blog"]),
    ("capcut.com", "commercial", "High", "视频工具生态", ["video tools"]),
    ("canva.com", "commercial", "High", "设计工具博客，社媒内容", ["social media tools"]),
    ("buffer.com", "commercial", "High", "社媒管理博客，内容工具", ["social media tools"]),
    ("hootsuite.com", "commercial", "High", "社媒管理博客", ["social media"]),
    ("later.com", "commercial", "Medium", "Instagram 营销博客", ["instagram", "social media"]),
    ("metricool.com", "commercial", "Medium", "社媒分析工具博客", ["social media tools"]),
    ("socialbee.com", "commercial", "Medium", "社媒工具博客", ["social media"]),
    ("mailchimp.com", "commercial", "High", "营销资源博客", ["marketing"]),
    ("blog.hootsuite.com", "commercial", "High", "社媒营销内容", ["social media"]),
    # downloader / tool review sites
    ("techradar.com", "news", "High", "科技评测，视频工具栏目", ["tech review"]),
    ("pcmag.com", "news", "High", "软件评测", ["software review"]),
    ("zdnet.com", "news", "High", "科技新闻", ["tech news"]),
    ("makeuseof.com", "news", "Medium", "软件教程/工具推荐", ["how to", "tools"]),
    ("howtogeek.com", "resource", "High", "教程站，视频下载类主题", ["how to", "video"]),
    ("lifehacker.com", "news", "High", "生活黑客工具推荐", ["tools"]),
    ("gizmodo.com", "news", "High", "科技博客", ["tech"]),
    ("theverge.com", "news", "High", "科技媒体", ["tech"]),
    ("wired.com", "news", "High", "科技媒体", ["tech"]),
    ("tomsguide.com", "news", "Medium", "软件指南", ["software guide"]),
    ("digitaltrends.com", "news", "Medium", "科技趋势", ["tech"]),
    ("cnet.com", "news", "High", "软件评测下载", ["software review"]),
    # video format / tech blogs (aligns with blog section)
    ("videohelp.com", "community", "Medium", "视频格式/工具社区，高度相关", ["video formats", "community"]),
    ("doom9.org", "community", "Medium", "视频编码技术社区", ["video codec"]),
    ("videolan.org", "community", "High", "VLC 官方社区，视频格式", ["video formats"]),
    ("ffmpeg.org", "resource", "High", "视频处理权威资源", ["video formats"]),
    ("adobe.com", "commercial", "High", "视频创作生态", ["video"]),
    ("redd.it", "community", "Low", "社区聚合（需具体 subreddit）", ["community"]),
    # privacy / security angle (site emphasizes no tracking)
    ("privacyguides.org", "resource", "Medium", "隐私工具指南", ["privacy"]),
    ("tomsguide.com", "news", "Medium", "隐私工具", ["privacy"]),
    #forums / qna (tool recommendations)
    ("quora.com", "qna", "High", "问答，工具推荐", ["qna"]),
    ("reddit.com", "community", "High", "社区（具体 sub）", ["community"]),
    ("stackexchange.com", "qna", "High", "技术问答", ["qna"]),
]


def probe(url):
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=10, context=CTX) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return type(e).__name__


def main():
    # dedupe by domain
    seen, uniq = set(), []
    for d, t, tier, note, tags in SEEDS:
        if d in seen:
            continue
        seen.add(d)
        uniq.append((d, t, tier, note, tags))
    print("candidates:", len(uniq))
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        codes = list(ex.map(lambda x: probe("https://" + x[0]), uniq))
    rows, alive = [], 0
    for (d, t, tier, note, tags), code in zip(uniq, codes):
        ok = isinstance(code, int) and 200 <= code < 400
        if ok:
            alive += 1
        rows.append({
            "url": "https://" + d,
            "type": t,
            "authorityTier": tier,
            "tags": tags + ["downer", "video downloader"],
            "note": note,
            "note_en": "Niche-relevant source for a video downloader tool.",
            "source": "seed-curated" + ("-verified" if ok else "-dead"),
            "verified_status": code if isinstance(code, int) else None,
            "domains": ["downer.app"],
        })
    # keep only verified-alive for the seed file
    live = [r for r in rows if r["source"] == "seed-curated-verified"]
    OUT.write_text(json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8")
    print("alive: %d / %d -> wrote %s" % (alive, len(uniq), OUT))
    for r in rows:
        mark = "OK " if r["source"] == "seed-curated-verified" else "DEAD"
        print("  %s %-28s %s" % (mark, r["url"].replace("https://", ""), r["verified_status"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
