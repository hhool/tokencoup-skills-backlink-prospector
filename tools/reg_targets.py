#!/usr/bin/env python3
"""把「需注册」的站点补进凭据库：找到每站真实注册入口，生成唯一密码。

幂等：已存在的账号沿用旧密码，不重置；新补的写进 audit.log。
入口发现顺序：台账 owner_note 里的入口 → 首页上的注册/登录链接 → 常见路径。
"""
import argparse
import json
import os
import re
import secrets
import string
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VAULT_DIR = os.path.expanduser("~/seo/.vault")
ACCOUNTS = os.path.join(VAULT_DIR, "azgames.poki2.online-accounts.json")
AUDIT = os.path.join(VAULT_DIR, "audit.log")
SITE_DIR = os.path.expanduser("~/seo/azgames.poki2.online")

PATHS = ["/register", "/signup", "/sign-up", "/join", "/users/sign_up",
         "/accounts/signup", "/account/register", "/members/register",
         "/register.php", "/forum/ucp.php?mode=register", "/enter",
         "/submit", "/auth/register", "/user/register"]

LINK_RE = re.compile(
    r"(?i)(sign[\s_-]?up|register|create[\s_-]?(an[\s_-]?)?account|join|"
    r"get[\s_-]?started|新規登録|aanmelden|inschrijven|registreren)")

SKIP = re.compile(r"(?i)(newsletter|subscribe|login|sign[\s_-]?in|password|"
                  r"advertis|sponsor|careers|job)")


def now_iso():
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def audit(rec):
    os.makedirs(VAULT_DIR, exist_ok=True)
    rec = dict(rec, ts=now_iso())
    with open(AUDIT, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def new_password(n=20):
    alpha = string.ascii_letters + string.digits
    return "".join(secrets.choice(alpha) for _ in range(n))


def load():
    with open(ACCOUNTS) as f:
        return json.load(f)


def save(data):
    tmp = ACCOUNTS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ACCOUNTS)
    try:
        os.chmod(ACCOUNTS, 0o600)
    except OSError:
        pass


def targets_needing_accounts():
    out = []
    with open(os.path.join(SITE_DIR, "targets.jsonl")) as f:
        for line in f:
            t = json.loads(line)
            tags = t.get("tags") or []
            if any(g in tags for g in ("gate:account_required", "gate:captcha")):
                out.append(t)
    return out


def entry_from_note(note):
    m = re.search(r"入口\s*(https?://\S+)", note or "")
    return m.group(1) if m else ""


def discover(dom):
    from azgames_autopilot import Session
    s = Session()
    base = "https://%s" % dom
    home = s.get(base + "/", timeout=20)
    if not home["ok"]:
        home = s.get("http://%s/" % dom, timeout=20)
    cands = []
    if home["ok"]:
        b = home["body"] or ""
        for m in re.finditer(r'(?is)<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', b):
            href, txt = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
            if not (LINK_RE.search(href) or LINK_RE.search(txt)):
                continue
            if SKIP.search(href) or SKIP.search(txt):
                continue
            import urllib.parse
            u = urllib.parse.urljoin(home["final_url"] or base, href)
            if dom not in u:
                continue
            if u not in cands:
                cands.append(u)
    for p in PATHS:
        u = base + p
        if u not in cands:
            cands.append(u)
    # 逐个验证：能打开、且页面里像注册表单（有 password 或 email 字段）
    for u in cands[:12]:
        r = s.get(u, timeout=15)
        if not r["ok"] or r["status"] >= 400:
            continue
        low = r["body"].lower()
        has_pwd = 'type="password"' in low or "type='password'" in low
        has_email = 'type="email"' in low or 'name="email"' in low or 'name="mail"' in low
        if has_pwd or has_email:
            login_url = ""
            m = re.search(r'href="([^"]*(login|signin|sign-in)[^"]*)"', low)
            if m and dom in m.group(1):
                import urllib.parse
                login_url = urllib.parse.urljoin(r["final_url"] or base, m.group(1))
            return {"register_url": r["final_url"] or u, "login_url": login_url,
                    "confidence": "form_detected" if has_pwd else "fields_only"}
    return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    data = load()
    accs = data["accounts"]
    todo = [t for t in targets_needing_accounts() if t["domain"] not in accs]
    if a.limit:
        todo = todo[:a.limit]
    print("待补入口 %d 站（库内已有 %d）" % (len(todo), len(accs)))
    if a.dry_run:
        for t in todo:
            print("  ", t["domain"], entry_from_note(t.get("owner_note") or "") or "(需探测)")
        return

    from concurrent.futures import ThreadPoolExecutor, as_completed
    found = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(discover, t["domain"]): t for t in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            t = futs[fut]
            dom = t["domain"]
            try:
                info = fut.result()
            except Exception as e:
                info = {}
                print("  %-26s 探测异常 %s" % (dom, str(e)[:60]))
            note_entry = entry_from_note(t.get("owner_note") or "")
            reg = info.get("register_url") or note_entry or ("https://%s/" % dom)
            accs[dom] = {
                "email": data["email"],
                "username": data.get("handle") or "azgameshub",
                "password": new_password(),
                "register_url": reg,
                "login_url": info.get("login_url", ""),
                "confidence": info.get("confidence") or ("note_hint" if note_entry else "home_only"),
                "created": now_iso(),
                "source": "reg_targets",
            }
            found += 1
            print("  %-26s %-14s %s" % (dom, accs[dom]["confidence"], reg[:70]))
    data["accounts"] = accs
    save(data)
    audit({"action": "vault_expand", "added": found, "total": len(accs),
           "tool": "reg_targets.py"})
    print("\n新增 %d 站，库内共 %d 站（0600 已设）" % (found, len(accs)))


if __name__ == "__main__":
    main()
