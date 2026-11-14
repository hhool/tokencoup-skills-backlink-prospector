#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only entry discovery: where does this site accept a submission, or who do I mail?

The delivery loop stalls on two values it cannot invent: ``submission_url`` (the
page hosting a submission form) and ``contact_email``. Both are observable from
outside without transmitting anything, so this tool observes them once and writes
an overlay the contract-C export folds into the snapshot.

What it does, per domain:

  1. fetch robots.txt, and honour it (a disallowed path is never requested);
  2. fetch the entry page; if it already carries a usable form, stop there;
  3. otherwise collect same-host links, score them against a path lexicon
     (/submit, /guest-post, /write-for-us, /advertise, /contact, ...), and fetch
     the best few within a per-domain page budget;
  4. parse every form: action, method, field names. A search box, a login form and
     a one-field newsletter are not submission forms and are rejected;
  5. collect addresses from ``mailto:`` links and from page prose;
  6. emit one record per domain, with provenance and a page count.

Three properties matter more than coverage:

  * **No transmission.** Every request is a GET. Nothing is posted, nothing is
    mailed, no form is touched. Discovery is observation, like the L4 observer.
  * **A miss is not a negative.** "No form found" inside a page budget means the
    budget ran out, not that the site has no form. The record says how many pages
    were read so a reader can tell the difference.
  * **One request per URL, cached.** Re-running is cheap, and a crawl cannot turn
    into a load test. The cache also makes an audit possible: the exact HTML that
    produced a decision is still on disk.

Usage
-----
    python3 tools/discover_entry.py --store data/store-soundbuttons.cc.json \\
        --out data/enrichment-soundbuttons.cc.json --resume

    python3 tools/discover_entry.py --store data/store-soundbuttons.cc.json \\
        --limit 5 --max-pages 6 --dry-run

    python3 tools/discover_entry.py --selftest        # offline, no network

Options that change behaviour live in DEFAULTS below; every one is also a flag.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

TOOL = "discover_entry/1.0.0"
USER_AGENT = "Mozilla/5.0 (compatible; tokencoup-prospector-discover/1.0; +https://github.com/hhool/tokencoup-skills-backlink-prospector)"

DEFAULTS: Dict[str, Any] = {
    "max_pages": 8,          # per domain, home included
    "delay": 0.8,            # seconds between requests to the same host
    "timeout": 15,
    "cache_days": 30,
    "cache_dir": "data/cache",
    "max_links": 120,        # links considered per page
    "email_limit": 3,        # contact candidates kept per domain
    # Submission pages are usually reachable but often unlinked, so a bounded
    # probe runs after the link crawl when nothing usable was found.
    "probe_paths": ["/contact", "/contact-us", "/submit", "/add", "/advertise"],
    "probe_budget": 3,
}

# ---------------------------------------------------------------------------
# Path lexicon. Higher wins; anything that scores 0 is never fetched.
# ---------------------------------------------------------------------------

_PATH_RULES: List[Tuple[int, str]] = [
    (100, r"/(?:submit|submission|add-?(?:a-?)?(?:link|site|url|listing|resource|tool)|suggest|"
          r"guest-?post|write-?for-?us|contribute|advertise|promote|partnerships?)(?:[/?#\-.]|$)"),
    (70, r"/(?:contact|contact-?us|about|about-?us|imprint|imprint-?legal|support|help|feedback|"
         r"get-?in-?touch)(?:[/?#\-.]|$)"),
    (45, r"/(?:resources?|links?|directory|directories|press|media|partners?|vendors?|"
         r"community|forum)(?:[/?#\-.]|$)"),
]

_PATH_NEGATIVE = re.compile(
    r"/(?:blog|news|article|articles|tag|tags|category|categories|author|authors|page|search|"
    r"cart|checkout|login|signin|sign-in|register|privacy|terms|tos|cookies?|legal|"
    r"rss|feed|amp|cdn-cgi)(?:[/?#]|$)",
    re.I,
)

# A form is a submission form only if it can carry a URL and words. These are the
# shapes that never do.
_SEARCH_HINTS = re.compile(r"search|query|find|filter", re.I)
_LOGIN_FIELDS = {"password", "pass", "login", "username", "user_login", "signin"}
_NEWSLETTER_ONLY = {"email", "email_address", "mail"}

# Field name synonyms. Two sites running the same plugin should land on the same
# shape hash, so the normalisation has to be opinionated.
_FIELD_SYNONYMS: List[Tuple[str, str]] = [
    (r"^(?:your|the|my)?[_-]?(?:full[_-]?)?name\d*$", "name"),
    (r"^(?:first|last|given|family|sur)[_-]?(?:name)?\d*$", "name"),
    (r"^(?:your|the|my)?[_-]?(?:e[_-]?mail|email[_-]?address|mail|emailaddr)\d*$", "email"),
    (r"^(?:your|the|my)?[_-]?(?:web[_-]?site|website[_-]?url|site[_-]?url|url|link|link[_-]?url|"
     r"homepage|webpage)\d*$", "url"),
    (r"^(?:your|the|my)?[_-]?(?:message|comment|comments|description|desc|details|detail|note|"
     r"notes|text|content|body|about|summary)\d*$", "message"),
    (r"^(?:your|the|my)?[_-]?(?:subject|topic|title|heading|headline)\d*$", "subject"),
    (r"^(?:your|the|my)?[_-]?(?:company|organization|organisation|business|brand)\d*$", "company"),
    (r"^(?:your|the|my)?[_-]?(?:phone|tel|telephone|mobile)\d*$", "phone"),
    (r"^(?:captcha|recaptcha|g-recaptcha|h-captcha|hcaptcha)\d*$", "captcha"),
]

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}")
_MAILTO_RE = re.compile(r"^mailto:([^?\s]+)", re.I)
_ASSET_MAIL_RE = re.compile(r"\.(?:png|jpe?g|gif|webp|svg|css|js|woff2?|ttf)$", re.I)
_DEAD_LOCALPARTS = {"noreply", "no-reply", "donotreply", "do-not-reply", "postmaster", "abuse"}
_PLACEHOLDER_DOMAINS = {
    "example.com", "example.org", "domain.com", "yourdomain.com", "yoursite.com",
    "email.com", "mail.com", "site.com", "company.com", "test.com", "sentry.io",
    "wixpress.com", "sentry-next.wixpress.com", "godaddy.com",
}
# Plugin field names that carry no meaning: the label beside them does.
_OPAQUE_NAME = re.compile(
    r"(?:wpforms|gform|wpcf7|contact-?form|forminator|ninja|gravity|"
    r"fields?|entry|input|field)[\[\-_ ]?\d",
    re.I,
)
# A field a human never fills. Auto-fill must leave these empty: a bot that fills
# a honeypot has announced itself, whatever the rest of the form says.
_HONEYPOT = re.compile(
    r"(?:^|[\[\-_])(?:hp|honeypot|gotcha|botcheck|antispam|spam)(?:$|[\]\-_\d])", re.I
)

FetchFunc = Callable[[str, int], Tuple[int, str]]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def registrable(host: str) -> str:
    text = (host or "").strip().lower()
    if text.startswith("www."):
        text = text[4:]
    return text


def host_of(url: str) -> str:
    try:
        return registrable(urllib.parse.urlsplit(url).netloc.split(":")[0])
    except ValueError:
        return ""


def normalise_field(name: str) -> str:
    """Reduce a form field name to the slot it means, not the label it uses."""
    base = re.sub(r"[^a-z0-9_\-]", "", (name or "").strip().lower())
    base = base.strip("_-")
    if not base:
        return ""
    for pattern, slot in _FIELD_SYNONYMS:
        if re.match(pattern, base):
            return slot
    # strip a trailing index (url_1, email2) before giving up
    trimmed = re.sub(r"[_\-]?\d+$", "", base)
    if trimmed != base:
        for pattern, slot in _FIELD_SYNONYMS:
            if re.match(pattern, trimmed):
                return slot
    return base


def shape_of(method: str, slots: Iterable[str]) -> str:
    """Host-independent form identity.

    Field names only, sorted and deduplicated: two sites running the same
    submission plugin produce the same shape, so one reviewed field mapping can
    serve both. The per-site `fingerprint` in the delivery loop stays the audit
    key; this is the reuse key.
    """
    material = (method or "post").lower() + "|" + ",".join(sorted(set(s for s in slots if s)))
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def score_path(path: str) -> int:
    if not path or _PATH_NEGATIVE.search(path):
        return 0
    best = 0
    for weight, pattern in _PATH_RULES:
        if re.search(pattern, path, re.I):
            best = max(best, weight)
    return best


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

class _FormParser(HTMLParser):
    """Collect forms with their fields, labels and honeypots.

    Field *names* are often meaningless - WPForms writes ``wpforms[fields][0]``,
    Gravity Forms writes ``input_3`` - while the visible ``<label>`` says "Your
    Name". Both are kept: the name is what a submission needs, the label is what
    tells us which slot it is. Labels are resolved when the form closes, so a
    label placed after its input still lands.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: List[Dict[str, Any]] = []
        self._current: Optional[Dict[str, Any]] = None
        self._labels: Dict[str, str] = {}
        self._label: Optional[Dict[str, Any]] = None

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        if tag == "label":
            self._label = {"for": values.get("for", "").strip(), "text": []}
            return
        if tag == "form":
            if self._current is not None:
                self._close()
            self._current = {
                "action": values.get("action", "").strip(),
                "method": (values.get("method") or "get").strip().lower(),
                "fields": [],
                "meta": {},
                "has_textarea": False,
            }
            return
        if self._current is None:
            return
        if tag == "textarea":
            self._current["has_textarea"] = True
        if tag not in ("input", "textarea", "select"):
            return
        name = values.get("name", "").strip()
        if not name:
            return
        default_type = {"textarea": "textarea", "select": "select"}.get(tag, "text")
        self._current["fields"].append(name)
        self._current["meta"][name] = {
            "type": (values.get("type") or default_type).lower(),
            "placeholder": values.get("placeholder", "").strip(),
            "aria": values.get("aria-label", "").strip(),
            "title": values.get("title", "").strip(),
            "id": values.get("id", "").strip(),
            "label": "",
        }

    def handle_data(self, data: str) -> None:
        if self._label is not None and data and data.strip():
            self._label["text"].append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag == "label" and self._label is not None:
            text = " ".join(self._label["text"]).strip()
            if self._label["for"] and text:
                self._labels[self._label["for"]] = text
            self._label = None
            return
        if tag == "form" and self._current is not None:
            self._close()

    def _close(self) -> None:
        current = self._current
        self._current = None
        if current is None:
            return
        for name, meta in current["meta"].items():
            if meta.get("label"):
                continue
            meta["label"] = (
                self._labels.get(meta.get("id", ""), "")
                or meta.get("aria", "")
                or meta.get("placeholder", "")
                or meta.get("title", "")
            )
        self.forms.append(current)

    def close(self) -> None:  # noqa: A003 - HTMLParser API
        super().close()
        if self._current is not None:
            self._close()


class _LinkParser(HTMLParser):
    """Collect anchors, mailto addresses and Cloudflare-obfuscated addresses."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: List[str] = []
        self.mailto: List[str] = []
        self.cfemail: List[str] = []
        self.text: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        for key, value in attrs:
            if key.lower() == "data-cfemail" and value:
                decoded = decode_cfemail(value.strip())
                if decoded:
                    self.cfemail.append(decoded)
        if tag != "a":
            return
        href = ""
        for key, value in attrs:
            if key.lower() == "href" and value:
                href = value.strip()
                break
        if not href:
            return
        match = _MAILTO_RE.match(href)
        if match:
            self.mailto.append(urllib.parse.unquote(match.group(1)))
        elif not href.startswith(("#", "javascript:", "tel:")):
            self.hrefs.append(href)

    def handle_data(self, data: str) -> None:
        if data and data.strip():
            self.text.append(data)


def decode_cfemail(value: str) -> str:
    """Cloudflare replaces addresses with data-cfemail="<key><xor bytes>".

    Sites behind Cloudflare hide every address this way, so a crawler that only
    reads text sees zero addresses on exactly the sites that care most about spam.
    """
    try:
        raw = bytes.fromhex(value)
    except ValueError:
        return ""
    if len(raw) < 2:
        return ""
    key = raw[0]
    decoded = "".join(chr(byte ^ key) for byte in raw[1:])
    return decoded if _EMAIL_RE.fullmatch(decoded) else ""


def is_honeypot(name: str) -> bool:
    return bool(_HONEYPOT.search(name or ""))


# Fields the browser sends but a human never sees. They must be submitted, so they
# stay in the field list, but they must not enter the shape: a CSRF token or a
# plugin's internal id differs on every site and would make every shape unique.
_TECHNICAL = re.compile(
    r"(?:csrf|token|nonce|_wpnonce|wpforms\[(?:id|post_id)\]|page_?(?:title|url|id)|"
    r"url_referer|redirect|referer|referrer|^utm_)",
    re.I,
)
_KNOWN_SLOTS = {"name", "email", "url", "message", "subject", "company", "phone", "captcha"}


def is_technical(name: str, meta: Dict[str, Any]) -> bool:
    if str(meta.get("type", "")).lower() == "hidden":
        return True
    return bool(_TECHNICAL.search(name or ""))


def slot_of(name: str, meta: Dict[str, Any]) -> str:
    """The slot a field means. Falls back to the label when the name is opaque."""
    direct = normalise_field(name)
    label = normalise_field(str(meta.get("label") or ""))
    slot = direct
    if label and (not direct or _OPAQUE_NAME.search(name) or re.fullmatch(r"[a-z]*\d+", direct)):
        slot = label
    # A textarea whose label is prose ("Tell us about your site") is still the
    # message. Without this, every site's free-text box becomes a unique slot and
    # the shape stops being comparable across sites.
    if slot not in _KNOWN_SLOTS and str(meta.get("type", "")).lower() == "textarea":
        return "message"
    return slot


def classify_form(form: Dict[str, Any], page_url: str) -> Optional[Dict[str, Any]]:
    """Return a usable form record, or None for search / login / signup / honeypot-only."""
    meta: Dict[str, Dict[str, Any]] = form.get("meta", {}) or {}
    fields = [name for name in form.get("fields", []) if name]
    if not fields:
        return None

    honeypots = [name for name in fields if is_honeypot(name)]
    real = [name for name in fields if name not in honeypots]
    technical = [name for name in real if is_technical(name, meta.get(name, {}))]
    visible = [name for name in real if name not in technical]
    if len(visible) < 2:
        return None  # a newsletter box is one field

    slots = [slot_of(name, meta.get(name, {})) for name in visible]
    lowered = {name.lower() for name in visible}
    type_values = {str(item.get("type", "")).lower() for item in meta.values()}

    if lowered & _LOGIN_FIELDS or "password" in type_values:
        return None
    if set(slots) <= _NEWSLETTER_ONLY:
        return None
    action = form.get("action", "")
    if _SEARCH_HINTS.search(action) or _SEARCH_HINTS.search(page_url):
        return None

    has_url = "url" in slots
    has_words = bool(form.get("has_textarea")) or "message" in slots or "subject" in slots
    # A form that can carry an address and an email but nowhere to say what is
    # being submitted is a signup box. Two such fields are the classic false
    # positive: email + website, no message.
    if not has_words:
        return None
    if not has_url and "email" not in slots:
        return None

    action_resolved = urllib.parse.urljoin(page_url, action) if action else page_url
    kind = "submission" if has_url else "contact"
    score = 3 * int(has_url) + 3 * int(bool(form.get("has_textarea"))) + int("email" in slots)
    return {
        "page_url": page_url,
        "action": action_resolved,
        "method": (form.get("method") or "post").lower(),
        "kind": kind,
        "fields": fields,
        "real_fields": real,
        "technical": technical,
        # name -> slot -> type, for every wire field. A consumer cannot zip two
        # lists once hidden tokens are filtered out, so the association is explicit.
        "map": [
            {
                "name": name,
                "slot": ("" if name in honeypots else slot_of(name, meta.get(name, {}))),
                "type": str(meta.get(name, {}).get("type", "")),
                "technical": name in technical,
                "honeypot": name in honeypots,
            }
            for name in fields
        ],
        "slots": slots,
        "shape": shape_of(form.get("method") or "post", slots),
        "has_textarea": bool(form.get("has_textarea")),
        "captcha": "captcha" in slots,
        "honeypots": honeypots,
        "score": score,
    }


def pick_form(forms: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not forms:
        return None
    # A submission form beats a contact form; a captcha is a cost, not a reason to
    # prefer a worse form.
    return sorted(
        forms, key=lambda item: (item["score"], item["kind"] == "submission", not item["captcha"]),
        reverse=True,
    )[0]


def extract_emails(
    text: str, mailto: Iterable[str], domain: str, cfemail: Iterable[str] = ()
) -> List[Dict[str, str]]:
    """Addresses ordered by how much we trust them, not by where they appeared."""
    found: Dict[str, Dict[str, str]] = {}

    def consider(address: str, source: str) -> None:
        candidate = (address or "").strip().strip(".,;:()<>[]\"'").lower()
        if not candidate or "@" not in candidate:
            return
        if _ASSET_MAIL_RE.search(candidate):
            return
        local, _, host = candidate.partition("@")
        if not local or not host or "." not in host:
            return
        if host in _PLACEHOLDER_DOMAINS or host.endswith((".example", ".test", ".invalid", ".local")):
            return
        if local in _DEAD_LOCALPARTS:
            return
        rank = 0
        if registrable(host) == domain:
            rank += 4
        if source in {"mailto", "obfuscated"}:
            rank += 2
        if local in {"contact", "hello", "hi", "info", "editor", "submit", "team", "press", "admin"}:
            rank += 2
        if len(local) <= 2:
            rank -= 1
        current = found.get(candidate)
        if current is None or rank > current["_rank"]:
            found[candidate] = {"address": candidate, "source": source, "_rank": rank}

    for address in cfemail:
        consider(address, "obfuscated")
    for address in mailto:
        consider(address, "mailto")
    for match in _EMAIL_RE.finditer(text or ""):
        consider(match.group(0), "prose")

    ordered = sorted(found.values(), key=lambda item: item["_rank"], reverse=True)
    for item in ordered:
        item.pop("_rank", None)
    return ordered


# ---------------------------------------------------------------------------
# HTTP: cache, robots, fetch
# ---------------------------------------------------------------------------

class Cache:
    """One directory per host, one file per URL, plus the status beside it."""

    def __init__(self, root: str | Path, days: int = 30) -> None:
        self.root = Path(root)
        self.days = days
        self.hits = 0
        self.misses = 0

    def _paths(self, url: str) -> Tuple[Path, Path]:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
        folder = self.root / (host_of(url) or "_")
        return folder / (digest + ".html"), folder / (digest + ".json")

    def get(self, url: str) -> Optional[Tuple[int, str]]:
        body, meta = self._paths(url)
        if not body.is_file() or not meta.is_file():
            self.misses += 1
            return None
        try:
            info = json.loads(meta.read_text(encoding="utf-8"))
            stamp = dt.datetime.strptime(info.get("fetched_at", ""), "%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, OSError, json.JSONDecodeError):
            self.misses += 1
            return None
        age = (dt.datetime.now(dt.timezone.utc) - stamp.replace(tzinfo=dt.timezone.utc)).days
        if age > self.days:
            self.misses += 1
            return None
        self.hits += 1
        return int(info.get("status", 200)), body.read_text(encoding="utf-8", errors="replace")

    def put(self, url: str, status: int, text: str) -> None:
        body, meta = self._paths(url)
        try:
            body.parent.mkdir(parents=True, exist_ok=True)
            body.write_text(text, encoding="utf-8")
            meta.write_text(
                json.dumps({"url": url, "status": status, "fetched_at": now_iso()}), encoding="utf-8"
            )
        except OSError:
            pass  # a cache that cannot write must not stop a run


def default_fetch(url: str, timeout: int = 15) -> Tuple[int, str]:
    """One GET, no cookies, no redirect to another host, no compression games."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        method="GET",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(2_000_000)
            charset = response.headers.get_content_charset() or "utf-8"
            return response.getcode(), raw.decode(charset, "replace")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read(400_000).decode("utf-8", "replace")
        except Exception:
            pass
        return exc.code, body
    except Exception:
        return 0, ""  # DNS, TLS, timeout: unknown, never "absent"


class Robots:
    """robots.txt per host, fetched once and honoured for every later request."""

    def __init__(self, fetch: FetchFunc, timeout: int) -> None:
        self._fetch = fetch
        self._timeout = timeout
        self._seen: Dict[str, Tuple[Optional[urllib.robotparser.RobotFileParser], str]] = {}

    def state(self, url: str) -> Tuple[Optional[urllib.robotparser.RobotFileParser], str]:
        host = host_of(url)
        if host in self._seen:
            return self._seen[host]
        parts = urllib.parse.urlsplit(url)
        target = "%s://%s/robots.txt" % (parts.scheme or "https", parts.netloc)
        status, body = self._fetch(target, self._timeout)
        if status == 200 and body.strip():
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(body.splitlines())
            entry: Tuple[Optional[urllib.robotparser.RobotFileParser], str] = (parser, "parsed")
        elif status in (401, 403):
            # A robots.txt that refuses to be read is not permission.
            entry = (None, "unreadable")
        elif status == 0:
            entry = (None, "unknown")
        else:
            entry = (None, "absent")
        self._seen[host] = entry
        return entry

    def allowed(self, url: str, user_agent: str = "*") -> Tuple[bool, str]:
        parser, state = self.state(url)
        if parser is None:
            return (state == "absent"), state
        try:
            return parser.can_fetch(user_agent, url), state
        except Exception:
            return False, state

    def crawl_delay(self, url: str, user_agent: str = "*") -> float:
        parser, _ = self.state(url)
        if parser is None:
            return 0.0
        try:
            value = parser.crawl_delay(user_agent)
        except Exception:
            value = None
        try:
            return float(value) if value else 0.0
        except (TypeError, ValueError):
            return 0.0


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _same_host(url: str, domain: str) -> bool:
    return host_of(url) == domain


def _candidate_links(html_text: str, page_url: str, domain: str, limit: int) -> List[Tuple[int, str]]:
    parser = _LinkParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:
        pass
    scored: Dict[str, int] = {}
    for href in parser.hrefs[: limit * 3]:
        absolute = urllib.parse.urljoin(page_url, href)
        absolute = urllib.parse.urldefrag(absolute)[0]
        if not absolute.startswith(("http://", "https://")):
            continue
        if not _same_host(absolute, domain):
            continue
        score = score_path(urllib.parse.urlsplit(absolute).path or "/")
        if score <= 0:
            continue
        if absolute not in scored or score > scored[absolute]:
            scored[absolute] = score
    ordered = sorted(scored.items(), key=lambda item: (-item[1], len(item[0]), item[0]))
    return [(score, url) for url, score in ordered[:limit]]


def discover_domain(
    domain: str,
    entry_url: str,
    fetch: FetchFunc,
    cache: Optional[Cache] = None,
    max_pages: int = DEFAULTS["max_pages"],
    delay: float = DEFAULTS["delay"],
    timeout: int = DEFAULTS["timeout"],
    email_limit: int = DEFAULTS["email_limit"],
    refresh: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> Dict[str, Any]:
    """Observe one domain. Returns a record; never raises for a network reason."""
    domain = registrable(domain)
    record: Dict[str, Any] = {
        "domain": domain,
        "entry_url": entry_url or ("https://" + domain),
        "enriched_at": now_iso(),
        "tool": TOOL,
        "pages_fetched": 0,
        "pages_blocked": 0,
        "home_status": None,
        "robots": "unknown",
        "submission_url": None,
        "form_shape": None,
        "form_fields": None,
        "form_map": None,
        "form_technical": [],
        "form_method": None,
        "form_kind": None,
        "form_captcha": None,
        "form_honeypots": [],
        "contact_email": None,
        "contact_source": None,
        "contact_source_url": None,
        "other_forms": [],
        "email_candidates": [],
        "notes": [],
    }

    robots = Robots(fetch, timeout)
    visited: set = set()
    forms: List[Dict[str, Any]] = []
    email_rows: List[Dict[str, str]] = []
    entry = record["entry_url"]
    base = "https://%s/" % urllib.parse.urlsplit(entry).netloc if urllib.parse.urlsplit(entry).netloc else entry

    def visit(url: str) -> Tuple[int, List[Tuple[int, str]]]:
        """Read one page and fold its evidence in. Every failure is a note, not a raise."""
        if url in visited:
            return 0, []
        visited.add(url)
        allowed, state = robots.allowed(url)
        if record["robots"] == "unknown":
            record["robots"] = state
        if not allowed:
            record["pages_blocked"] += 1
            return 0, []

        cached = cache.get(url) if (cache is not None and not refresh) else None
        if cached is not None:
            status, body = cached
        else:
            pause = max(delay, robots.crawl_delay(url))
            if record["pages_fetched"] and pause:
                sleep(min(pause, 10.0))
            status, body = fetch(url, timeout)
            if cache is not None and status:
                cache.put(url, status, body)
        record["pages_fetched"] += 1

        if status != 200 or not body.strip():
            return status, []

        parser = _FormParser()
        try:
            parser.feed(body)
            parser.close()
        except Exception:
            pass
        for raw_form in parser.forms:
            classified = classify_form(raw_form, url)
            if classified:
                forms.append(classified)

        linker = _LinkParser()
        try:
            linker.feed(body)
            linker.close()
        except Exception:
            pass
        text = html.unescape(" ".join(linker.text))[:400_000]
        for row in extract_emails(text, linker.mailto, domain, linker.cfemail):
            row["page_url"] = url
            email_rows.append(row)
        return status, _candidate_links(body, url, domain, DEFAULTS["max_links"])

    def has_submission() -> bool:
        return any(form["kind"] == "submission" for form in forms)

    home_status, links = visit(entry)
    record["home_status"] = home_status
    if home_status == 0:
        record["notes"].append("entry page unreadable (DNS, TLS or timeout): unknown, not absent")
        return record
    if home_status >= 400:
        record["notes"].append("entry page returned %d" % home_status)
        return record

    for _, url in links:
        if record["pages_fetched"] >= max_pages or has_submission():
            break
        visit(url)

    # Link-driven crawling only reaches pages the site chose to link. Submission
    # pages are often reachable but unlinked, so a bounded probe of the usual
    # paths comes after it - never before, never beyond the extra budget.
    if not has_submission() or not email_rows:
        probed = 0
        for path in DEFAULTS["probe_paths"]:
            if probed >= DEFAULTS["probe_budget"]:
                break
            if has_submission() and email_rows:
                break
            probed += 1
            visit(urllib.parse.urljoin(base, path.lstrip("/")))

    best = pick_form(forms)
    if best:
        record["submission_url"] = best["page_url"]
        record["form_shape"] = best["shape"]
        # `form_fields` are the wire names a submission must carry, hidden tokens
        # included. `form_slots` is what each visible field means, which is what a
        # fill plan needs; the two are different questions.
        record["form_fields"] = best["real_fields"]
        record["form_map"] = best["map"]
        record["form_technical"] = best["technical"]
        record["form_method"] = best["method"]
        record["form_kind"] = best["kind"]
        record["form_captcha"] = best["captcha"]
        record["form_honeypots"] = best["honeypots"]
        record["other_forms"] = [
            {"page_url": form["page_url"], "kind": form["kind"], "shape": form["shape"]}
            for form in forms
            if form is not best
        ][:5]

    deduped: List[Dict[str, str]] = []
    seen = set()
    for row in email_rows:
        if row["address"] in seen:
            continue
        seen.add(row["address"])
        deduped.append(row)
    record["email_candidates"] = deduped[:email_limit]
    if deduped:
        record["contact_email"] = deduped[0]["address"]
        record["contact_source"] = deduped[0]["source"]
        record["contact_source_url"] = deduped[0].get("page_url")

    if not best:
        record["notes"].append(
            "no usable form within %d page(s); a larger --max-pages may find one"
            % record["pages_fetched"]
        )
    elif best["kind"] == "contact":
        record["notes"].append("only a contact form was found, no submission form")
    if not deduped:
        record["notes"].append("no address found on the pages read")
    if record["pages_blocked"]:
        record["notes"].append("%d page(s) skipped by robots.txt" % record["pages_blocked"])
    return record


# ---------------------------------------------------------------------------
# Inputs and outputs
# ---------------------------------------------------------------------------

def load_targets(path: str | Path) -> Tuple[str, List[Tuple[str, str]]]:
    """Accept a prospector store OR a contract-C snapshot; return (center, [(domain, url)])."""
    src = Path(path)
    if not src.is_file():
        raise SystemExit("input not found: %s" % src)
    doc = json.loads(src.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise SystemExit("input root must be an object: %s" % src)

    center = str(doc.get("center_domain") or "").strip().lower()
    targets: List[Tuple[str, str]] = []

    domains = doc.get("domains")
    if isinstance(domains, dict):
        for key, record in domains.items():
            record = record if isinstance(record, dict) else {}
            domain = registrable(str(record.get("domain") or key))
            if domain:
                targets.append((domain, str(record.get("url") or ("https://" + domain))))
    else:
        prospects = doc.get("prospects")
        if not isinstance(prospects, list):
            raise SystemExit("input has neither a domains map nor a prospects array: %s" % src)
        for record in prospects:
            if not isinstance(record, dict):
                continue
            domain = registrable(str(record.get("domain") or ""))
            if domain:
                targets.append((domain, str(record.get("url") or ("https://" + domain))))

    deduped: Dict[str, str] = {}
    for domain, url in targets:
        deduped.setdefault(domain, url)
    return center, sorted(deduped.items())


def load_overlay(path: str | Path) -> Dict[str, Any]:
    src = Path(path)
    if not src.is_file():
        return {"tool": TOOL, "generated_at": now_iso(), "domains": {}}
    try:
        doc = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"tool": TOOL, "generated_at": now_iso(), "domains": {}}
    if not isinstance(doc, dict) or not isinstance(doc.get("domains"), dict):
        return {"tool": TOOL, "generated_at": now_iso(), "domains": {}}
    return doc


def write_overlay(path: str | Path, center: str, overlay: Dict[str, Any]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "center_domain": center,
        "generated_at": now_iso(),
        "tool": TOOL,
        "domains": dict(sorted(overlay.get("domains", {}).items())),
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Offline self test
# ---------------------------------------------------------------------------

_FIXTURES: Dict[str, Tuple[int, str]] = {
    "https://example-a.com/": (200, """<html><body>
        <form action="/search"><input name="q" type="search"></form>
        <a href="/submit-a-link">Submit a link</a>
        <a href="/blog/some-post">Blog</a>
        <a href="mailto:hello@example-a.com?subject=Hi">Mail us</a>
        </body></html>"""),
    "https://example-a.com/submit-a-link": (200, """<html><body>
        <form action="/submit-a-link" method="post">
          <input name="your_name"><input name="Your Email" type="email">
          <input name="Website_URL" type="url"><textarea name="description"></textarea>
        </form></body></html>"""),
    "https://example-b.com/": (200, """<html><body>
        <form action="/login"><input name="username"><input name="password" type="password"></form>
        <form action="/newsletter"><input name="email" type="email"></form>
        <p>Write to the editor directly: admin@example-b.com.</p>
        </body></html>"""),
    "https://example-c.com/": (200, "<html><body><h1>Nothing here</h1></body></html>"),
    "https://example-d.com/": (403, ""),
    # WPForms: numbered field names, meaning only in the labels, plus a honeypot.
    "https://example-e.com/": (200, """<html><body>
        <form action="/wp-admin/admin-ajax.php" method="post">
          <label for="f0">Your Name</label><input id="f0" name="wpforms[fields][0]">
          <label for="f1">Email Address</label><input id="f1" name="wpforms[fields][1]" type="email">
          <label for="f2">Website URL</label><input id="f2" name="wpforms[fields][2]" type="url">
          <label for="f3">Tell us about your site</label>
          <textarea id="f3" name="wpforms[fields][3]"></textarea>
          <input name="wpforms[hp]" type="text">
          <input type="hidden" name="csrf_token" value="abc">
          <input type="hidden" name="wpforms[id]" value="9">
        </form></body></html>"""),
    # The classic false positive: a signup box with an address and a URL, but
    # nowhere to say what is being submitted.
    "https://example-f.com/": (200, """<html><body>
        <form action="/subscribe"><input name="email" type="email">
        <input name="website" type="url"></form></body></html>"""),
    # Cloudflare hides addresses as data-cfemail="<key><xor>", which decodes to
    # hi@example-g.com.
    "https://example-g.com/": (200, """<html><body>
        <a href="/cdn-cgi/l/email-protection" data-cfemail="5b33321b3e233a362b373e763c75383436"
           class="__cf_email__">[email protected]</a></body></html>"""),
}


def _fixture_fetch(url: str, timeout: int = 15) -> Tuple[int, str]:
    parts = urllib.parse.urlsplit(url)
    key = "https://%s%s" % (parts.netloc, parts.path or "/")
    if parts.query:
        key += "?" + parts.query
    return _FIXTURES.get(key, (404, ""))


def selftest() -> int:
    failures: List[str] = []

    def check(name: str, condition: bool, detail: Any = "") -> None:
        print("  [%s] %s%s" % ("PASS" if condition else "FAIL", name,
                               (" -> %s" % (detail,) if not condition and detail else "")))
        if not condition:
            failures.append(name)

    print("discover_entry selftest (offline)")

    a = discover_domain("example-a.com", "https://example-a.com", _fixture_fetch,
                        max_pages=4, delay=0, sleep=lambda _: None)
    check("form page is found through a link", a["submission_url"] == "https://example-a.com/submit-a-link",
          a["submission_url"])
    check("search form is rejected", a["other_forms"] == [] or all(
        "/search" not in form["page_url"] for form in a["other_forms"]))
    check("field synonyms normalise to slots",
          sorted(a["form_fields"]) == ["Website_URL", "Your Email", "description", "your_name"],
          a["form_fields"])
    check("shape is a sha256", str(a["form_shape"]).startswith("sha256:"), a["form_shape"])
    check("mailto address wins", a["contact_email"] == "hello@example-a.com", a["contact_email"])
    check("mailto provenance", a["contact_source"] == "mailto", a["contact_source"])

    b = discover_domain("example-b.com", "https://example-b.com", _fixture_fetch,
                        max_pages=2, delay=0, sleep=lambda _: None)
    check("login form is not a submission form", b["submission_url"] is None, b["submission_url"])
    check("newsletter is not a submission form", b["form_shape"] is None, b["form_shape"])
    check("prose address is found", b["contact_email"] == "admin@example-b.com", b["contact_email"])
    check("prose provenance", b["contact_source"] == "prose", b["contact_source"])

    c = discover_domain("example-c.com", "https://example-c.com", _fixture_fetch,
                        max_pages=2, delay=0, sleep=lambda _: None)
    check("a bare page yields no channel", c["submission_url"] is None and c["contact_email"] is None)
    check("a miss is explained, not silent", any("may find one" in note for note in c["notes"]),
          c["notes"])

    d = discover_domain("example-d.com", "https://example-d.com", _fixture_fetch,
                        max_pages=2, delay=0, sleep=lambda _: None)
    check("a 403 home is recorded as such", d["home_status"] == 403, d["home_status"])

    same = shape_of("post", [normalise_field(n) for n in ("your_name", "Your Email", "Website_URL")])
    other = shape_of("post", [normalise_field(n) for n in ("name", "email", "url")])
    check("two sites sharing a plugin share a shape", same == other, (same, other))

    e = discover_domain("example-e.com", "https://example-e.com", _fixture_fetch,
                        max_pages=2, delay=0, sleep=lambda _: None)
    check("numbered plugin fields take their slot from the label",
          e["submission_url"] == "https://example-e.com", e["submission_url"])
    check("honeypot is not treated as a field",
          e["form_honeypots"] == ["wpforms[hp]"], e["form_honeypots"])
    check("hidden tokens are recorded but kept out of the shape",
          sorted(e["form_technical"]) == ["csrf_token", "wpforms[id]"], e["form_technical"])
    semantic = shape_of("post", ["name", "email", "url", "message"])
    check("a WPForms form shares the shape of its semantic equivalent",
          e["form_shape"] == semantic, (e["form_shape"], semantic))

    f = discover_domain("example-f.com", "https://example-f.com", _fixture_fetch,
                        max_pages=2, delay=0, sleep=lambda _: None)
    check("email + website with no message is a signup, not a submission form",
          f["submission_url"] is None, f["submission_url"])

    g = discover_domain("example-g.com", "https://example-g.com", _fixture_fetch,
                        max_pages=2, delay=0, sleep=lambda _: None)
    check("cloudflare-obfuscated address is decoded",
          g["contact_email"] == "hi@example-g.com", g["contact_email"])
    check("obfuscated provenance is recorded", g["contact_source"] == "obfuscated",
          g["contact_source"])

    print("")
    if failures:
        print("%d check(s) failed" % len(failures))
        return 1
    print("all checks passed")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only discovery of submission forms and contact addresses.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--store", default="", help="prospector store-<domain>.json or a contract-C snapshot")
    parser.add_argument("--out", default="", help="overlay file to write (default: data/enrichment-<center>.json)")
    parser.add_argument("--limit", type=int, default=0, help="visit at most N domains")
    parser.add_argument("--only", default="", help="comma-separated domains to visit")
    parser.add_argument("--max-pages", type=int, default=DEFAULTS["max_pages"])
    parser.add_argument("--delay", type=float, default=DEFAULTS["delay"])
    parser.add_argument("--timeout", type=int, default=DEFAULTS["timeout"])
    parser.add_argument("--cache-dir", default=DEFAULTS["cache_dir"])
    parser.add_argument("--cache-days", type=int, default=DEFAULTS["cache_days"])
    parser.add_argument("--refresh", action="store_true", help="ignore cached pages")
    parser.add_argument("--resume", action="store_true", help="keep domains already in --out")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, fetch nothing")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--selftest", action="store_true", help="run the offline checks and exit")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.store:
        print("--store is required (or pass --selftest)", file=sys.stderr)
        return 2

    center, targets = load_targets(args.store)
    if not center:
        center = "unknown-center"
    if args.only:
        wanted = {registrable(part) for part in args.only.split(",") if part.strip()}
        targets = [(domain, url) for domain, url in targets if domain in wanted]
    if args.limit > 0:
        targets = targets[: args.limit]

    out_path = args.out or ("data/enrichment-%s.json" % center)
    overlay = load_overlay(out_path) if args.resume else {"domains": {}}
    known = overlay.get("domains", {}) if args.resume else {}

    if args.dry_run:
        for domain, url in targets:
            marker = " (cached)" if domain in known else ""
            print("%-32s %s%s" % (domain, url, marker))
        print("\n%d domain(s); nothing fetched (--dry-run)" % len(targets))
        return 0

    cache = Cache(args.cache_dir, args.cache_days)
    results: Dict[str, Any] = dict(known)
    started = time.time()

    for index, (domain, url) in enumerate(targets, 1):
        if args.resume and domain in results:
            if not args.quiet:
                print("[%d/%d] %-30s skipped (already discovered)" % (index, len(targets), domain))
            continue
        record = discover_domain(
            domain, url, default_fetch, cache=cache,
            max_pages=args.max_pages, delay=args.delay, timeout=args.timeout,
            refresh=args.refresh,
        )
        results[domain] = record
        if not args.quiet:
            channel = record["submission_url"] or record["contact_email"] or "-"
            print("[%d/%d] %-30s %-6s pages=%d %s"
                  % (index, len(targets), domain, record["home_status"], record["pages_fetched"], channel))

    written = write_overlay(out_path, center, {"domains": results})
    forms = sum(1 for r in results.values() if r.get("submission_url"))
    emails = sum(1 for r in results.values() if r.get("contact_email"))
    both = sum(1 for r in results.values() if r.get("submission_url") and r.get("contact_email"))
    neither = sum(1 for r in results.values() if not r.get("submission_url") and not r.get("contact_email"))
    print(json.dumps({
        "out": str(written),
        "center_domain": center,
        "domains": len(results),
        "form": forms,
        "email": emails,
        "both": both,
        "neither": neither,
        "cache_hits": cache.hits,
        "cache_misses": cache.misses,
        "seconds": round(time.time() - started, 1),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
