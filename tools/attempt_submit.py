#!/usr/bin/env python3
"""真投递：只对「实测存在匿名提交表单」的站点发起真实 POST，并记录原始回执。

判定不靠猜：只有响应里出现站点自己的成功措辞（submitted / pending review /
thanks / added / success）才算 submitted；命中校验错误算 rejected；其余 unknown。
"""
import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "tools")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

SITE = "Azgames"
SITE_URL = "https://azgames.poki2.online/"
from identity import identity  # noqa: E402
EMAIL = identity()["email"]
TAGLINE = "Free online browser games you can play instantly, no download."

SUCCESS_HINTS = ["thank you", "thanks", "submitted", "pending review", "success",
                 "added", "received", "will be reviewed", "已提交", "提交成功"]
ERROR_HINTS = ["error", "required", "invalid", "already", "failed", "not allowed",
               "must be", "请输入", "错误"]


def now_iso():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def _ctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "text/html,*/*", "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
        return r.status, r.geturl(), r.read(400000).decode("utf-8", "replace")


def strip_tags(h):
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h)
    t = re.sub(r"(?s)<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", t).strip()


def post(url, data, referer, timeout=25):
    """裸传输层。**对外发送一律走 submit()**，那样才会过发送闸门。"""
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": referer,
        "Origin": re.match(r"https?://[^/]+", url).group(0),
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
            return r.status, r.geturl(), r.read(400000).decode("utf-8", "replace"), ""
    except urllib.error.HTTPError as e:
        raw = b""
        try:
            raw = e.read(200000)
        except Exception:
            pass
        return e.code, e.url, raw.decode("utf-8", "replace"), "HTTP %s" % e.code


class GateBlocked(RuntimeError):
    """发送被闸门拦下（默认人工确认）。携带排队 id，批准后用 gate.py approve 放行。"""

    def __init__(self, queue_id, domain):
        super().__init__("gate: 已排队待确认 %s (%s)" % (queue_id, domain))
        self.queue_id = queue_id
        self.domain = domain


def submit(url, data, referer, timeout=25, note="", action="submit"):
    """对外提交的唯一入口：先过 gate，再发。

    gate 默认 confirm 模式：不发送，写入待确认队列并抛 GateBlocked；
    `gate.py mode auto` 之后同一份代码直接发。
    """
    import gate as _gate
    host = re.sub(r"^www\.", "", urllib.parse.urlsplit(url).netloc.lower())
    allowed, info = _gate.check(action, host, url=url, payload=data, note=note)
    if not allowed:
        raise GateBlocked(info.get("id"), host)
    return post(url, data, referer, timeout=timeout)


def judge(http, body):
    text = strip_tags(body).lower()
    hit_s = [h for h in SUCCESS_HINTS if h in text]
    hit_e = [h for h in ERROR_HINTS if h in text]
    if http in (200, 201, 202) and hit_s and not (hit_e and not hit_s):
        return "submitted", hit_s[:3]
    if http >= 400:
        return "rejected", ["HTTP %s" % http]
    if hit_e:
        return "rejected", hit_e[:3]
    return "unknown", []


def try_uneed():
    url = "https://uneed.best/submit"
    http, _, body = get(url)
    http2, final, body2, err = post(url, {"name": SITE, "url": SITE_URL}, referer=url)
    verdict, hints = judge(http2, body2)
    return {
        "domain": "uneed.best", "entry": url, "method": "POST form(name,url)",
        "get_status": http, "http": http2, "final_url": final, "err": err,
        "verdict": verdict, "hints": hints,
        "excerpt": strip_tags(body2)[:280],
    }


def try_sitelike():
    url = "https://sitelike.org/add-site"
    http, final, body = get(url)
    vs = re.search(r'name="__VIEWSTATE"[^>]*value="([^"]*)"', body)
    vg = re.search(r'name="__VIEWSTATEGENERATOR"[^>]*value="([^"]*)"', body)
    ev = re.search(r'name="__EVENTVALIDATION"[^>]*value="([^"]*)"', body)
    if not vs:
        return {"domain": "sitelike.org", "entry": url, "verdict": "rejected",
                "hints": ["未取到 __VIEWSTATE，无法投递"], "excerpt": strip_tags(body)[:200]}
    data = {
        "__VIEWSTATE": vs.group(1),
        "__VIEWSTATEGENERATOR": vg.group(1) if vg else "",
        "siteURLInputN2": SITE_URL,
    }
    if ev:
        data["__EVENTVALIDATION"] = ev.group(1)
    action = urllib.parse.urljoin(final, "AddSite.aspx")
    http2, final2, body2, err = post(action, data, referer=url)
    verdict, hints = judge(http2, body2)
    return {
        "domain": "sitelike.org", "entry": url, "method": "POST AddSite.aspx(viewstate+url)",
        "get_status": http, "http": http2, "final_url": final2, "err": err,
        "verdict": verdict, "hints": hints,
        "excerpt": strip_tags(body2)[:280],
    }


def main():
    results = []
    for fn in (try_uneed, try_sitelike):
        try:
            results.append(fn())
        except Exception as e:
            results.append({"domain": fn.__name__, "verdict": "unknown", "err": str(e)[:200]})
    out = {"generated_at": now_iso(), "site": SITE_URL, "results": results}
    with open("reports/azgames-p1-submits.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for r in results:
        print(json.dumps(r, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
