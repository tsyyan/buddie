"""E009 step 1. Run in data/ with the four DRB I jsonl files of E004 (sha256 checked against E004's DATASET.json).

Pool: every sentence of the 200 English-task reports that has a number `verbatim.numbers.mentions` would check and a
citation that resolves to a URL: a markdown link or bare URL in the sentence, a footnote `[^n]`/`[n]` with a
definition, or Gemini's footnote digits glued after a word (`outlook.5`) looked up in its numbered source list.
OpenAI's `【n†】` markers carry no URL in this dataset and are counted, not sampled.
Sample: PER_SYSTEM random sentences per system (SEED). Writes pool.json and sample.json.
"""
import hashlib, json, random, re
from pathlib import Path

from verbatim.numbers import mentions
from verbatim.report import URL as BARE

LAB = Path(__file__).resolve().parents[3]
DS = json.loads((LAB / "experiments/E004-deep-research-quotes/raw/DATASET.json").read_text())["files"]
SEED, PER_SYSTEM = 2029, 25
SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z*\"“(])|\n+")
INLINE = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+(?:\([^)\s]*\)[^)\s]*)*)\)")
NOTE = re.compile(r"\[\^?(\d+(?:_\d+)?)\]")
DEFN = re.compile(r"^\s{0,3}\[\^?(\d+(?:_\d+)?)\]:\s*(.+)$", re.M)
LIST = re.compile(r"^\s*(\d{1,3})\.\s+(.+)$", re.M)
GLUED = re.compile(r"(?<=[a-z\)\"”%])[.,]?(\d{1,3}(?:,\d{1,3})*)(?=[.,]?\s|$)")
GEMINI_END = re.compile(r"([a-z\)\"”%][.!?]\d{1,3}(?:,\d{1,3})*)[ \t]+(?=[A-Z*])")
OAI = re.compile(r"【\d+[†:][^】]*】")


def first_url(text):
    m = INLINE.search(text)
    if m:
        return m.group(2)
    m = BARE.search(text.replace("\\_", "_"))
    return m.group(0) if m else None


def sources(article):
    """footnote number -> URL from `[^n]: url` definitions and from a numbered source list after the last heading."""
    defs = {n: first_url(t) for n, t in DEFN.findall(article)}
    tail = article[article.rfind("\n#"):] if "\n#" in article else article[-len(article) // 3:]
    for n, t in LIST.findall(tail):
        if n not in defs and first_url(t):
            defs[n] = first_url(t)
    return {n: u.replace("\\_", "_") for n, u in defs.items() if u}


def cites(sentence, defs, gemini):
    found = [(m.start(), m.group(2)) for m in INLINE.finditer(sentence)]
    spans = [(m.start(), m.end()) for m in INLINE.finditer(sentence)]
    for m in BARE.finditer(sentence):
        if not any(a <= m.start() < b for a, b in spans):
            found.append((m.start(), m.group(0)))
    for m in NOTE.finditer(sentence):
        if m.group(1) in defs:
            found.append((m.start(), defs[m.group(1)]))
    if gemini:
        for m in GLUED.finditer(sentence):
            for n in m.group(1).split(","):
                if n in defs:
                    found.append((m.start(), defs[n]))
    urls = []
    for _, u in sorted(found):
        u = u.replace("\\_", "_")
        if u not in urls:
            urls.append(u)
    return urls


pool, stats = [], {}
for m, meta in DS.items():
    p = Path(m + ".jsonl")
    assert hashlib.sha256(p.read_bytes()).hexdigest() == meta["sha256"], m
    st = stats.setdefault(m, {"reports": 0, "numeric_sentences": 0, "with_url": 0, "oai_marker_only": 0, "numbers": 0})
    for line in p.open():
        r = json.loads(line)
        if re.search(r"[一-鿿]", r["prompt"]):
            continue
        st["reports"] += 1
        a = r["article"]
        defs = sources(a)
        if m.startswith("gemini"):  # "infarction.66 Participants": a footnote glued after the full stop ends the sentence
            a = GEMINI_END.sub(r"\1\n", a)
        for i, s in enumerate(SENT.split(a)):
            if s.lstrip().startswith(("[^", "[")) and DEFN.match(s) or "访问时间" in s or "檢索日期" in s or "accessed" in s.lower():
                continue
            if re.match(r"^\s*\d{1,3}\.\s", s) and first_url(s) and len(s) < 600 and ("http" in s[:400]):
                continue  # an entry of the source list
            ms = mentions(s)
            if not ms:
                continue
            urls = cites(s, defs, m.startswith("gemini"))
            if not urls and not OAI.search(s):
                continue
            st["numeric_sentences"] += 1
            if not urls:
                st["oai_marker_only"] += 1
                continue
            st["with_url"] += 1
            st["numbers"] += len(ms)
            pool.append({"system": m, "task": r["id"], "n": i, "sentence": s.strip(), "urls": urls,
                         "numbers": [x.as_dict() for x in ms]})
random.seed(SEED)
sample = []
for m in DS:
    sample += random.sample([x for x in pool if x["system"] == m], PER_SYSTEM)
random.shuffle(sample)
for k, x in enumerate(sample, 1):
    x["key"] = f"S{k:03d}"
Path("pool.json").write_text(json.dumps({"stats": stats, "pool": pool}, ensure_ascii=False) + "\n")
Path("sample.json").write_text(json.dumps({"seed": SEED, "per_system": PER_SYSTEM, "stats": stats, "items": sample},
                                          ensure_ascii=False, indent=1) + "\n")
print(json.dumps(stats, indent=1), "sample numbers", sum(len(x["numbers"]) for x in sample))
