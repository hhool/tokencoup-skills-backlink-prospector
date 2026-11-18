#!/usr/bin/env python3
"""汇总每个外链域名的注册/登录/发布路径，整体统计分类归纳。

数据源：~/.vault/reg-runs/*.jsonl（过程留痕）、accounts vault（凭据）、
targets.jsonl（台账状态/submit_type）。产出：
  reports/azgames-reg-paths-registry.json  — 每域路径登记（机器可读）
  reports/azgames-reg-paths-summary.md    — 统计 + 分类归纳（人读）
"""
import collections
import glob
import json
import os

VAULT = os.path.expanduser("~/seo/.vault")
RUNS = os.path.join(VAULT, "reg-runs")
SITE = os.path.expanduser("~/seo/azgames.poki2.online")
REPORTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "reports")
os.makedirs(REPORTS, exist_ok=True)

# done 结果 → 分类
CLASSIFY = {
    "registered_verified": "ready",
    "registered_session": "ready",
    "session_reused": "ready",
    "submitted_ok": "ready",
    "awaiting_verify": "awaiting",
    "submit_unconfirmed": "awaiting",
    "registered_unverified": "awaiting",
    "captcha": "manual",
    "needs_extra_field": "manual",
    "already_login_failed": "manual",
    "oauth_blocked": "manual",
    "submit_queued": "awaiting_gate",
    "no_form": "blocked",
    "form_error": "blocked",
    "error": "blocked",
    "redirect_offsite": "blocked",
    "bot_blocked": "blocked",
    "unreachable": "dead",
    "rejected_automation": "dead",
    "dry_run": "test",
}
CLASS_CN = {
    "ready": "✅ 可发布（账号已验证/有会话）",
    "awaiting": "⏳ 待验证信",
    "awaiting_gate": "⏳ 发送待人工确认（gate）",
    "manual": "🖐 需人工（验证码/额外字段/OAuth）",
    "blocked": "🚧 通道受阻（无表单/报错/反爬）",
    "dead": "💀 死路（拒绝自动化/不可达）",
    "test": "🧪 仅演练",
}


def newest_runlog_per_domain():
    """每域取时间戳最新的 jsonl（文件名含 HHMMSS，字典序即时间序）。"""
    best = {}
    for f in glob.glob(os.path.join(RUNS, "*.jsonl")):
        dom = os.path.basename(f).rsplit("-", 2)[0]
        if dom not in best or os.path.basename(f) > os.path.basename(best[dom]):
            best[dom] = f
    return best


def summarize_runlog(path):
    """从单条 jsonl 提取路径要素。"""
    reg_url = login_url = verify_subject = None
    verify_via = verify_ok = oauth_used = resend_clicked = None
    outcome = note = None
    events = []
    try:
        for line in open(path):
            try:
                d = json.loads(line)
            except Exception:
                continue
            ev = d.get("event") or d.get("result") or ""
            ph = d.get("phase") or ""
            events.append("%s:%s" % (ph, ev))
            u = d.get("url") or ""
            if ph == "open" and ev == "start" and reg_url is None:
                reg_url = u
            if ph == "login" and ev in ("entry_found", "filled") and not login_url:
                login_url = u
            if ph == "oauth" and ev in ("clicked", "clicked_gsi_iframe"):
                oauth_used = True
            if ph == "resend" and ev == "clicked":
                resend_clicked = True
            if ph == "verify_email" and ev == "link_found":
                verify_subject = d.get("note", "")
            if ph == "verify_email" and ev == "ok":
                verify_ok = True
                verify_via = verify_via or "browser_click"
            if ph == "done":
                outcome = d.get("result")
                note = d.get("note") or ""
    except Exception:
        pass
    return dict(reg_url=reg_url, login_url=login_url, verify_subject=verify_subject,
                verify_ok=verify_ok, oauth_used=bool(oauth_used),
                resend_clicked=bool(resend_clicked), outcome=outcome,
                note=note, events=events, log=path)


def main():
    accs = json.load(open(os.path.join(VAULT, "azgames.poki2.online-accounts.json")))
    accounts = accs.get("accounts", {})
    ledger = {}
    for line in open(os.path.join(SITE, "targets.jsonl")):
        t = json.loads(line)
        ledger[t.get("domain")] = t

    registry = {}
    for dom, path in sorted(newest_runlog_per_domain().items()):
        s = summarize_runlog(path)
        acc = accounts.get(dom) or {}
        led = ledger.get(dom) or {}
        klass = CLASSIFY.get(s["outcome"], "blocked")
        login_type = ("google_oauth" if s["oauth_used"] else
                      "magic_link" if acc.get("confidence") == "form_detected"
                      and not s.get("login_url") else
                      "password_login" if s["login_url"] else
                      "register_only" if s["reg_url"] else "unknown")
        reg_type = "passwordless" if "passwordless" in s["events"] else "form"
        registry[dom] = {
            "class": klass,
            "register_path": {"url": s["reg_url"] or acc.get("register_url"),
                              "type": reg_type},
            "login_path": {"url": s["login_url"] or acc.get("login_url") or "",
                           "type": login_type,
                           "credentials_stored": bool(acc)},
            "verify_path": {"method": "imap+browser_click" if s["verify_ok"]
                            else "imap_watch",
                            "resend_used": s["resend_clicked"],
                            "email_subject": s["verify_subject"]},
            "publish_path": {"submit_type": led.get("submit_type"),
                             "wave": led.get("wave"),
                             "status": led.get("status"),
                             "owner_note": led.get("owner_note") or ""},
            "outcome": s["outcome"],
            "note": s["note"],
            "evidence": {"runlog": s["log"], "shots_dir": os.path.join(RUNS, "shots")},
        }

    # 写机器可读登记
    out_json = os.path.join(REPORTS, "azgames-reg-paths-registry.json")
    json.dump(registry, open(out_json, "w"), ensure_ascii=False, indent=1)

    # 统计
    by_class = collections.Counter(v["class"] for v in registry.values())
    by_login = collections.Counter(v["login_path"]["type"] for v in registry.values())
    by_publish = collections.Counter(str(v["publish_path"]["submit_type"])
                                     for v in registry.values())
    ready = sorted(d for d, v in registry.items() if v["class"] == "ready")
    awaiting = sorted(d for d, v in registry.items() if v["class"] == "awaiting")
    manual = sorted(d for d, v in registry.items() if v["class"] == "manual")
    blocked = sorted(d for d, v in registry.items() if v["class"] == "blocked")
    dead = sorted(d for d, v in registry.items() if v["class"] == "dead")

    md = []
    md.append("# azgames 外链域名 注册/登录/发布路径登记与归纳")
    md.append("")
    md.append("生成：%s · 数据源：reg-runs jsonl + accounts vault + targets.jsonl" %
              __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"))
    md.append("")
    md.append("## 一、整体统计")
    md.append("")
    md.append("| 维度 | 分布 |")
    md.append("|---|---|")
    total = len(registry)
    md.append("| 有注册留痕的域名 | %d |" % total)
    md.append("| 分类 | " + " · ".join(
        "%s %d" % (CLASS_CN[k], n) for k, n in
        sorted(by_class.items(), key=lambda x: -x[1])) + " |")
    md.append("| 登录路径类型 | " + " · ".join("%s %d" % kv for kv in
                                              by_login.most_common()) + " |")
    md.append("| 发布通道（submit_type） | " + " · ".join(
        "%s %d" % kv for kv in by_publish.most_common()) + " |")
    md.append("")
    md.append("## 二、分类归纳")
    md.append("")
    for name, lst in (("可发布", ready), ("待验证信", awaiting),
                      ("需人工", manual), ("通道受阻", blocked), ("死路", dead)):
        md.append("### %s（%d）" % (CLASS_CN.get(
            {v: k for k, v in CLASSIFY.items()}.get(name, name), name), len(lst)))
        # 用 class key 找对应列表的中文标题
        md.append("")
        for d in lst:
            v = registry[d]
            bits = [d]
            p = v["publish_path"]
            if p.get("submit_type"):
                bits.append("发布=%s(w%d)" % (p["submit_type"], p.get("wave") or 0))
            if v["note"]:
                bits.append(v["note"][:60])
            md.append("- " + " · ".join(bits))
        md.append("")
    md.append("## 三、路径明细（每域）")
    md.append("")
    md.append("| 域名 | 注册入口 | 登录路径 | 验证方式 | 发布通道 | 结果 |")
    md.append("|---|---|---|---|---|---|")
    for d, v in registry.items():
        rp = v["register_path"]["url"] or "-"
        lp = "%s%s" % (v["login_path"]["type"],
                       (" " + v["login_path"]["url"]) if v["login_path"]["url"] else "")
        vp = v["verify_path"]["method"] + ("+resend" if v["verify_path"]["resend_used"] else "")
        pp = v["publish_path"]["submit_type"] or "-"
        oc = "%s %s" % (CLASS_CN.get(v["class"], v["class"]), v["outcome"] or "")
        md.append("| %s | %s | %s | %s | %s | %s |" %
                  (d, rp[:46], lp[:46], vp, pp, oc))
    md.append("")
    md.append("留痕索引：`~/.vault/reg-runs/*.jsonl`（过程）+ `~/.vault/reg-runs/shots/*.jpg`（截图）"
              " + `~/.vault/azgames.poki2.online-accounts.json`(凭据) + `audit.log`(闸门)")
    out_md = os.path.join(REPORTS, "azgames-reg-paths-summary.md")
    open(out_md, "w").write("\n".join(md))
    print("registry:", out_json)
    print("summary:", out_md)
    print("total domains:", total, dict(by_class))


if __name__ == "__main__":
    main()
