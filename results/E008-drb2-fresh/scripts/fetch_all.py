"""E008 step 1. Run in data/: snapshot every URL cited next to a quote into data/store (same fetcher as E004)."""
import concurrent.futures as cf, sys, urllib.error, urllib.request
sys.path.insert(0, __import__("os").path.dirname(__file__))
from reports import reports
from verbatim.report import from_markdown
from verbatim.store import Store, canonical_url, now

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
st = Store("store")
urls = sorted({canonical_url(u) for _, _, text in reports() for c in from_markdown(text)[0] for u in c["urls"]})
done = set(st.index())
todo = [u for u in urls if u not in done]


def get(u):
    req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
                                             "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return u, r.status, r.headers.get("Content-Type"), r.geturl(), r.read(30_000_000), None
    except urllib.error.HTTPError as e:
        return u, e.code, None, u, None, f"HTTP {e.code}"
    except Exception as e:
        return u, None, None, u, None, str(e)[:200]


with cf.ThreadPoolExecutor(24) as ex:
    for i, (u, code, ct, final, body, err) in enumerate(ex.map(get, todo), 1):
        if body is not None:
            st.add(u, body, content_type=ct, http_status=code, final_url=final)
        else:
            st.record(u, {"sha256": None, "fetched_at": now(), "http_status": code, "content_type": None,
                          "final_url": u, "error": err})
        if i % 100 == 0:
            print(i, flush=True)
print("urls", len(urls), "fetched now", len(todo))
