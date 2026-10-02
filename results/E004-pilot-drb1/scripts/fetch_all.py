"""E004 step 1. Run in data/ (gitignored): snapshot every URL cited next to a quote (urls.txt) into data/store."""
import sys, urllib.request, urllib.error, concurrent.futures as cf
from verbatim.store import Store, USER_AGENT, now
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
st = Store("store")
urls = [u for u in open("urls.txt").read().split("\n") if u]
done = set(st.index())
urls = [u for u in urls if u not in done]
def get(u):
    req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return u, r.status, r.headers.get("Content-Type"), r.geturl(), r.read(30_000_000), None
    except urllib.error.HTTPError as e:
        return u, e.code, None, u, None, f"HTTP {e.code}"
    except Exception as e:
        return u, None, None, u, None, str(e)[:200]
with cf.ThreadPoolExecutor(24) as ex:
    for i, (u, code, ct, final, body, err) in enumerate(ex.map(get, urls), 1):
        if body is not None:
            st.add(u, body, content_type=ct, http_status=code, final_url=final)
        else:
            st.record(u, {"sha256": None, "fetched_at": now(), "http_status": code, "content_type": None, "final_url": u, "error": err})
        if i % 50 == 0: print(i, flush=True)
print("done", len(urls))
