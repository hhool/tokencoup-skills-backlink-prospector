#!/usr/bin/env python3
"""读取 poki2.online@gmail.com 收件箱，抓注册验证链接。

凭据来源（按优先级）：
  1) 环境变量 POKI2_GMAIL_APP_PASSWORD
  2) ~/.sextant/poki2-gmail.env 里的 export POKI2_GMAIL_APP_PASSWORD=...

用法：
  python3 mail_verify.py --list                 # 最近 30 分钟收到的信（发件人/主题）
  python3 mail_verify.py --domain reddit.com --wait 180   # 等并抓该站验证链接
"""
import argparse
import email
import imaplib
import json
import os
import quopri
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from email.header import decode_header

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from identity import identity, require_password, ENV_FILE  # noqa: E402

EMAIL_ADDR = identity()["email"]
LINK_KEYS = ("verify", "confirm", "activate", "activation", "validate",
             "registration", "welcome", "onboard", "magic", "token")


def now_iso():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def load_password():
    i = identity()
    return i["password"], ("env" if os.environ.get("POKI2_GMAIL_APP_PASSWORD") else i["env_file"])


def connect(pw):
    m = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=30)
    m.login(EMAIL_ADDR, pw)
    return m


def decode_hdr(raw):
    if not raw:
        return ""
    out = []
    for part, enc in decode_header(raw):
        if isinstance(part, bytes):
            out.append(part.decode(enc or "utf-8", "replace"))
        else:
            out.append(part)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def body_text(msg):
    """尽量取出可读正文（含 quoted-printable / base64）。"""
    chunks = []
    for part in msg.walk():
        ct = part.get_content_type()
        if ct not in ("text/plain", "text/html"):
            continue
        raw = part.get_payload(decode=True)
        if raw is None:
            continue
        cs = part.get_content_charset() or "utf-8"
        try:
            chunks.append(raw.decode(cs, "replace"))
        except LookupError:
            chunks.append(raw.decode("utf-8", "replace"))
    return "\n".join(chunks)


def links_in(text):
    urls = re.findall(r'https?://[^\s"\'<>\)\]\}]+', text)
    clean = []
    for u in urls:
        u = u.rstrip('.,;:')
        u = u.replace("&amp;", "&")
        if len(u) < 18:
            continue
        # 常见邮件跟踪跳转：保留原链，交由人工/自动化判断
        clean.append(u)
    return clean


def fetch_recent(m, minutes=30, want_domain="", limit=20):
    since = (datetime.now(timezone.utc) - timedelta(minutes=minutes))
    crit = since.strftime("%d-%b-%Y")
    typ, data = m.search(None, '(SINCE "%s")' % crit)
    if typ != "OK":
        return []
    ids = (data[0] or b"").split()
    out = []
    for uid in reversed(ids[-limit:]):
        typ, msgdata = m.fetch(uid, "(RFC822)")
        if typ != "OK" or not msgdata or not msgdata[0]:
            continue
        msg = email.message_from_bytes(msgdata[0][1])
        frm = decode_hdr(msg.get("From"))
        subj = decode_hdr(msg.get("Subject"))
        date = msg.get("Date", "")
        text = body_text(msg)
        ls = links_in(text)
        if want_domain:
            d = want_domain.lower().lstrip("www.")
            keep = [u for u in ls if d in u.lower()]
            if not keep and d not in (frm + subj).lower():
                continue
            ranked = sorted(keep, key=lambda u: (
                -sum(k in u.lower() for k in LINK_KEYS), len(u)))
            ls = ranked or ls
        out.append({"from": frm, "subject": subj, "date": date,
                    "links": ls[:8], "domain_match": bool(want_domain)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="", help="只看该域名的验证信")
    ap.add_argument("--minutes", type=int, default=30)
    ap.add_argument("--wait", type=int, default=0, help="轮询等待秒数")
    ap.add_argument("--interval", type=int, default=20)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--json-out", default="")
    a = ap.parse_args()

    _, err = require_password()
    if err:
        print(err, file=sys.stderr)
        return 2
    pw, src = load_password()

    deadline = time.time() + a.wait
    found = []
    while True:
        try:
            m = connect(pw)
        except imaplib.IMAP4.error as e:
            print("IMAP 登录失败：%s（应用专用密码 16 位、需账号已开两步验证）" % e,
                  file=sys.stderr)
            return 3
        except OSError as e:
            print("IMAP 连接失败：%s" % e, file=sys.stderr)
            return 3
        try:
            m.select("INBOX")
            found = fetch_recent(m, a.minutes, a.domain)
        finally:
            try:
                m.logout()
            except Exception:
                pass
        if found or time.time() >= deadline:
            break
        time.sleep(a.interval)

    print("凭据来源：%s · 匹配 %d 封" % (src or "env", len(found)))
    for f in found:
        print("\n[%s] %s\n  %s" % (f["date"][:31], f["from"][:60], f["subject"][:90]))
        for u in f["links"][:5]:
            print("   -> %s" % u[:150])
    if a.json_out:
        json.dump({"checked_at": now_iso(), "domain": a.domain, "messages": found},
                  open(a.json_out, "w"), ensure_ascii=False, indent=1)
        print("\n已写入 %s" % a.json_out)
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())
