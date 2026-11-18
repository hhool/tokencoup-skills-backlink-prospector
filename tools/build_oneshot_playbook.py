#!/usr/bin/env python3
"""一次投递实测清单（wave=1 playbook）。

对 workbench 六站 wave=1 条目：
  - 补 target_page（要推的落地页）
  - 按 category 选模板渲染 subject/body（真实可发的英文话术）
  - 推断投递入口（submit_url）：从 how/note 提取已有路径，否则域名根 + 提示
  - 按 fit_score 降序输出 CSV（每站一份）+ 汇总 MD（top N 优先批次）

只读台账，不写回；需要落盘字段时用 --apply-target-page。
"""
import argparse, csv, json, re
from pathlib import Path

WS = Path("/Users/hou/seo")
REPORTS = Path(__file__).resolve().parent.parent / "reports"
SITES = ["downer.app", "poki2.online", "azgames.poki2.online",
         "balancebiketoddler.com", "soundbuttons.cc", "soundbuttons.click"]
DEFAULT_LANDING = {
    "downer.app": "https://downer.app/",
    "poki2.online": "https://poki2.online/",
    "azgames.poki2.online": "https://azgames.poki2.online/",
    "balancebiketoddler.com": "https://balancebiketoddler.com/",
    "soundbuttons.cc": "https://soundbuttons.cc/",
    "soundbuttons.click": "https://soundbuttons.click/",
}
SUBMIT_HINT = {
    "listing": "On-site submission form — look for Submit / Add site / Add tool / List your site.",
    "register": "Create a free account, then find the submit/add entry in the dashboard.",
    "posting": "Publish a post directly in the community — value first, link last.",
    "answer": "Find an open question and answer it; drop the link only where relevant.",
    "publish": "Self-publish a page/post; add the link in the body where natural.",
    "free": "Free submission / auto-approval path — submit and confirm indexing.",
    "pr": "Submit a press release; include the link in the body.",
    "auto": "Automated/self-serve inclusion — submit the URL and confirm.",
}

# 话术按「动作」选，不按 category：同一 category 下 listing/answer/publish/pr
# 是完全不同的行为，用 category 选会把新闻站套上记者征询模板（review 实锤）。
# 模板由本工具内置，保证 8 种一次投递动作各有正确话术，零 CJK。
SUBMIT_TEMPLATE = {
    "listing": {
        "subject": "Submit {site_name} to {outlet}",
        "body": "Hi,\n\nI'd like to submit {site_name} ({site}) to {outlet} for inclusion.\n\nOne-line intro: {site_name} is a free resource for {industry}.\nSuggested page: {target_page}\n\nHappy to provide any extra details you need.\n\nThanks",
    },
    "register": {
        "subject": "Adding {site_name} to {outlet}",
        "body": "Hi,\n\nI've signed up for {outlet} and would like to add {site_name} ({site}).\n\nCategory: {industry}\nLink to feature: {target_page}\n\nHappy to complete any profile fields you require. Thanks!",
    },
    "posting": {
        "subject": "Sharing: 3 practical lessons about {industry}",
        "body": "Title: 3 practical lessons about {industry} — and how we worked around them\n\nBody (value first, link last):\n1) ...\n2) ...\n3) ...\n\nIf you're working on something similar, our full notes are here: {target_page}\n(Not an ad — just sharing. Happy to discuss in the comments.)",
    },
    "answer": {
        "subject": "Answer on {outlet} — first-hand data on {industry}",
        "body": "Hi,\n\nI saw the open question on {outlet} about {industry}. I have first-hand data I'm happy to share, with no strings attached.\n\nQ: ...\nA: ... (with verifiable numbers or a concrete example)\n\nAttribution: {site_name} ({site}). If a link is allowed, the detailed write-up is here: {target_page}\n\nThanks either way.",
    },
    "publish": {
        "subject": "Article idea for {outlet}: a data-backed take on {industry}",
        "body": "Hi,\n\nI'd like to publish an original piece on {outlet}. Working title:\n\"What most guides get wrong about {industry}\"\n\nCore argument: ...\nTarget reader: ...\nAuthor: {site_name} ({site})\n\nI can include original data and a working example: {target_page}\n\nWant me to send the outline?",
    },
    "free": {
        "subject": "Free submission: {site_name} to {outlet}",
        "body": "Hi,\n\nI'd like to submit {site_name} ({site}) via your free listing option.\n\nCategory: {industry}\nPage to list: {target_page}\n\nPlease let me know if any additional info is needed. Thanks!",
    },
    "pr": {
        "subject": "Press release: {site_name} — {industry}",
        "body": "FOR IMMEDIATE RELEASE\n\nHeadline: {site_name} launches free {industry} resource\n\n{outlet} team,\n\nPlease find below our press release for {site_name} ({site}).\n\nSummary: {site_name} is a free resource for {industry}.\nLearn more: {target_page}\n\nMedia contact: [name / email]\n\nThank you.",
    },
    "auto": {
        "subject": "Add {site_name} to {outlet}",
        "body": "Hi,\n\nAdding {site_name} ({site}) to {outlet}.\n\nCategory: {industry}\nURL: {target_page}\n\nPlease confirm once it's live. Thanks!",
    },
}

# 无自助提交入口、无法留下可由我们控制的链接的站：不是外链目标。
# web.archive.org（归档）、github.com（代码托管）、wikipedia/wikidata（禁自推）、
# bbb.org/capterra（第三方目录，需审核且非一次投递）。
EXCLUDE_DOMAINS = {
    "web.archive.org", "github.com", "wikipedia.org", "wikidata.org",
    "bbb.org", "capterra.com", "google.com",
}
PATH_RE = re.compile(r"(?i)(https?://[^\s,;]+?/(?:submit|add|suggest|new|list|directory|story|submit-site|add-url|link)[^\s,)';]*)")


def load_templates(site):
    p = WS / site / "templates.json"
    if not p.exists():
        p = WS / "downer.app" / "templates.json"
    return json.loads(p.read_text(encoding="utf-8"))


def render(tpl, site, landing, industry, outlet):
    # 英文话术必须零 CJK：品牌名取域名主标签并首字母大写；outlet 用纯域名，
    # 不用台账里的中文 title（否则英文 pitch 里混入中文）。
    brand = site.split(".")[0]
    brand = brand[:1].upper() + brand[1:]
    ctx = {"site": landing, "site_name": brand,
           "target_page": landing, "industry": industry or "free online resources",
           "outlet": outlet}
    out = {}
    for k in ("subject", "body"):
        s = tpl.get(k, "")
        for a, b in ctx.items():
            s = s.replace("{%s}" % a, str(b))
        out[k] = s.strip()
    return out


def submit_entry(t):
    """返回 (entry_url, 入口说明)。优先用 how/note 里已有的提交 URL。"""
    blob = " ".join(str(t.get(k) or "") for k in ("how", "note"))
    m = PATH_RE.search(blob)
    if m:
        return m.group(1).rstrip(".,"), "从录入指引提取的直达提交页"
    st = t.get("submit_type") or "unknown"
    return t.get("url") or ("https://" + t["domain"] + "/"), SUBMIT_HINT.get(st, "进站后找 Submit / Add / Contribute 入口")


LANDING_BY_CATEGORY = {
    # 功能页优先：目录/资源类外链指向真正有价值的差异页，比首页转化更高。
    "soundbuttons.cc": {"directory": "https://soundbuttons.cc/audio-editor",
                        "resource": "https://soundbuttons.cc/audio-editor",
                        "news": "https://soundbuttons.cc/audio-editor"},
    "soundbuttons.click": {"directory": "https://soundbuttons.click/audio-editor",
                           "resource": "https://soundbuttons.click/audio-editor",
                           "news": "https://soundbuttons.click/audio-editor"},
}


def build(site, landing, top_n):
    rows = [json.loads(l) for l in (WS / site / "targets.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    w1 = [r for r in rows if r.get("wave") == 1 and r.get("status") not in ("dropped", "lost")]
    w1.sort(key=lambda r: -(r.get("fit_score") or 0))
    cfg = json.loads((WS / site / "project.json").read_text(encoding="utf-8"))
    industry = cfg.get("industry", "")
    out = []
    seen_domains = set()
    for i, t in enumerate(w1, 1):
        cat = t.get("category") or "other"
        st = t.get("submit_type") or "unknown"
        # 话术按动作选；缺动作的用 directory 兜底
        tpl = SUBMIT_TEMPLATE.get(st, SUBMIT_TEMPLATE["listing"])
        entry, hint = submit_entry(t)
        page = (t.get("target_page") or "").strip() or LANDING_BY_CATEGORY.get(site, {}).get(cat, landing)
        txt = render(tpl, site, page, industry, t["domain"])
        # review 标记
        review = "OK"
        if t["domain"] in EXCLUDE_DOMAINS:
            review = "EXCLUDE: 无自助提交入口/禁自推，不是外链目标"
        elif t["domain"] == "reddit.com":
            if t["domain"] in seen_domains:
                review = "DUPLICATE: 同平台多条，合并为一次投递"
            else:
                review = "CAUTION: 社区自推受限，需确认具体 subreddit 版规"
        elif st == "unknown":
            review = "CAUTION: 投递方式未确认"
        seen_domains.add(t["domain"])
        out.append({
            "seq": i, "id": t["id"], "domain": t["domain"], "category": cat,
            "submit_type": st,
            "fit_score": t.get("fit_score") or 0,
            "authority": t.get("authority_label") or "-",
            "entry_url": entry, "entry_hint": hint, "target_page": page,
            "subject": txt["subject"], "body": txt["body"].replace("\n", " ⏎ "),
            "status": t.get("status") or "pending",
            "priority": "P1" if i <= top_n else "P2",
            "review": review,
            "link_state": t.get("link_state") or "unknown",
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=20, help="每站 P1 优先批次数")
    ap.add_argument("--landing", help="覆盖所有站的落地页 URL")
    ap.add_argument("--site", action="append", help="只处理指定站（可重复）")
    args = ap.parse_args()
    REPORTS.mkdir(parents=True, exist_ok=True)
    sites = args.site or SITES
    all_rows = {}
    for site in sites:
        landing = args.landing or DEFAULT_LANDING.get(site, "https://" + site + "/")
        rows = build(site, landing, args.top * 3)  # 多算一些，供排除后仍有 top 条 P1
        # P1 重排：先排除 EXCLUDE/DUPLICATE，再取前 top 条为 P1
        eligible = [r for r in rows if not r["review"].startswith(("EXCLUDE", "DUPLICATE"))]
        elig_ids = {r["id"] for r in eligible[:args.top]}
        for r in rows:
            r["priority"] = "P1" if r["id"] in elig_ids else (
                "EXCLUDE" if r["review"].startswith("EXCLUDE") else
                "DUP" if r["review"].startswith("DUPLICATE") else "P2")
        all_rows[site] = rows
        out = REPORTS / ("oneshot-%s.csv" % site)
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["seq"])
            w.writeheader(); w.writerows(rows)
        print("%-26s wave1=%4d -> %s" % (site, len(rows), out.name))
    # 汇总 MD
    md = ["# 一次投递实测清单（wave=1）", "",
          "按站点分组，P1 = 每站前 %d 条优先批次；所有条目为「一次动作即出结果」，无邮件往返依赖。" % args.top,
          "R-520：实际投递由人完成；本清单只提供入口与话术。", ""]
    for site in sites:
        rows = all_rows[site]
        p1 = [r for r in rows if r["priority"] == "P1"]
        excl = [r for r in rows if r["priority"] == "EXCLUDE"]
        dup = [r for r in rows if r["priority"] == "DUP"]
        md += ["## %s — %d 条（P1 可投 %d / 剔除 %d / 重复 %d）" % (
                   site, len(rows), len(p1), len(excl), len(dup)), "",
               "| # | 目标 | 品类 | 方式 | 分 | 投递入口 | review |",
               "|---|---|---|---|---|---|---|"]
        for r in p1[:args.top]:
            md.append("| %d | %s | %s | %s | %d | %s | %s |" % (
                r["seq"], r["domain"], r["category"], r["submit_type"],
                r["fit_score"], r["entry_url"][:40], r["review"][:22]))
        sample = p1[0] if p1 else (rows[0] if rows else None)
        if excl:
            md += ["", "剔除（无自助入口/禁自推）：" + ", ".join(r["domain"] for r in excl[:12])]
        if dup:
            md += ["", "同平台重复（合并投递）：" + ", ".join(r["domain"] for r in dup[:12])]
        if sample:
            md += ["", "P1 话术示例（第一条 · %s · %s）：" % (sample["domain"], sample["submit_type"]), "",
                   "**Subject:** %s" % sample["subject"],
                   "", "```", sample["body"], "```", ""]
    (REPORTS / "oneshot-playbook.md").write_text("\n".join(md), encoding="utf-8")
    print("\n汇总: %s" % (REPORTS / "oneshot-playbook.md"))


if __name__ == "__main__":
    main()
