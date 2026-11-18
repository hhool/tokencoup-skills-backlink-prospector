# -*- coding: utf-8 -*-
"""Probe wave-3 (unknown submit_type) targets for a real self-serve submit path.

Strategy (user directive 2026-11-17): do NOT bulk-guess submit_type from a
domain name — WDC competitor-backlink evidence only means 'once linked to a
competitor', not 'accepts new submissions'. Instead:
  1. stratified sample from wave3
  2. fetch homepage + common submit paths (/submit, /add, /submit-url, /suggest, /directory)
  3. look for self-serve submit-page signals and submit-form signals
  4. only upgrade submit_type when a real submit path is found; keep wave3 otherwise

Writes a JSON report with per-domain evidence. Never writes the workbench ledger.
"""
import json
import random
import re
import ssl
import sys
import urllib.request
import urllib.error
import concurrent.futures as cf
from pathlib import Path

LEDGER = Path("/Users/hou/seo/soundbuttons.cc/targets.jsonl")
OUT = Path("/Users/hou/Desktop/skill-seo-geo/backlink-prospector/reports/wave3-probe.json")
SAMPLE_N = int(sys.argv[1]) if len(sys.argv) > 1 else 30
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"

SUBMIT_PATHS = ["/", "/submit", "/add", "/submit-url", "/suggest", "/submit-site",
                "/directory", "/resources", "/links", "/add-site", "/list-your-site"]
# 必须出现「提交站点」的明确引导，而不是任何搜索框/订阅框
PATH_RE = re.compile(r"(?i)(submit\s+(your|a|the)\s+(site|url|link|tool|resource|website)"
                     r"|add\s+(your|a)\s+(site|url|link|tool|resource|website)"
                     r"|list\s+your\s+(site|business|link|url)"
                     r"|suggest\s+(a\s+|your\s+)?(site|link|url|resource)"
                     r"|directory\s+submission|submit\s+here|推荐\s*站点|提交\s*网址)")
# 表单里必须有明确的 URL/网址输入字段，且要有 submit 按钮
FORM_RE = re.compile(r"(?is)<form[^>]*>.*?(?:name|id|placeholder)=[\"'][^\"']*(?:url|website|site_url|link_url|homepage)[^\"']*[\"'].*?"
                     r"type=[\"']submit[\"'].*?</form>")


def fetch(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            data = r.read(250000)
            if "html" not in (r.headers.get("Content-Type") or "").lower():
                return r.status, ""
            return r.status, data.decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return type(e).__name__, ""


def probe_domain(domain):
    base = "https://" + domain
    evidence, submit_path, form = [], None, False
    for p in SUBMIT_PATHS:
        code, body = fetch(base + p)
        if isinstance(code, int) and 200 <= code < 400 and body:
            if PATH_RE.search(body):
                evidence.append({"path": p, "signal": "submit-link"})
                submit_path = submit_path or p
            if FORM_RE.search(body):
                evidence.append({"path": p, "signal": "submit-form"})
                form = True
            if submit_path and form:
                break
    stype = "listing" if (submit_path or form) else None
    return {"domain": domain, "submit_type": stype, "evidence": evidence,
            "verdict": "upgrade-listing" if stype else "keep-unknown"}


def main():
    rows = [json.loads(l) for l in LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()]
    w3 = [r for r in rows if r.get("wave") == 3 and r.get("found_by", "").startswith("prospector")]
    # 命令行可直接传域名列表（高置信子集）；否则随机抽样
    if len(sys.argv) > 2:
        domains = sys.argv[2:]
    else:
        random.seed(20261117)
        sample = random.sample(w3, min(SAMPLE_N, len(w3)))
        domains = [r["domain"] for r in sample]
    print("probing %d domains / %d wave3 targets" % (len(domains), len(w3)))
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(probe_domain, domains))
    upgraded = [r for r in results if r["submit_type"]]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "sample_size": len(results),
        "upgrade_count": len(upgraded),
        "upgrade_rate": round(len(upgraded) / len(results), 4) if results else 0,
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("upgrade-listing: %d / %d (%.1f%%)" % (
        len(upgraded), len(results), 100 * len(upgraded) / len(results) if results else 0))
    for r in upgraded[:20]:
        print("  +", r["domain"], r["evidence"][:2])
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
