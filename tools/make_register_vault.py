#!/usr/bin/env python3
"""注册凭据保险库：为需要账号的外链目标生成唯一密码并落盘留痕。

- 路径：~/seo/.vault/<site>-accounts.json（目录 0700，文件 0600）
- 幂等：同一 domain 已存在则沿用旧密码，不重置
- 留痕：每次创建/读取都追加到 ~/seo/.vault/audit.log（JSONL）

用法：
  python3 make_register_vault.py --site azgames.poki2.online \
      --email poki2.online@gmail.com --probe reports/azgames-p1-probe.json
"""
import argparse
import json
import os
import secrets
import string
from datetime import datetime, timedelta, timezone

VAULT_DIR = os.path.expanduser("~/seo/.vault")

# 各站注册入口（实测/官方文档已知路径，confidence 标注可信度）
REGISTER_URLS = {
    "reddit.com": ("https://www.reddit.com/register", "high"),
    "substack.com": ("https://substack.com/signup", "high"),
    "medium.com": ("https://medium.com/m/signin", "high"),
    "facebook.com": ("https://www.facebook.com/reg", "high"),
    "pr.com": ("https://www.pr.com/register", "medium"),
    "featured.com": ("https://featured.com/signup", "medium"),
    "dev.to": ("https://dev.to/enter?state=new-user", "high"),
    "v2ex.com": ("https://www.v2ex.com/signup", "medium"),
    "hashnode.com": ("https://hashnode.com/onboard", "high"),
    "advertcn.com": ("https://www.advertcn.com/member.php?mod=register", "medium"),
    "growthhackers.com": ("https://growthhackers.com/signup", "medium"),
    "warriorforum.com": ("https://www.warriorforum.com/register.php", "medium"),
    "hostloc.com": ("https://hostloc.com/member.php?mod=register", "low"),
    "raindrop.io": ("https://app.raindrop.io/", "medium"),
    "getpocket.com": ("https://getpocket.com/signup", "high"),
    "flipboard.com": ("https://flipboard.com/signup", "medium"),
    "newsbreak.com": ("https://www.newsbreak.com/publisher", "low"),
}

# 无需注册或不应注册（注明原因）
NO_ACCOUNT = {
    "en.wikipedia.org": "禁自推（WP:NOTPROMO），不应注册投递",
    "ghost.org": "Ghost 是自建博客软件，非社区；无 ghost.org 外链出口",
    "discord.com": "需具体服务器邀请，无通用提交入口",
}

ALNUM = string.ascii_letters + string.digits


def gen_password(n=20):
    # 只用字母数字：避免部分站点的表单/校验拒绝特殊字符
    while True:
        pw = "".join(secrets.choice(ALNUM) for _ in range(n))
        if any(c.islower() for c in pw) and any(c.isupper() for c in pw) \
                and any(c.isdigit() for c in pw):
            return pw


def audit(site, action, **kw):
    os.makedirs(VAULT_DIR, mode=0o700, exist_ok=True)
    rec = {"ts": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
           "site": site, "action": action}
    rec.update(kw)
    path = os.path.join(VAULT_DIR, "audit.log")
    with open(path, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    os.chmod(path, 0o600)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--email", default="",
                    help="默认取 ~/.sextant/poki2-gmail.env 的 POKI2_GMAIL_ADDRESS")
    ap.add_argument("--probe", required=True)
    ap.add_argument("--handle", default="azgameshub")
    a = ap.parse_args()

    if not a.email:
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from identity import identity as _ident
        a.email = _ident()["email"]

    probe = json.load(open(a.probe))
    os.makedirs(VAULT_DIR, mode=0o700, exist_ok=True)
    os.chmod(VAULT_DIR, 0o700)
    path = os.path.join(VAULT_DIR, "%s-accounts.json" % a.site)

    data = {"site": a.site, "email": a.email, "handle": a.handle,
            "created_at": "", "note": "明文存储（用户指定落盘留痕），文件 0600", "accounts": {}}
    if os.path.exists(path):
        data = json.load(open(path))

    created, reused = [], []
    for r in probe["results"]:
        dom = r["domain"]
        if dom in NO_ACCOUNT:
            continue
        if dom in data["accounts"]:
            reused.append(dom)
            continue
        reg_url, conf = REGISTER_URLS.get(dom, ("", "low"))
        data["accounts"][dom] = {
            "email": a.email,
            "username": a.handle,
            "display_name": "Azgames",
            "password": gen_password(),
            "register_url": reg_url,
            "url_confidence": conf,
            "gate_probe": r["gate"],
            "entry_http": r["http_status"],
            "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
            "state": "generated",
        }
        created.append(dom)

    data["created_at"] = data.get("created_at") or \
        datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.chmod(path, 0o600)

    audit(a.site, "vault_write", file=path, created=len(created), reused=len(reused),
          email=a.email, domains=created)

    print("vault: %s (%d 新增 / %d 沿用)" % (path, len(created), len(reused)))
    for d in created:
        acc = data["accounts"][d]
        print("  %-20s %-46s %s" % (d, acc["register_url"] or "(未知入口)", acc["password"]))
    if reused:
        print("沿用以避免重置：%s" % ", ".join(reused))


if __name__ == "__main__":
    main()
