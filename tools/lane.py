#!/usr/bin/env python3
"""浏览器通道（browser lane）：需要真实浏览器会话的注册/登录/发帖，统一走这一条通道。

留痕：~/seo/.vault/browser-lane.jsonl（每步一行，append-only）
截图：会话内截图不入库，改成记录 DOM/URL/页面文案证据 + 站点回执

三档分类（由实测决定，不靠猜）：
  auto     —— 无 captcha、无邮箱验证，可整段自动
  handoff  —— 表已填好，卡在 Turnstile/reCAPTCHA，需人点一次即交接
  blocked  —— 邀请码 / 手机号 / 实名审核，不可自助

用法：
  lane.py list                       # 看 17 条通道现状
  lane.py start dev.to               # 标记开始
  lane.py record dev.to --phase signup --result handoff --url ... --note "..."
  lane.py writeback                  # 把 blocked/handoff 结果回写台账 status
"""
import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

LEDGER = os.path.expanduser("~/seo/.vault/browser-lane.jsonl")
VAULT = os.path.expanduser("~/seo/.vault/azgames.poki2.online-accounts.json")
SITE_DIR = os.path.expanduser("~/seo/azgames.poki2.online")
BASE = "http://127.0.0.1:8765"

PHASES = ("signup", "verify_email", "login", "submit", "publish")
RESULTS = ("ok", "handoff", "blocked", "failed", "skipped")

# 结果 → 台账 status
WRITEBACK = {
    "ok": "done",          # 已产出提交/发布
    "handoff": "working",  # 等人工点一次
    "blocked": "dropped",  # 不可自助
    "failed": "working",
}


def now_iso():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def append(rec):
    os.makedirs(os.path.dirname(LEDGER), mode=0o700, exist_ok=True)
    with open(LEDGER, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    os.chmod(LEDGER, 0o600)


def read_ledger():
    if not os.path.exists(LEDGER):
        return []
    out = []
    with open(LEDGER) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def latest_by_domain():
    st = {}
    for r in read_ledger():
        st[r["domain"]] = r
    return st


def load_vault():
    return json.load(open(VAULT))["accounts"]


def cmd_list():
    vault = load_vault()
    st = latest_by_domain()
    print("%-20s %-10s %-9s %-8s %s" % ("域名", "最新档位", "阶段", "结果", "备注"))
    for d in sorted(vault):
        r = st.get(d)
        if not r:
            print("%-20s %-10s %-9s %-8s %s" % (d, "未开始", "-", "-", ""))
            continue
        print("%-20s %-10s %-9s %-8s %s" % (
            d, r.get("lane", "-"), r.get("phase", "-"), r.get("result", "-"),
            (r.get("note") or "")[:60]))
    done = sum(1 for r in st.values() if r.get("result") == "ok")
    hand = sum(1 for r in st.values() if r.get("result") == "handoff")
    blk = sum(1 for r in st.values() if r.get("result") == "blocked")
    print("\n已产出 %d / 待人工一次 %d / 不可自助 %d / 未开始 %d" % (
        done, hand, blk, len(vault) - len([d for d in st if d in vault])))


def cmd_start(domain):
    append({"ts": now_iso(), "domain": domain, "phase": "start", "result": "started",
            "lane": "browser", "note": "进入浏览器通道"})
    print("已开始：%s" % domain)


def cmd_record(a):
    rec = {"ts": now_iso(), "domain": a.domain, "phase": a.phase,
           "result": a.result, "lane": a.lane, "url": a.url, "note": a.note}
    append(rec)
    print("已记录：%s %s → %s" % (a.domain, a.phase, a.result))


def target_id(domain):
    path = os.path.join(SITE_DIR, "targets.jsonl")
    with open(path) as f:
        for line in f:
            t = json.loads(line)
            if t.get("domain") == domain:
                return t["id"]
    return None


def cmd_writeback(dry=False):
    st = latest_by_domain()
    n = 0
    for d, r in st.items():
        want = WRITEBACK.get(r.get("result"))
        tid = target_id(d)
        if not want or not tid:
            continue
        note = "浏览器通道 %s · %s · %s" % (
            r["ts"][5:16].replace("T", " "), r.get("phase"), (r.get("note") or "")[:160])
        if dry:
            print("%-20s %s  %s" % (d, want, note))
            continue
        req = urllib.request.Request(
            "%s/api/target/%s" % (BASE, tid),
            data=json.dumps({"status": want, "owner_note": note}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                res = json.loads(resp.read())
            print("%-20s → %-8s %s" % (d, want, list(res.get("applied") or {})))
            n += 1
        except Exception as e:
            print("%-20s 回写失败：%s" % (d, e))
    print("\n回写 %d 条" % n)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    s = sub.add_parser("start")
    s.add_argument("domain")
    r = sub.add_parser("record")
    r.add_argument("domain")
    r.add_argument("--phase", required=True, choices=PHASES + ("start",))
    r.add_argument("--result", required=True, choices=RESULTS + ("started",))
    r.add_argument("--lane", default="browser")
    r.add_argument("--url", default="")
    r.add_argument("--note", default="")
    w = sub.add_parser("writeback")
    w.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.cmd == "list":
        cmd_list()
    elif a.cmd == "start":
        cmd_start(a.domain)
    elif a.cmd == "record":
        cmd_record(a)
    elif a.cmd == "writeback":
        cmd_writeback(a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
