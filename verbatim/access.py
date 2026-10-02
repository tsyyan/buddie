"""Access cascade: where else the text of a cited page may come from when a plain GET cannot read it (E007).

Methods, tried in the order given (default: DEFAULT) when the cited page cannot be read, or when the quote is not
on it (a second look: check.py keeps the first read's miss unless an alternative finds the quote):

  browser      headless Chromium (optional `playwright`): runs the page's JavaScript, keeps the rendered DOM
  archive      Wayback Machine (raw `id_` bytes), then Common Crawl (WARC record by offset): its CDX index server
               when reachable (one request per crawl), else a bisect of cluster.idx (about 30 requests per crawl).
               An unreachable Wayback or index server is noted once per process and not asked again.
  open_access  for a DOI link: an open copy listed by OpenAlex / Unpaywall, else the OpenAlex abstract
  copy         the same article republished elsewhere (syndication); the copy URLs come from the caller
  relay        r.jina.ai renders the page on a third-party server; opt-in only, never part of DEFAULT

Every result is stored under the cited URL with `via` (method and where the bytes came from) and `provenance`:
publisher (direct, browser), archive, open_access, copy, relay. A quote found in a copy or a relay is not FOUND
(check.py: FOUND_IN_COPY), because those bytes are not the page the report cites.

Nothing here defeats a paywall, a CAPTCHA or a bot filter: a page that refuses all of these stays unreadable.
"""
from __future__ import annotations

import functools
import gzip
import http.client
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from verbatim.store import Store, canonical_url, now, request_url

DEFAULT = ("browser", "archive", "open_access", "copy")
ALL = DEFAULT + ("relay",)
PROVENANCE = {"direct": "publisher", "browser": "publisher", "archive": "archive", "open_access": "open_access",
              "copy": "copy", "relay": "relay"}
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
CC_DATA = "https://data.commoncrawl.org/"
CC_INDEX = "https://index.commoncrawl.org/"
_down: set[str] = set()  # "wayback", "cc_index": hosts given up on in this process
_fails: dict[str, int] = {}
DOWN_AFTER = 3  # consecutive network failures; one reset under load (Wayback in Actions) must not stop the run


def _failed(host: str) -> None:
    _fails[host] = _fails.get(host, 0) + 1
    if _fails[host] >= DOWN_AFTER:
        _down.add(host)


def _ok(host: str) -> None:
    _fails[host] = 0
CC_CRAWLS = int(os.environ.get("VERBATIM_CC_CRAWLS", "24"))  # newest crawls to search, about two years
DOI = re.compile(r"(?:doi\.org/|/doi/(?:abs/|full/|pdf/|epdf/)?)(10\.\d{4,9}/[^\s?#]+)", re.I)


def _get(url: str, headers: dict | None = None, timeout: float = 60) -> tuple[int, dict, bytes, str]:
    req = urllib.request.Request(request_url(url), headers={"User-Agent": BROWSER_UA, "Accept": "*/*", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, b"", url


def _store(store: Store, url: str, method: str, status: int, ctype: str | None, body: bytes, final: str,
           source: str, **meta) -> dict:
    extra = {"via": f"{method} {source}".strip(), "provenance": PROVENANCE[method], **meta}
    if not body or status >= 400:
        return store.record(url, {"sha256": None, "fetched_at": now(), "http_status": status, "content_type": ctype,
                                  "final_url": final, "error": f"{method}: HTTP {status}" if status else f"{method}: no body",
                                  **extra})
    return store.add(url, body, content_type=ctype, http_status=status, final_url=final, **extra)


# ---- browser ------------------------------------------------------------------------------------------------

_browser = None


def _trust_extra_ca() -> None:
    """Chromium on Linux trusts NSS, not SSL_CERT_FILE. VERBATIM_BROWSER_CA (a PEM file, e.g. a proxy's CA)
    is added to the user's NSS database if certutil is installed; nothing is ever marked insecure."""
    ca = os.environ.get("VERBATIM_BROWSER_CA")
    if not ca or not Path(ca).exists() or not shutil.which("certutil"):
        return
    db = Path.home() / ".pki" / "nssdb"
    db.mkdir(parents=True, exist_ok=True)
    if not (db / "cert9.db").exists():
        subprocess.run(["certutil", "-d", f"sql:{db}", "-N", "--empty-password"], check=False, capture_output=True)
    subprocess.run(["certutil", "-d", f"sql:{db}", "-A", "-t", "C,,", "-n", "verbatim-extra-ca", "-i", ca],
                   check=False, capture_output=True)


def browser(store: Store, url: str, **_) -> dict:
    global _browser
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return store.record(url, {"sha256": None, "fetched_at": now(), "http_status": None, "content_type": None,
                                  "final_url": url, "error": "browser: playwright is not installed",
                                  "via": "browser", "provenance": "publisher"})
    if _browser is None:
        _trust_extra_ca()
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        exe = os.environ.get("VERBATIM_CHROMIUM")
        _browser = sync_playwright().start().chromium.launch(
            headless=True, executable_path=exe or None, proxy={"server": proxy} if proxy else None)
    ctx = _browser.new_context(user_agent=BROWSER_UA, locale="en-US")
    try:
        page = ctx.new_page()
        resp = page.goto(request_url(url), wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass  # pages that keep polling never go idle; the DOM after 15 s is what a reader sees
        status = resp.status if resp else 200
        if status == 202:  # AWS WAF / SiteGround answer a bot with 202 and a CAPTCHA page (E007: IMDb)
            status = 429
        return _store(store, url, "browser", status, "text/html; charset=utf-8",
                      page.content().encode("utf-8"), page.url, "chromium")
    except Exception as e:
        return store.record(url, {"sha256": None, "fetched_at": now(), "http_status": None, "content_type": None,
                                  "final_url": url, "error": f"browser: {str(e).splitlines()[0][:160]}",
                                  "via": "browser", "provenance": "publisher"})
    finally:
        ctx.close()


# ---- archive ------------------------------------------------------------------------------------------------

def surt(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    host = (p.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    return ",".join(reversed(host.split("."))) + ")" + ((p.path or "/") + (f"?{p.query}" if p.query else "")).lower()


def _cc(path: str, rng: tuple[int, int] | None = None, method: str = "GET") -> tuple[dict, bytes]:
    """Headers and body. data.commoncrawl.org answers 503 'Slow Down' (sometimes 403) and cuts long reads under
    load: back off and retry."""
    headers = {"User-Agent": "verbatim (quote checker)"}
    if rng:
        headers["Range"] = f"bytes={rng[0]}-{rng[1]}"
    for wait in (2, 4, 8, 16, 32):
        try:
            req = urllib.request.Request(CC_DATA + path, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=60) as r:
                return dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            if e.code not in (403, 429, 503):
                raise
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError):
            pass
        time.sleep(wait)
    raise OSError(f"data.commoncrawl.org kept refusing {path}")


def _cc_bytes(path: str, a: int, b: int) -> bytes:
    return _cc(path, (a, b))[1]


@functools.cache
def _crawls() -> list[str]:
    page = _cc("crawl-data/index.html")[1].decode("utf-8", "replace")
    return sorted(set(re.findall(r"CC-MAIN-20\d\d-\d\d", page)), reverse=True)[:CC_CRAWLS]


def cc_lookup(url: str, crawl: str) -> list[dict]:
    """Captures of url in one crawl: bisect the sorted cluster.idx by Range requests, then read one CDX block."""
    idx = f"cc-index/collections/{crawl}/indexes/cluster.idx"
    size = int({k.lower(): v for k, v in _cc(idx, method="HEAD")[0].items()}["content-length"])
    key = surt(url)

    def line_at(off: int) -> str:
        chunk = _cc_bytes(idx, off, min(size - 1, off + 8191)).decode("utf-8", "replace")
        return (chunk.split("\n", 1)[1] if off and "\n" in chunk else chunk).split("\n", 1)[0]

    lo, hi = 0, size
    while hi - lo > 16384:
        mid = (lo + hi) // 2
        lo, hi = (mid, hi) if line_at(mid).split(" ")[0] <= key else (lo, mid)
    lines = [l for l in _cc_bytes(idx, lo, min(size - 1, hi + 16384)).decode("utf-8", "replace").split("\n")[1 if lo else 0:]
             if "\t" in l]
    if not lines:
        return []
    i = max([n for n, l in enumerate(lines) if l.split(" ")[0] <= key] or [0])
    hits = []
    for l in lines[i:i + 2]:  # a URL's rows can spill into the next block
        _, f, off, ln, _ = l.split("\t")
        raw = gzip.decompress(_cc_bytes(f"cc-index/collections/{crawl}/indexes/{f}", int(off), int(off) + int(ln) - 1))
        for row in raw.decode("utf-8", "replace").splitlines():
            k, ts, js = row.split(" ", 2)
            if k == key:
                hits.append({"timestamp": ts, **json.loads(js)})
    return hits


def cc_lookup_index(url: str, crawl: str) -> list[dict] | None:
    """Captures of url in one crawl from the CDX index server; None when the server cannot answer (then bisect)."""
    if "cc_index" in _down:
        return None
    q = urllib.parse.urlencode({"url": url, "output": "json"})
    try:
        st, _, body, _ = _get(f"{CC_INDEX}{crawl}-index?{q}", timeout=60)
    except (OSError, http.client.HTTPException):
        _failed("cc_index")
        return None
    _ok("cc_index")
    if st == 404:  # the server's answer for "no captures"
        return []
    if st != 200:
        return None
    return [json.loads(l) for l in body.decode("utf-8", "replace").splitlines() if l.strip()]


def cc_record(hit: dict) -> tuple[int, str | None, bytes]:
    off, ln = int(hit["offset"]), int(hit["length"])
    warc = gzip.decompress(_cc_bytes(hit["filename"], off, off + ln - 1))
    head, body = warc.split(b"\r\n\r\n", 1)[1].split(b"\r\n\r\n", 1)
    lines = head.decode("latin-1").split("\r\n")
    hdr = {h.split(":", 1)[0].lower(): h.split(":", 1)[1].strip() for h in lines[1:] if ":" in h}
    if "gzip" in hdr.get("content-encoding", ""):
        body = gzip.decompress(body)
    return int(lines[0].split(" ")[1]), hdr.get("content-type"), body


def archive(store: Store, url: str, **_) -> dict:
    errors = []
    try:  # Wayback first: one call tells whether it is reachable (it is not from some cloud sandboxes)
        if "wayback" in _down:
            raise OSError("unreachable earlier in this run")
        st, _, body, _ = _get("https://archive.org/wayback/available?" + urllib.parse.urlencode({"url": url}), timeout=30)
        _ok("wayback")
        snap = json.loads(body or b"{}").get("archived_snapshots", {}).get("closest") if st == 200 else None
        if snap and snap.get("status", "200") == "200":
            ts = snap["timestamp"]
            st, h, body, final = _get(f"https://web.archive.org/web/{ts}id_/{url}")
            if st == 200 and body:
                return _store(store, url, "archive", st, h.get("content-type"), body, final, f"web.archive.org {ts}",
                              archived_at=ts)
        errors.append(f"wayback HTTP {st}" if st != 200 else "wayback: no capture")
    except (OSError, ValueError) as e:
        if isinstance(e, OSError) and not isinstance(e, urllib.error.HTTPError):
            _failed("wayback")
        errors.append(f"wayback: {str(e)[:80]}")
    try:
        for crawl in _crawls():
            found = cc_lookup_index(url, crawl)
            hits = [h for h in (cc_lookup(url, crawl) if found is None else found) if h.get("status") == "200"]
            if hits:
                h = hits[-1]
                st, ctype, body = cc_record(h)
                return _store(store, url, "archive", st, ctype, body, h["url"],
                              f"{crawl} {h['filename']}@{h['offset']}", archived_at=h["timestamp"])
        errors.append(f"commoncrawl: no capture in {CC_CRAWLS} crawls")
    except (OSError, ValueError, KeyError, http.client.HTTPException) as e:
        errors.append(f"commoncrawl: {str(e)[:80]}")
    return store.record(url, {"sha256": None, "fetched_at": now(), "http_status": None, "content_type": None,
                              "final_url": url, "error": "archive: " + "; ".join(errors), "via": "archive",
                              "provenance": "archive"})


# ---- open access --------------------------------------------------------------------------------------------

def open_access(store: Store, url: str, **_) -> dict | None:
    m = DOI.search(urllib.parse.unquote(url))
    if not m:
        return None  # not a DOI link: nothing to try, nothing to record
    doi = m.group(1).rstrip(".")
    links = []
    st, _, body, _ = _get(f"https://api.openalex.org/works/doi:{doi}", timeout=30)
    work = json.loads(body) if st == 200 else {}
    links += [l.get(k) for l in work.get("locations") or [] if l.get("is_oa") for k in ("pdf_url", "landing_page_url")]
    email = os.environ.get("VERBATIM_EMAIL", "verbatim@example.org")  # Unpaywall asks for a contact address
    st, _, body, _ = _get(f"https://api.unpaywall.org/v2/{doi}?email={urllib.parse.quote(email)}", timeout=30)
    if st == 200:
        links += [l.get(k) for l in json.loads(body).get("oa_locations") or [] for k in ("url_for_pdf", "url")]
    for link in dict.fromkeys(l for l in links if l and "doi.org/" not in l):  # doi.org leads back to the publisher
        st, h, body, final = _get(link)
        if st == 200 and body:
            return _store(store, url, "open_access", st, h.get("content-type"), body, final, link, doi=doi)
    inv = work.get("abstract_inverted_index")
    if inv:
        text = " ".join(w for _, w in sorted((p, w) for w, ps in inv.items() for p in ps))
        return _store(store, url, "open_access", 200, "text/plain; charset=utf-8", text.encode("utf-8"), work["id"],
                      "openalex abstract", doi=doi, abstract_only=True)
    return store.record(url, {"sha256": None, "fetched_at": now(), "http_status": None, "content_type": None,
                              "final_url": url, "error": "open_access: no open copy or abstract", "via": "open_access",
                              "provenance": "open_access", "doi": doi})


# ---- copies and relay ---------------------------------------------------------------------------------------

def copy(store: Store, url: str, copies: dict | None = None, **_) -> dict | None:
    """Try each known republication of url: plain GET, then the browser."""
    last = None
    known = {canonical_url(k): v for k, v in (copies or {}).items()}
    for alt in known.get(canonical_url(url), []):
        st, h, body, final = _get(alt)
        if st == 200 and len(body) > 2000:
            last = _store(store, url, "copy", st, h.get("content-type"), body, final, alt, copy_of=url)
        else:
            got = browser(store, alt)  # rendered copy, also recorded under the copy's own URL
            if got.get("sha256"):
                last = store.add(url, store.read(got["sha256"]), content_type=got.get("content_type"),
                                 http_status=got.get("http_status"), final_url=got.get("final_url"),
                                 via=f"copy {alt} (browser)", provenance="copy", copy_of=url)
        if last and last.get("sha256"):
            return last
    return last


def relay(store: Store, url: str, **_) -> dict:
    st, h, body, final = _get("https://r.jina.ai/" + url, headers={"Accept": "text/plain"}, timeout=90)
    return _store(store, url, "relay", st, "text/plain; charset=utf-8", body, final, "r.jina.ai")


METHODS = {"browser": browser, "archive": archive, "open_access": open_access, "copy": copy, "relay": relay}


def parse(spec: str | None) -> tuple[str, ...]:
    """--access value: 'default', 'all' or a comma list of method names."""
    if not spec:
        return ()
    if spec == "default":
        return DEFAULT
    if spec == "all":
        return ALL
    names = tuple(s.strip() for s in spec.split(",") if s.strip())
    bad = [n for n in names if n not in METHODS]
    if bad:
        raise ValueError(f"unknown access method(s): {', '.join(bad)}; known: {', '.join(METHODS)}")
    return names
