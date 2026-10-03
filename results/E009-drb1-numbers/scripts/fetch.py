"""E009 step 2. Run in data/ after sentences.py: snapshot every URL the 100 sampled sentences cite into data/store.
`fetch.py [SAMPLE.json [LOG.json]]` does the same for another sample (NEXT №42: the out-of-sample set).

Direct fetch first (the E004/E010 fetcher); a page that is not readable after it (error, 4xx, gate page, home page,
no text) goes through verbatim's access cascade in order: browser, open_access, archive (Common Crawl; Wayback does
not answer from the cloud container). Same environment as E010:
VERBATIM_CHROMIUM=/opt/pw-browsers/chromium VERBATIM_BROWSER_CA=/root/.ccr/agent-proxy-ca.crt
"""
import concurrent.futures as cf, json, sys, urllib.error, urllib.request

from verbatim.access import METHODS
from verbatim.check import readable
from verbatim.store import Store, canonical_url, now, request_url

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
st = Store("store")
urls = sorted({canonical_url(u) for x in json.load(open(sys.argv[1] if len(sys.argv) > 1 else "sample.json"))["items"] for u in x["urls"]})
todo = [u for u in urls if u not in st.index()]


def get(u):
    req = urllib.request.Request(request_url(u), headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
                                                          "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return u, r.status, r.headers.get("Content-Type"), r.geturl(), r.read(30_000_000), None
    except urllib.error.HTTPError as e:
        return u, e.code, None, u, None, f"HTTP {e.code}"
    except Exception as e:
        return u, None, None, u, None, str(e)[:200]


with cf.ThreadPoolExecutor(16) as ex:
    for u, code, ct, final, body, err in ex.map(get, todo):
        if body is not None:
            st.add(u, body, content_type=ct, http_status=code, final_url=final)
        else:
            st.record(u, {"sha256": None, "fetched_at": now(), "http_status": code, "content_type": None,
                          "final_url": u, "error": err})


def ok(u):
    return any(not isinstance(readable(st, e, u), dict) for e in st.index().get(u, []))


log = {}
for u in urls:
    tried = []
    for method in ("browser", "open_access", "archive"):
        if ok(u):
            break
        if any(e.get("via") == method for e in st.index().get(u, [])):
            continue
        try:
            METHODS[method](st, u)
        except Exception as e:  # one broken method must not stop the run
            st.record(u, {"sha256": None, "fetched_at": now(), "error": f"{method}: {e}"[:200], "via": method})
        tried.append(method)
    log[u] = {"readable": ok(u), "tried": tried}
    print(("ok  " if log[u]["readable"] else "MISS"), tried, u[:100], flush=True)
json.dump(log, open(sys.argv[2] if len(sys.argv) > 2 else "fetch_log.json", "w"), indent=1)
print("urls", len(urls), "readable", sum(v["readable"] for v in log.values()))
