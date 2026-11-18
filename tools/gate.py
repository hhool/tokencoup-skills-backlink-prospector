#!/usr/bin/env python3
"""发送闸门：默认「每条人工确认」，可一键关成全自动。

所有会对外产生动作的地方（目录提交 POST、发信、投稿）都必须先过这里。
- confirm 模式：不发送，写进待确认队列，由 `gate.py approve <id>` 放行；
- auto 模式：直接放行，同时留审计记录。

留痕：~/seo/.vault/audit.log（每次判定一行 JSON）+ ~/seo/.vault/send-queue.jsonl（队列本体）
配置：~/seo/.gate.json
"""
import argparse
import json
import os
import time
import uuid
from datetime import datetime

CST = None
try:
    from datetime import timezone, timedelta
    CST = timezone(timedelta(hours=8))
except Exception:  # pragma: no cover
    pass

CONFIG = os.path.expanduser("~/seo/.gate.json")
VAULT = os.path.expanduser("~/seo/.vault")
QUEUE = os.path.join(VAULT, "send-queue.jsonl")
AUDIT = os.path.join(VAULT, "audit.log")

# 默认被闸门管住的动作。注册（signup）不在其中：注册是用户明确要求自动化的。
GATED_ACTIONS = ("submit", "email", "publish", "apply")

DEFAULT_CONFIG = {
    "send_mode": "confirm",          # confirm = 人工确认；auto = 全自动
    "gated_actions": list(GATED_ACTIONS),
    "updated": "",
    "updated_by": "default",
    "note": "默认每条发送需人工确认；gate.py mode auto 可关闭",
}


def now_iso():
    if CST:
        return datetime.now(CST).isoformat(timespec="seconds")
    return datetime.now().isoformat(timespec="seconds")


def _ensure():
    os.makedirs(VAULT, exist_ok=True)
    try:
        os.chmod(VAULT, 0o700)
    except OSError:
        pass


def load_config():
    _ensure()
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG):
        try:
            with open(CONFIG) as f:
                cfg.update(json.load(f) or {})
        except Exception:
            pass
    return cfg


def save_config(cfg, by="cli"):
    _ensure()
    cfg["updated"] = now_iso()
    cfg["updated_by"] = by
    tmp = CONFIG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)
    os.replace(tmp, CONFIG)


def audit(rec):
    _ensure()
    rec = dict(rec)
    rec.setdefault("ts", now_iso())
    with open(AUDIT, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    try:
        os.chmod(AUDIT, 0o600)
    except OSError:
        pass


def read_queue():
    if not os.path.exists(QUEUE):
        return []
    out = []
    for line in open(QUEUE):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def _write_queue(items):
    _ensure()
    tmp = QUEUE + ".tmp"
    with open(tmp, "w") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    os.replace(tmp, QUEUE)
    try:
        os.chmod(QUEUE, 0o600)
    except OSError:
        pass


def check(action, domain, url="", payload=None, note=""):
    """发送前调用。返回 (allowed: bool, info: dict)。

    allowed=False 时把这次发送写进待确认队列，调用方**不得**继续发送。
    """
    cfg = load_config()
    mode = cfg.get("send_mode", "confirm")
    if action not in cfg.get("gated_actions", GATED_ACTIONS) or mode == "auto":
        audit({"action": "gate_allow", "gate_action": action, "domain": domain,
               "url": url, "mode": mode, "auto": mode == "auto"})
        return True, {"mode": mode, "queued": False}

    qid = "q" + datetime.now().strftime("%m%d%H%M") + uuid.uuid4().hex[:4]
    rec = {"id": qid, "ts": now_iso(), "action": action, "domain": domain,
           "url": url, "note": note, "status": "pending",
           "payload": payload if isinstance(payload, (dict, list)) else None}
    items = read_queue()
    items.append(rec)
    _write_queue(items)
    audit({"action": "gate_queue", "gate_action": action, "domain": domain,
           "url": url, "queue_id": qid, "mode": mode})
    return False, {"mode": mode, "queued": True, "id": qid}


def decide(qid, status, why=""):
    items = read_queue()
    hit = None
    for it in items:
        if it["id"] == qid:
            it["status"] = status
            it["decided"] = now_iso()
            it["why"] = why
            hit = it
    if not hit:
        return None
    _write_queue(items)
    audit({"action": "gate_" + status, "queue_id": qid, "domain": hit["domain"],
           "gate_action": hit["action"], "why": why})
    return hit


def pending_ids():
    return [it["id"] for it in read_queue() if it["status"] == "pending"]


def summary():
    items = read_queue()
    out = {}
    for it in items:
        out[it["status"]] = out.get(it["status"], 0) + 1
    return out


# ---------- CLI ----------
def cmd_status(_a):
    cfg = load_config()
    print("发送模式：%s（%s）" % (
        "人工确认" if cfg["send_mode"] == "confirm" else "全自动", cfg["send_mode"]))
    print("受管动作：%s" % ", ".join(cfg.get("gated_actions") or []))
    print("上次变更：%s by %s" % (cfg.get("updated") or "-", cfg.get("updated_by")))
    print("队列：%s" % (summary() or "空"))


def cmd_mode(a):
    cfg = load_config()
    if a.mode == "confirm":
        cfg["send_mode"] = "confirm"
    elif a.mode == "auto":
        cfg["send_mode"] = "auto"
    else:
        raise SystemExit("mode 只能是 confirm 或 auto")
    save_config(cfg, by=a.by)
    audit({"action": "gate_mode", "mode": a.mode, "by": a.by})
    print("已切换为 %s" % ("人工确认" if a.mode == "confirm" else "全自动"))


def cmd_list(a):
    items = read_queue()
    if a.status:
        items = [x for x in items if x["status"] == a.status]
    if not items:
        print("队列为空")
        return
    for it in items[-a.limit:]:
        print("%-14s %-7s %-8s %-24s %s" % (
            it["id"], it["status"], it["action"], it["domain"], (it.get("url") or "")[:60]))
        if it.get("note"):
            print("      %s" % it["note"][:120])


def cmd_approve(a):
    hit = decide(a.id, "approved", a.why)
    print("已放行 %s (%s)" % (a.id, hit["domain"]) if hit else "没有这个 id")


def cmd_reject(a):
    hit = decide(a.id, "rejected", a.why)
    print("已拒绝 %s (%s)" % (a.id, hit["domain"]) if hit else "没有这个 id")


UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def cmd_flush(a):
    """把已批准的排队项真正发出去（默认只演练）。"""
    items = read_queue()
    todo = [i for i in items if i["status"] == "approved" and i.get("payload")]
    if a.id:
        todo = [i for i in todo if i["id"] == a.id]
    if not todo:
        print("没有已批准待发送的项")
        return
    import re as _re
    import urllib.parse
    import urllib.request
    for it in todo:
        url = it.get("url") or ""
        if not url:
            print("%s 缺少 url，跳过" % it["id"])
            continue
        if a.dry_run:
            print("[演练] %s %s 字段=%s" % (it["id"], url, ",".join(sorted(it["payload"]))))
            continue
        body = urllib.parse.urlencode(it["payload"]).encode()
        req = urllib.request.Request(url, data=body, headers={
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": url,
            "Origin": _re.match(r"https?://[^/]+", url).group(0),
        }, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                status, final = r.status, r.geturl()
                text = r.read(200000).decode("utf-8", "replace")
        except Exception as e:
            status, final, text = 0, url, str(e)
        it["status"] = "sent" if status in (200, 201, 202) else "send_failed"
        it["sent_at"] = now_iso()
        it["http"] = status
        it["final_url"] = final
        it["excerpt"] = _re.sub(r"\s+", " ", _re.sub(r"<[^>]+>", " ", text))[:200]
        audit({"action": "gate_flush", "queue_id": it["id"], "domain": it["domain"],
               "http": status, "final": final})
        print("%s → HTTP %s %s" % (it["id"], status, final))
    _write_queue(items)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    m = sub.add_parser("mode")
    m.add_argument("mode", choices=("confirm", "auto"))
    m.add_argument("--by", default="cli")
    l = sub.add_parser("list")
    l.add_argument("--status", default="pending")
    l.add_argument("--limit", type=int, default=40)
    f = sub.add_parser("flush")
    f.add_argument("--id", default="")
    f.add_argument("--dry-run", action="store_true")
    a1 = sub.add_parser("approve")
    a1.add_argument("id")
    a1.add_argument("--why", default="")
    r1 = sub.add_parser("reject")
    r1.add_argument("id")
    r1.add_argument("--why", default="")
    a = ap.parse_args()
    {"status": cmd_status, "mode": cmd_mode, "list": cmd_list,
     "approve": cmd_approve, "reject": cmd_reject, "flush": cmd_flush}[a.cmd](a)


if __name__ == "__main__":
    main()
