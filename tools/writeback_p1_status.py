#!/usr/bin/env python3
"""把 P1 实测结果回写台账（通过 serve 的 POST /api/target/<id>，避免内存态覆盖）。

实测结论只有三种落法，绝不伪造「成功」：
  done    —— 拿到站点成功回执（本次 0 条）
  working —— 入口实测可达，卡在注册/登录门槛，待账号投递
  dropped —— 站点明确拒绝或结构上无投递出口
"""
import argparse
import json
import urllib.request

BASE = "http://127.0.0.1:8765"

# 人工裁定（覆盖自动分类的偏差），每条都写理由
OVERRIDE = {
    "en.wikipedia.org": ("dropped", "禁自推（WP:NOTPROMO / WP:COI），无提交入口"),
    "ghost.org": ("dropped", "Ghost 是自建博客软件，非社区，无 ghost.org 外链出口"),
    "discord.com": ("dropped", "需具体服务器邀请，无通用提交入口"),
    "newsbreak.com": ("working", "首页无提交表单，需 publisher 账号；入口已记入凭据库"),
    "facebook.com": ("working", "入口重定向到 /login，需账号；群组发帖需先入群"),
}


def post(tid, payload):
    req = urllib.request.Request(
        "%s/api/target/%s" % (BASE, tid),
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    probe = json.load(open(a.probe))

    rows = []
    for r in probe["results"]:
        dom = r["domain"]
        if dom in OVERRIDE:
            status, reason = OVERRIDE[dom]
        elif r["gate"] == "no_response":
            status, reason = "pending", "入口无响应（%s），可重试" % r["note"]
        elif r["gate"] == "dead_entry":
            status, reason = "dropped", r["note"]
        elif r["gate"] == "rules_forbid":
            status, reason = "dropped", r["note"]
        else:
            status, reason = "working", "入口实测可达，需账号：%s" % r["note"]

        note = "实测 %s · HTTP %s · %s · %s" % (
            r["checked_at"][5:16].replace("T", " "), r["http_status"], r["gate"], reason)
        rows.append({"id": r["id"], "domain": dom, "status": status, "owner_note": note[:300]})

    if a.dry_run:
        for x in rows:
            print("%-20s %-8s %s" % (x["domain"], x["status"], x["owner_note"]))
        return 0

    from collections import Counter
    ok = 0
    for x in rows:
        try:
            res = post(x["id"], {"status": x["status"], "owner_note": x["owner_note"]})
            applied = res.get("applied") or {}
            print("%-20s %-8s applied=%s rejected=%s" % (
                x["domain"], x["status"], list(applied), res.get("rejected")))
            ok += 1 if res.get("ok") else 0
        except Exception as e:
            print("%-20s 回写失败：%s" % (x["domain"], e))
    print("\n回写成功 %d/%d" % (ok, len(rows)))
    print(Counter(x["status"] for x in rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
