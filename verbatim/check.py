"""Verdict for each quote: is it in the visible text of the snapshot it cites?

FOUND               in the visible text, only whitespace differs
FOUND_NORMALIZED    in the visible text after normalizing case, dashes, spaces around punctuation, dropping
                    double quotation marks (a quote nested in the source),
                    punctuation or "..." at the quote's edges, Unicode compatibility forms (ligatures),
                    or with "..." / "…" standing for omitted words (parts found in order, close together),
                    or with only the punctuation between words different ("important – this" / "important—this",
                    "heroes – like" / "heroes -- like", "Waller – I" / "Waller. I"; "note": "punctuation"; also blanks
                    "___" of any length and the page's own [brackets] around a few letters, "[A]t" / "at"),
                    or as two replies of one speaker joined across the page's speech tag ("…agendas,” said X.
                    “It was…" quoted as "…agendas. It was…"; "note": "speech_tag", "tag" gives the dropped words).
                    Pages whose text layer lost or garbled UTF-8 punctuation ("\\x80\\x9d", "â€™") are repaired
                    first ("repaired": how many characters)
HIDDEN_ONLY         only in markup a reader does not see (JSON-LD, meta, alt text)
FOUND_IN_COPY       found, but only in bytes that are not the cited page: a republished copy of the article or a
                    relay's rendering (access.py, provenance copy / relay); "via" names where
UNCERTAIN           not found, but the miss may not be the report's fault ("doubts" says why):
                    unattributed  - the report does not present the quote as anyone's words (example, term, hypothetical)
                    thin_page     - the snapshot has under THIN_PAGE_CHARS of text (paywall, JS shell, teaser)
                    other_language - the page is not in English and the quote is: likely a translation
                    other_link    - not in the quote's own link, but in another link of its paragraph ("found_in")
                    copy_only     - the cited page was not read, only a copy or relay of it, which may be another edition
                    abstract_only - the cited paper was not read, only its abstract (OpenAlex)
                    unread_link   - another of the quote's own links could not be read, the words may be there
NOT_A_QUOTE         not found, and the report's own text shows it is not somebody's words ("not_quote", report.py):
                    boilerplate (a system's stock line), title (of a standard, paper, song), example (the agent's own
                    illustration, a hypothetical speaker, a question or rule nobody is said to have asked). Found
                    not-quotes keep their FOUND verdict. E008: 46 of 55 false NOT_FOUND were such text
NOT_FOUND           none of the above; "closest" gives the nearest visible passage and its similarity,
                    so a wrong number (ratio ~0.95) reads differently from an invented sentence (ratio ~0.5)
SOURCE_UNAVAILABLE  no snapshot for any cited URL, the fetch failed / returned an HTTP error, its text
                    cannot be extracted here (a PDF without pdftotext, a binary body), the snapshot is a short
                    bot/cookie gate, has almost no text (EMPTY_PAGE_CHARS), or an article URL redirected to the
                    site's home page. Judged on the quote's own links only:
                    a readable neighbour link in the same paragraph does not turn it into NOT_FOUND (E005)
NO_SOURCE           the quote cites no URL at all

Every verdict on a read page carries "via" and "provenance" (publisher, archive, open_access, copy, relay):
publisher is the cited URL itself, read directly or rendered in a browser; the rest come from access.py.

The check is mechanical: it says where the words are, never whether they support the claim around them.
"""
from __future__ import annotations

import bisect
import difflib
import re
import unicodedata
from urllib.parse import urlsplit

from verbatim.store import Store, canonical_url
from verbatim.textlayer import Unreadable, collapse, layers

ORDER = ["FOUND", "FOUND_NORMALIZED", "HIDDEN_ONLY", "FOUND_IN_COPY", "UNCERTAIN", "NOT_A_QUOTE", "NOT_FOUND", "SOURCE_UNAVAILABLE", "NO_SOURCE"]
OK = {"FOUND", "FOUND_NORMALIZED"}

FOLD = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "′": "'", "“": '"', "”": '"', "„": '"', "«": '"', "»": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
})
DROP = {"­", "​", "‌", "‍", "﻿"}
NO_SPACE_BEFORE = set(",.;:!?)]%")
NO_SPACE_AFTER = set("([.!?")  # "similar.Just like" in a rendered DOM is "similar. Just like" (E007, futunn)
ELLIPSIS = re.compile(r"\s*(?:\[\s*(?:\.\.\.|…)\s*\]|\(\s*(?:\.\.\.|…)\s*\)|\.\.\.|…)\s*")
# punctuation and ellipses at the edges of a quote belong to the sentence around it ("…was less creative," she said)
EDGES = re.compile(r"^(?:[\s.,;:!?'\"-]|\.\.\.)+|(?:[\s.,;:!?'\"-]|\.\.\.)+$")
ELISION_SPAN = 3000
# an editorial insertion or substitution in square brackets ("often [led] to", "support [AI's] adoption")
BRACKET = re.compile(r"\s*\[(?!\s*(?:\.\.\.|…)\s*\])[^\[\]]{1,60}\]\s*")
BRACKET_SPAN = 40
BRACKET_KEEP = re.compile(r"\[([^\[\]]{1,60})\]")  # "bore [a son]" where the page has "bore a son" (E008 F204)
# a short page that says this is a bot / cookie / JavaScript gate, not the document (PubMed, PMC, Cloudflare)
WALL = re.compile(r"enable (?:cookies|javascript)|cookies must be enabled|just a moment|checking your browser|"
                  r"verify (?:that )?you are (?:a )?human|are you a robot|access denied|please turn javascript on", re.I)
WALL_MAX_CHARS = 2000
# below this a snapshot is an app shell or a teaser, not an article. Real short news pages run 2-4k characters
# (E001: Android Authority 2.1k, AI Weekly 3.3k), so length alone cannot catch paywalls without hiding misquotes.
THIN_PAGE_CHARS = 1200
# below this there is nothing to check against (IMDb, app shells: 0-70 characters in E005)
EMPTY_PAGE_CHARS = 200
# share of these words among a text's words: >= 0.1 in English prose, < 0.05 on a Spanish, French or Japanese page
EN_WORDS = frozenset("the of and to in is that for it with as was on be by this are from at an or have has not "
                     "which but their they its were been".split())
OTHER_LANGUAGE_BELOW = 0.05


# UTF-8 punctuation read as cp1252 ("â€™") or with its lead byte lost ("\x80\x99", E011 F074): C1 controls
# (U+0080-U+009F) never stand in real text, and "â€" before a cp1252 character is not English or any other language
CP1252 = "€‚ƒ„…†‡ˆ‰Š‹ŒŽ‘’“”•–—˜™š›œžŸ"
MOJIBAKE = re.compile("[\u00c2-\u00f4][\u0080-\u00bf" + CP1252 + "]{1,3}|[\u0080\u0081][\u0080-\u00bf]")


def _byte(ch: str) -> int:
    return ch.encode("cp1252")[0] if ch in CP1252 else ord(ch)


def repair(text: str) -> tuple[str, int]:
    """Text with mojibake sequences decoded back to the characters they stand for, and how many were repaired."""
    count = 0

    def fix(m: re.Match) -> str:
        nonlocal count
        raw = bytes(_byte(c) for c in m.group(0))
        if raw[0] < 0xC0:
            raw = b"\xe2" + raw  # the lead byte of U+2000-U+207F (quotes, dashes) was lost
        try:
            ch = raw.decode("utf-8")
        except UnicodeDecodeError:
            return m.group(0)
        if len(ch) != 1 or ch.isascii():
            return m.group(0)
        count += 1
        return ch

    return MOJIBAKE.sub(fix, text), count


def english_share(text: str) -> float:
    words = re.findall(r"[^\W\d_]+", text.lower())
    return sum(w in EN_WORDS for w in words) / len(words) if words else 0.0  # characters allowed between the parts of an elided quote


def loose(text: str) -> tuple[str, list[int]]:
    """Normalized text and, for each of its characters, the index in the input it came from."""
    chars: list[str] = []
    where: list[int] = []
    for i, ch in enumerate(text):
        if ch in DROP:
            continue
        ch = unicodedata.normalize("NFKC", ch).translate(FOLD).casefold()
        if ch.isspace():
            ch = " "
        for c in ch:
            if c == '"':
                continue  # quotation marks inside a quote vary between the report and the page
            if c == "'" and not (chars and chars[-1].isalnum() and i + 1 < len(text) and text[i + 1].isalnum()):
                continue  # so do single ones ('…' for "…", E006 B25); an apostrophe inside a word (it's) stays
            if c == " " and (not chars or chars[-1] == " " or chars[-1] in NO_SPACE_AFTER):
                continue
            if c in NO_SPACE_BEFORE and chars and chars[-1] == " ":
                chars.pop()
                where.pop()
            chars.append(c)
            where.append(i)
    if chars and chars[-1] == " ":
        chars.pop()
        where.pop()
    return "".join(chars), where


# punctuation between words: the last level of normalization (E008: dashes spaced or not, "--" for "–", "." for "–";
# E011: blanks "___" of different lengths)
PUNCT = re.compile(r"[\s.,;:!?…\-_]+")
# the page's own editorial brackets around a few letters: "[A]t a nonhub airport" for "at a nonhub airport" (E011 F001)
PAGE_BRACKET = re.compile(r"\[([^\W\d_]{1,3})\]")


def words(text: str) -> tuple[str, list[int]]:
    """loose() text with every run of punctuation and spaces between words turned into one space, and the map back."""
    lo, where = loose(text)
    if "[" in lo:
        keep = [True] * len(lo)
        for m in PAGE_BRACKET.finditer(lo):
            keep[m.start()] = keep[m.end() - 1] = False
        where = [w for w, k in zip(where, keep) if k]
        lo = "".join(c for c, k in zip(lo, keep) if k)
    chars: list[str] = []
    out: list[int] = []
    pos = 0
    for m in PUNCT.finditer(lo):
        chars.extend(lo[pos:m.start()])
        out.extend(where[pos:m.start()])
        if chars and m.end() < len(lo):
            chars.append(" ")
            out.append(where[m.start()])
        pos = m.end()
    chars.extend(lo[pos:])
    out.extend(where[pos:])
    return "".join(chars), out


def split_gaps(quote: str, norm=None) -> tuple[list[str], list[int]]:
    """Normalized literal parts of a quote, and the page characters allowed between neighbours:
    "..." / "…" stands for omitted words (up to ELISION_SPAN), "[word]" for an editor's change (up to BRACKET_SPAN)."""
    pieces: list[tuple[str, int]] = []  # (text before the gap, gap after it)
    pos = 0
    marks = sorted([(m.start(), m.end(), ELISION_SPAN) for m in ELLIPSIS.finditer(quote)] +
                   [(m.start(), m.end(), BRACKET_SPAN) for m in BRACKET.finditer(quote)])
    for a, b, span in marks:
        if a < pos:
            continue
        pieces.append((quote[pos:a], span))
        pos = b
    pieces.append((quote[pos:], 0))
    parts: list[str] = []
    gaps: list[int] = []
    for text, span in pieces:
        p = (norm(text)[0] if norm else EDGES.sub("", loose(text)[0])).strip()
        if p:
            parts.append(p)
            gaps.append(span)
        elif gaps:
            gaps[-1] = max(gaps[-1], span)  # two gaps in a row, or a gap at the edge
    return parts, gaps[:-1]


# between two replies of one speaker on the page: the closing quotation mark, a short speech tag without quotation
# marks ("said Eric Newcomer, former chief architect at Credit Suisse."), the opening mark (E011 F064, F074)
SPEECH_TAG = re.compile(r"[\s,.;:!?…\-—–]*[”\"»]\s*([^“”\"«»\n]{3,120}?)\s*[“\"«]")
QUOTE_SPLIT = re.compile(r"[.,;:!?…](?=\s)")
SPLIT_MIN_CHARS = 20  # each of the two replies, normalized


def closest(quote: str, text: str) -> dict:
    n = len(quote)
    if not text or not n:
        return {"ratio": 0.0, "text": ""}
    step = max(1, n // 4)
    sm = difflib.SequenceMatcher(None, autojunk=False)
    sm.set_seq2(quote)
    scored = []
    for i in range(0, max(1, len(text) - n + 1), step):
        sm.set_seq1(text[i:i + n])
        scored.append((sm.quick_ratio(), i))
    scored.sort(reverse=True)
    best = (0.0, 0)
    for _, i in scored[:25]:
        for j in range(max(0, i - step), min(len(text), i + step + 1)):
            sm.set_seq1(text[j:j + n])
            if sm.quick_ratio() > best[0]:
                r = sm.ratio()
                if r > best[0]:
                    best = (r, j)
    r, i = best
    return {"ratio": round(r, 3), "offset": i, "text": text[i:i + n]}


class Page:
    def __init__(self, data: bytes, content_type: str | None, content_encoding: str | None = None) -> None:
        self.data = data
        lay = layers(data, content_type, content_encoding)
        self.visible, self.repaired = repair(lay["visible"])
        self.hidden = lay["hidden"]
        self.visible_loose, self.visible_map = loose(self.visible)
        self.hidden_loose = loose(self.hidden)[0]
        self._words = None
        self.english = english_share(self.visible)

    def context(self, start: int, end: int, pad: int = 80) -> str:
        return self.visible[max(0, start - pad):end + pad]

    def locate(self, quote: str) -> dict:
        q = collapse(quote)
        i = self.visible.find(q)
        if i >= 0:
            res = {"verdict": "FOUND", "visible_offset": i, "context": self.context(i, i + len(q))}
            raw = self.data.find(quote.encode("utf-8"))
            if raw >= 0:
                res["raw_offset"] = raw
            return res
        ql = EDGES.sub("", loose(q)[0])
        i = self.visible_loose.find(ql) if ql else -1
        if i >= 0:
            a, b = self.visible_map[i], self.visible_map[i + len(ql) - 1] + 1
            return {"verdict": "FOUND_NORMALIZED", "visible_offset": a, "matched": self.visible[a:b],
                    "context": self.context(a, b)}
        parts, gaps = split_gaps(q)
        if gaps or (parts and parts[0] != ql):  # also a lone bracket or ellipsis at an edge
            hit = self._gapped(parts, gaps)
            if hit:
                a, b = hit
                note = "+".join(n for n, g in (("elided", ELISION_SPAN), ("bracketed", BRACKET_SPAN)) if g in gaps)
                return {"verdict": "FOUND_NORMALIZED", "note": note, "visible_offset": a,
                        "matched": self.visible[a:b], "context": self.context(a, b)}
        hit = self._by_words(q) or self._stitched(q)
        if hit:
            return hit
        if ql in self.hidden_loose:
            return {"verdict": "HIDDEN_ONLY"}
        near = closest(ql, self.visible_loose)
        if near["text"]:
            a = self.visible_map[near["offset"]]
            b = self.visible_map[min(len(self.visible_map) - 1, near["offset"] + len(near["text"]) - 1)] + 1
            near = {"ratio": near["ratio"], "text": self.visible[a:b], "visible_offset": a}
        return {"verdict": "NOT_FOUND", "closest": near}

    def _by_words(self, q: str) -> dict | None:
        """The quote with punctuation between words ignored, whole, elided, or with an editor's [brackets] removed
        or standing for other words."""
        if self._words is None:
            self._words = words(self.visible)
        text, where = self._words
        tries = [q] + ([BRACKET_KEEP.sub(r" \1 ", q)] if BRACKET.search(q) else [])
        for t in tries:
            parts, gaps = split_gaps(t, words)
            hit = self._gapped(parts, gaps, text, where) if parts and len(" ".join(parts)) >= 8 else None
            if hit:
                a, b = hit
                return {"verdict": "FOUND_NORMALIZED", "note": "punctuation", "visible_offset": a,
                        "matched": self.visible[a:b], "context": self.context(a, b)}
        return None

    def _stitched(self, q: str) -> dict | None:
        """The quote as two replies the page separates with a speech tag: the first ends right before the closing
        quotation mark, the second starts right after the next opening one, and only the tag stands between."""
        if self._words is None:
            self._words = words(self.visible)
        text, where = self._words
        for m in QUOTE_SPLIT.finditer(q):
            first, second = words(q[:m.start()])[0].strip(), words(q[m.end():])[0].strip()
            if len(first) < SPLIT_MIN_CHARS or len(second) < SPLIT_MIN_CHARS:
                continue
            start = text.find(first)
            while start >= 0:
                end = where[start + len(first) - 1] + 1
                tag = SPEECH_TAG.match(self.visible, end)
                if tag:
                    k = bisect.bisect_left(where, tag.end())
                    while k < len(text) and text[k] == " ":
                        k += 1
                    if text.startswith(second, k):
                        a, b = where[start], where[k + len(second) - 1] + 1
                        return {"verdict": "FOUND_NORMALIZED", "note": "speech_tag", "tag": tag.group(1),
                                "visible_offset": a, "matched": self.visible[a:b], "context": self.context(a, b)}
                start = text.find(first, start + 1)
        return None

    def _gapped(self, parts: list[str], gaps: list[int], text: str | None = None,
                where: list[int] | None = None) -> tuple[int, int] | None:
        """parts in order; after part k up to gaps[k] characters of the page may stand between it and the next."""
        if text is None:
            text, where = self.visible_loose, self.visible_map
        start = text.find(parts[0])
        while start >= 0:
            pos, ok = start + len(parts[0]), True
            for p, gap in zip(parts[1:], gaps):
                j = text.find(p, pos, pos + gap + len(p))
                if j < 0:
                    ok = False
                    break
                pos = j + len(p)
            if ok:
                return where[start], where[pos - 1] + 1
            start = text.find(parts[0], start + 1)
        return None


def readable(store: Store, entry: dict | None, url: str = "") -> tuple[dict, Page] | dict:
    """(entry, page) when the snapshot has text to check, else {"error": why not}."""
    if entry is None:
        return {"error": "no snapshot"}
    if not entry.get("sha256") or (entry.get("http_status") or 200) >= 400:
        return {"error": entry.get("error") or f"HTTP {entry.get('http_status')}"}
    try:
        pg = Page(store.read(entry["sha256"]), entry.get("content_type"), entry.get("content_encoding"))
    except Unreadable as error:
        return {"error": str(error)}
    wall = WALL.search(pg.visible) if len(pg.visible) < WALL_MAX_CHARS else None
    if wall:
        return {"error": f"gate page, not the document: {wall.group(0)!r}"}
    if url and _home_page(url, entry.get("final_url")):
        return {"error": f"redirected to the site's home page: {entry.get('final_url')}"}
    if len(pg.visible) < EMPTY_PAGE_CHARS:
        return {"error": f"no text to check: {len(pg.visible)} visible characters"}
    return entry, pg


def check_claims(claims: list[dict], store: Store, *, fetch: bool = False, access: tuple[str, ...] = (),
                 copies: dict[str, list[str]] | None = None, defer: tuple[str, ...] = (),
                 deferred: set[str] | None = None) -> list[dict]:
    """access: access.py methods to try, in order, when the cited page cannot be read or the quote is not on it
    (needs network). copies: {cited URL: [URLs of the same article republished]} for the "copy" method.
    defer: methods not to run here (archive is slow from a sandbox, fast from GitHub Actions); a URL whose cascade
    reached one with no stored result is added to `deferred`, and a later check reuses what was stored for it."""
    pages: dict[str, tuple[dict, Page] | dict] = {}
    others: dict[str, dict] = {}

    def page(url: str):
        if url not in pages:
            entry = store.latest(url)
            if (entry is None or not entry.get("sha256")) and fetch:
                entry = store.fetch(url)
            got = readable(store, entry, url)
            if isinstance(got, dict) and access:
                alt = next(alternatives(url), None)
                got = alt or {"error": "; ".join([f"direct: {got['error']}"] + others[url]["tried"])}
            pages[url] = got
        return pages[url]

    def alternatives(url: str):
        """Readable (entry, page) from the access methods in order, each method run at most once per check and
        only when the caller asks for the next one. An earlier run's stored result for a method is reused."""
        from verbatim import access as acc
        state = others.setdefault(url, {"found": [], "tried": [], "next": 0})
        yield from list(state["found"])
        done = {e["via"].split(" ")[0]: e for e in store.index().get(canonical_url(url), []) if e.get("via")}
        while state["next"] < len(access):
            name = access[state["next"]]
            state["next"] += 1
            if name in defer and name not in done:
                if deferred is not None:
                    deferred.add(url)
                continue
            entry = done.get(name) or acc.METHODS[name](store, url, copies=copies)
            if entry is None:
                continue  # does not apply: open_access on a non-DOI link, copy without known copies
            got = readable(store, entry, url)
            if isinstance(got, dict):
                state["tried"].append(f"{name}: {got['error']}")
            else:
                state["found"].append(got)
                yield got

    results = []
    for claim in claims:
        out = dict(claim)
        if not claim["urls"]:
            out["verdict"] = "NO_SOURCE"
            results.append(out)
            continue

        def judge(url: str, entry: dict, pg: Page) -> dict:
            res = pg.locate(claim["quote"])
            res.update(url=url, sha256=entry["sha256"], fetched_at=entry.get("fetched_at"), page_chars=len(pg.visible),
                       via=entry.get("via", "direct"), provenance=entry.get("provenance", "publisher"))
            if entry.get("archived_at"):
                res["archived_at"] = entry["archived_at"]
            if pg.repaired:
                res["repaired"] = pg.repaired
            if res["provenance"] in ("copy", "relay") and res["verdict"] in OK | {"HIDDEN_ONLY"}:
                res.update(verdict="FOUND_IN_COPY", match=res["verdict"])
            if res["verdict"] == "NOT_FOUND":
                doubts = doubts_about(claim, pg)
                doubts += ["copy_only"] if res["provenance"] in ("copy", "relay") else []
                doubts += ["abstract_only"] if entry.get("abstract_only") else []
                if doubts:
                    res.update(verdict="UNCERTAIN", doubts=doubts)
            return res

        def verdict(url: str) -> dict:
            got = page(url)
            if isinstance(got, dict):
                return {"verdict": "SOURCE_UNAVAILABLE", "url": url, "error": got["error"]}
            res = judge(url, *got)
            if access and res["verdict"] in ("NOT_FOUND", "UNCERTAIN"):
                # second look: a rendered DOM, an older capture or a copy may hold what this read did not (E007)
                for entry, pg in alternatives(url):
                    if entry["sha256"] != res["sha256"]:
                        alt = judge(url, entry, pg)
                        if alt["verdict"] in OK | {"HIDDEN_ONLY", "FOUND_IN_COPY"}:
                            return dict(alt, first_read=res["verdict"])
            return res

        best, unread = None, []
        for url in claim["urls"]:
            res = verdict(url)
            if res["verdict"] == "SOURCE_UNAVAILABLE":
                unread.append(url)
            if best is None or _better(res, best):
                best = res
            if best["verdict"] == "FOUND":
                break
        if best["verdict"] not in OK and best["verdict"] not in ("HIDDEN_ONLY", "FOUND_IN_COPY"):
            for url in claim.get("block_urls") or []:
                if url not in claim["urls"] and verdict(url)["verdict"] in OK:
                    best = dict(best, found_in=url)
                    break
            doubts = list(best.get("doubts", []))
            doubts += ["other_link"] if best.get("found_in") else []
            doubts += ["unread_link"] if unread and best["verdict"] in ("NOT_FOUND", "UNCERTAIN") else []
            if doubts:
                if best["verdict"] == "SOURCE_UNAVAILABLE":
                    best["doubts"] = doubts  # stays unavailable: its own link was not read
                else:
                    best.update(verdict="UNCERTAIN", doubts=doubts)
        out.update(best)
        if out["verdict"] in ("NOT_FOUND", "UNCERTAIN") and claim.get("not_quote"):
            out.update(verdict="NOT_A_QUOTE", miss=best["verdict"])  # "closest" and "doubts" stay for a reader
        results.append(out)
    return results


def _home_page(url: str, final_url: str | None) -> bool:
    """An article URL that ended on the site's front page: the article is gone (E006 B17)."""
    if not final_url:
        return False
    asked, got = urlsplit(url), urlsplit(final_url)
    return asked.path.strip("/") != "" and got.path.strip("/") == "" and not got.query


def doubts_about(claim: dict, page: Page) -> list[str]:
    doubts = []
    if claim.get("attributed") is False:
        doubts.append("unattributed")
    if len(page.visible) < THIN_PAGE_CHARS:
        doubts.append("thin_page")
    if page.english < OTHER_LANGUAGE_BELOW and english_share(claim["quote"]) >= 0.1:
        doubts.append("other_language")
    return doubts


def _better(a: dict, b: dict) -> bool:
    ra, rb = ORDER.index(a["verdict"]), ORDER.index(b["verdict"])
    if ra != rb:
        return ra < rb
    return a.get("closest", {}).get("ratio", 0) > b.get("closest", {}).get("ratio", 0)


def summary(results: list[dict]) -> dict[str, int]:
    counts = {v: 0 for v in ORDER}
    for r in results:
        counts[r["verdict"]] += 1
    return {k: v for k, v in counts.items() if v}
