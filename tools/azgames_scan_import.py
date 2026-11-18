#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把全量重扫 + 自动处理的实测结果落成台账动作（两段，都不猜）。

A 段 —— 生成 `blw add` 用的候选文件（只含台账里还没有的域）：
    每个域带 category / submit_type / tags / owner_note，
    证据写进 note（谁链过它、哪来的、探测到哪种出口）。

B 段 —— 对「已在台账里」的域，把实测门槛回写成 status + tags + owner_note，
    通过 serve 的 POST /api/target/<id>（serve 在跑时直接改 targets.jsonl 会被
    内存态覆盖，这一点 2026-11-17 踩过）。

status 映射（严格按实测证据，不美化）：
    submitted（站点自己的成功措辞）→ done
    rejected_automation / rejected  → dropped（站点明确拒收）
    unreachable（DNS/连接失败）      → dropped
    anonymous_form 未投 / account_required / captcha / no_form / bot_blocked
                                    → working（是机会，但当前一次性投不通）

用法：
  python3 tools/azgames_scan_import.py --dry-run
  python3 tools/azgames_scan_import.py            # 写 A 段文件 + B 段回写
"""
import argparse
import json
import re
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = Path.home() / "seo" / "azgames.poki2.online" / "targets.jsonl"
BASE = "http://127.0.0.1:8765"
CST = timezone(timedelta(hours=8))


def now():
    return datetime.now(CST).isoformat(timespec="seconds")


def bare(value):
    d = re.sub(r"^https?://", "", str(value or "").lower()).split("/")[0]
    return d[4:] if d.startswith("www.") else d


def load_ledger():
    rows = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        rows[bare(r.get("domain") or r.get("url"))] = r
    return rows


def category_of(cand):
    host, st = cand["domain"], (cand.get("submit_type") or "").lower()
    if st == "posting" or re.search(r"(?i)forum|board|community|discuss|reddit", host):
        return "community"
    if re.search(r"(?i)launch|hunt|betalist|producthunt|startup", host):
        return "launch"
    if re.search(r"(?i)news|press|media", host):
        return "news"
    if re.search(r"(?i)blog", host):
        return "resource"
    return "directory"


def submit_type_of(cand, rec=None):
    """提交方式以实测门槛为准：判成「listing」就会进 wave1 一次投递队列，
    而实测说要账号/人机验证的站根本做不到一次投递 —— 那是排期谎报。"""
    gate = (rec or {}).get("gate")
    if gate == "account_required":
        return "register"
    if gate == "captcha":
        return "register"
    if gate in ("no_form", "bot_blocked", "form_get_only", "redirect_offsite", "error"):
        return "unknown"
    if gate == "anonymous_form":
        return "listing"
    st = (cand.get("submit_type") or "").lower()
    return st if st in ("listing", "posting", "guest_post", "publish", "free",
                        "auto", "register", "paid") else "listing"


def status_of(rec):
    if not rec:
        return "pending", "未探测"
    g = rec.get("gate")
    v = rec.get("submit_verdict")
    if v == "submitted":
        return "done", "实测提交成功"
    if v in ("rejected_automation", "rejected"):
        return "dropped", "站点明确拒收"
    if g == "unreachable":
        return "dropped", "DNS/连接失败"
    if g == "bot_blocked":
        return "working", "Cloudflare/反爬拦截（人可访问，非死链）"
    if g == "anonymous_form":
        return "working", "匿名表单已确认，未投递"
    if g == "form_get_only":
        return "working", "表单只支持 GET，需手工确认"
    if g == "account_required":
        return "working", "需注册账号"
    if g == "captcha":
        return "working", "人机验证拦截"
    if g == "no_form":
        return "working", "入口未找到（预算内）"
    return "pending", "未判定"


def note_of(cand, rec):
    parts = []
    if cand.get("evidence"):
        parts.append(cand["evidence"])
    if cand.get("entry_url"):
        parts.append("入口 " + cand["entry_url"])
    if rec:
        g = rec.get("gate")
        parts.append("实测 %s · gate=%s" % (now()[:16], g))
        if rec.get("submit_verdict"):
            parts.append("投递结果 %s (HTTP %s)" % (rec["submit_verdict"], rec.get("submit_http")))
        if rec.get("form_fields"):
            parts.append("字段 " + ",".join(rec["form_fields"])[:60])
    return " | ".join(parts)[:600]


def post_update(tid, payload):
    req = urllib.request.Request(
        "%s/api/target/%s" % (BASE, tid),
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=20).read() or b"{}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default="reports/azgames-fullscan-candidates.json")
    ap.add_argument("--autopilot", nargs="+",
                    default=["reports/azgames-probes-merged.json"])
    ap.add_argument("--out", default="reports/azgames-import.json")
    ap.add_argument("--min-score", type=float, default=0.0)
    ap.add_argument("--all-candidates", action="store_true",
                    help="连未探测的候选也入账（默认只入已实测的，避免把 6000 条"
                         "未验证的 2012 老域灌进台账）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cands = json.loads((ROOT / args.candidates).read_text(encoding="utf-8"))["rows"]
    probes = {}
    for name in args.autopilot:
        ap_path = ROOT / name
        if not ap_path.exists():
            continue
        for r in json.loads(ap_path.read_text(encoding="utf-8"))["rows"]:
            probes[r["domain"]] = r          # 后跑的覆盖先跑的（同一域只留最新观测）

    ledger = load_ledger()
    imp, existing = [], []
    for c in cands:
        if c.get("score", 0) < args.min_score:
            continue
        dom = bare(c["domain"])
        rec = probes.get(dom)
        if rec is None and not args.all_candidates:
            continue
        status, _why = status_of(rec)
        tags = ["src:" + (c.get("source") or "unknown")]
        if rec:
            tags.append("gate:" + str(rec.get("gate")))
        if rec and rec.get("submit_verdict") == "submitted":
            tags.append("submitted")
        if dom in ledger:
            existing.append((dom, ledger[dom], c, rec, status, tags))
            continue
        imp.append({
            "url": "https://%s/" % dom,
            "domain": dom,
            "category": category_of(c),
            "submit_type": submit_type_of(c, rec),
            "cost": "free" if c.get("pricing") == "free" else "unknown",
            "effort": "low",
            "link_type": "unknown",
            "status": status,
            "tags": tags,
            "owner_note": note_of(c, rec),
            "found_by": c.get("source") or "seed",
            "title": dom,
        })

    out = ROOT / args.out
    out.write_text(json.dumps({"site": "azgames.poki2.online", "generated_at": now(),
                               "count": len(imp), "candidates": imp},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print("新域 %d 条 → %s" % (len(imp), out))
    print("已在台账 %d 条（只回写状态，不重复入账）" % len(existing))
    print("状态分布（新域）：", dict(Counter(x["status"] for x in imp)))
    print("gate 分布（新域）：", dict(Counter(t for x in imp for t in x["tags"] if t.startswith("gate:"))))

    if args.dry_run:
        print("\n[dry-run] 不写台账。前 10 条：")
        for x in imp[:10]:
            print("  %-30s %-10s %-9s %s" % (x["domain"], x["category"], x["status"], x["owner_note"][:70]))
        return 0

    # B 段：已在台账的，回写实测状态
    if existing:
        try:
            urllib.request.urlopen(BASE + "/api/health", timeout=5).read()
            serve_ok = True
        except Exception:
            serve_ok = False
        if not serve_ok:
            print("!! serve 未运行，B 段回写跳过（先启动 serve 再跑一次）")
        else:
            n = 0
            for dom, row, c, rec, status, tags in existing:
                if not rec:
                    continue
                payload = {
                    "status": status,
                    "owner_note": note_of(c, rec),
                    "tags": sorted(set((row.get("tags") or []) + tags)),
                }
                try:
                    post_update(row["id"], payload)
                    n += 1
                except Exception as e:
                    print("  !! %s 回写失败：%s" % (dom, e))
            print("B 段：回写 %d 条已有记录" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
