"""Numbers and dates as a second claim type (experimental, E009): is each number of a cited sentence in its source?

A sentence such as "senior households spent ¥115 trillion in 2014[^1]" carries claims a quote check cannot see.
`mentions(sentence)` finds the numbers a reader would check: values with a unit, percent, currency or scale word,
decimals, numbers of four or more digits, years and dates. Bare small integers ("3 key areas") are left out: they are
on almost every page and their presence proves nothing.

`locate(mention, page_text, words)` looks for the same value on the page, in any of its usual spellings
(`3.349 million` = `3,349,000` = `3349 thousand`; `April 28, 2025` = `28 April 2025` = `2025-04-28`), then for a
rounding of a more precise page number at the claim's precision (`29%` for `29.4%`), and reports how many content
words of the sentence stand near the best occurrence. Verdicts:

  FOUND             same value, same written digits, with sentence words nearby
  FOUND_NORMALIZED  same value in another spelling (scale word, commas, unit missing in a table cell)
  FOUND_ROUNDED     a page number that rounds to the claim at its precision (or within 5 % after "about", "nearly")
  NO_CONTEXT        the value is on the page, but no content word of the sentence within WINDOW characters
  NOT_FOUND         the value is not on the page in any of these forms
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS["sept"] = 9
MON = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
SCALES = {"thousand": 1e3, "k": 1e3, "million": 1e6, "mn": 1e6, "mln": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9,
          "b": 1e9, "trillion": 1e12, "tn": 1e12, "t": 1e12, "crore": 1e7, "lakh": 1e5}
SCALE = r"(?:thousand|million|billion|trillion|crore|lakh|mn|mln|bn|tn|k|m|b|t)\b"
CURRENCY = r"(?:US\$|USD|EUR|GBP|JPY|CNY|RMB|A\$|C\$|HK\$|[$€£¥₹₩])"
UNIT = (r"(?:%|percent\b|per cent\b|pct\b|percentage points?\b|bps?\b|basis points?\b|yen\b|dollars?\b|euros?\b|"
        r"yuan\b|rupees?\b|pounds?\b|won\b|km\b|kg\b|tons?\b|tonnes?\b|mt\b|gw\b|mw\b|kw\b|twh\b|gwh\b|mwh\b|kwh\b|"
        r"ppm\b|°c|°f|°|µm\b|μm\b|nm\b|mm\b|cm\b|x\b|×|-?fold\b|times\b|"
        r"years?\b|people\b|users?\b|households?\b|units?\b|vehicles?\b|jobs?\b|patients?\b)")
NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
APPROX = re.compile(r"(?:~|≈|\babout|\baround|\bapproximately|\bapprox\.?|\bnearly|\balmost|\broughly|\bsome|"
                    r"\bover|\bmore than|\bless than|\bunder|\bup to|\bat least|\bestimated|\bclose to|\bupwards of)\s*$", re.I)
DATE_MDY = re.compile(rf"\b({MON})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+((?:19|20)\d\d)\b", re.I)
DATE_DMY = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({MON}),?\s+((?:19|20)\d\d)\b", re.I)
DATE_ISO = re.compile(r"\b((?:19|20)\d\d)-(\d\d)-(\d\d)\b")
DATE_MY = re.compile(rf"\b({MON})\s+((?:19|20)\d\d)\b", re.I)
YEAR = re.compile(r"(?<![\d.,$€£¥/-])((?:19|20)\d\d)(?![\d%]|,\d|\.\d)(?!\s*(?:%|percent|million|billion|trillion))")
VALUE = re.compile(rf"(?P<cur>{CURRENCY}\s?)?(?<![\w.,])(?P<num>{NUM})(?![\d])(?:\s?(?P<scale>{SCALE}))?"
                   rf"(?:\s?(?P<unit>{UNIT}))?", re.I)
# what a sentence's citation markup looks like; numbers inside it are not claims
MARKUP = re.compile(r"!?\[[^\]]*\]\([^)]*\)|https?://\S+|【[^】]*】|\[\^?[\w.-]+\]|(?<=[a-z\)\"”%])[.,]\d{1,3}(?:,\d{1,3})*(?=\s|$)"
                    r"|(?<=[a-z\)\"”])\d{1,3}(?:,\d{1,3})*(?=[.,]?\s|$)")
STOP = frozenset("""this that with from have were been their there which about while these those than then into over
also more most such only other some what when where will would could should after before between during under among
each very much many both being said says according report reported data year years percent million billion trillion
around approximately nearly roughly total average estimated estimate number share rate level since until within""".split())
WINDOW = 300


@dataclass
class Mention:
    text: str
    start: int
    end: int
    kind: str                     # percent | money | value | year | date | month
    value: float | tuple | None
    digits: str = ""              # the mantissa as written, without commas: "3.349"
    decimals: int = 0
    approx: bool = False
    scale: float = 1.0
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = {"text": self.text, "kind": self.kind, "approx": self.approx}
        d["value"] = list(self.value) if isinstance(self.value, tuple) else self.value
        return d


def _month(s: str) -> int:
    return MONTHS[s.lower().rstrip(".")[:4] if s.lower().startswith("sept") else s.lower().rstrip(".")[:3]]


def blank_markup(text: str) -> str:
    """Citation markup replaced by spaces of the same length, so offsets stay valid."""
    return MARKUP.sub(lambda m: " " * len(m.group(0)), text.replace("\\$", " $").replace("\\.", " .").replace("\\-", " -"))


def mentions(sentence: str, *, page: bool = False) -> list[Mention]:
    """Numbers a reader would check. page=True: every number, with small bare integers too (they can be a table
    cell that holds the claim's value), and no markup blanking."""
    text = sentence if page else blank_markup(sentence)
    out: list[Mention] = []
    taken: list[tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= x or a >= y for x, y in taken)

    def add(m: Mention) -> None:
        out.append(m)
        taken.append((m.start, m.end))

    for rx, order in ((DATE_MDY, "mdy"), (DATE_DMY, "dmy"), (DATE_ISO, "iso")):
        for m in rx.finditer(text):
            if not free(m.start(), m.end()):
                continue
            g = m.groups()
            y, mo, d = ((int(g[2]), _month(g[0]), int(g[1])) if order == "mdy" else
                        (int(g[2]), _month(g[1]), int(g[0])) if order == "dmy" else (int(g[0]), int(g[1]), int(g[2])))
            if 1 <= mo <= 12 and 1 <= d <= 31:
                add(Mention(m.group(0), m.start(), m.end(), "date", (y, mo, d)))
    for m in DATE_MY.finditer(text):
        if free(m.start(), m.end()):
            add(Mention(m.group(0), m.start(), m.end(), "month", (int(m.group(2)), _month(m.group(1)))))
    values = []
    for m in VALUE.finditer(text):
        num, scale, unit, cur = m.group("num"), m.group("scale"), m.group("unit"), m.group("cur")
        end = m.end()
        if scale and scale in ("m", "b", "t", "k") and not cur:
            # "5 m" is metres, "3 t" tonnes: lower-case one-letter scales only after a currency sign ("1.6M" is fine)
            scale, unit, end = None, None, m.end("num")
            um = re.match(rf"\s?({UNIT})", text[end:], re.I)
            if um and not um.group(1)[0].isalpha() or um and text[end] == " ":
                unit, end = um.group(1), end + um.end()
        if not (scale or unit) and re.match(r"[A-Za-z_]", text[m.end("num"):m.end("num") + 1]):
            continue  # part of a name or code: "3BP", "H2O", "5G"
        values.append([m.start(), end, num, scale, unit, cur])
    for i, v in enumerate(values):
        # a range ("40-45 cm", "4%-15%", "$1-2 billion"): the first number takes the second one's unit and scale
        if not (v[3] or v[4]) and i + 1 < len(values) and re.fullmatch(r"\s?(?:-|–|—|to)\s?", text[v[1]:values[i + 1][0]]):
            nxt = values[i + 1]
            v[3], v[4], v[5] = nxt[3], nxt[4], v[5] or nxt[5]
            v.append("range")
    for v in values:
        a, b, num, scale, unit, cur = v[:6]
        if not free(a, b):
            continue
        digits = num.replace(",", "")
        value = float(digits)
        if re.fullmatch(r"(?:19|20)\d\d", num) and not (cur or scale or unit):
            if YEAR.match(text, a):
                add(Mention(num, a, a + 4, "year", int(num)))
            continue
        kind = ("percent" if unit and re.match(r"%|per|pct|percentage", unit, re.I) else
                "money" if cur or (unit and re.match(r"yen|dollar|euro|yuan|rupee|pound|won", unit, re.I)) else "value")
        small = kind == "value" and not scale and "." not in digits and len(digits) < 4
        if not page and small and (not unit or re.match(r"years?|people|users?|households?|units?|vehicles?|jobs?|"
                                                        r"patients?|times", unit, re.I) and value < 100):
            continue  # bare small integer, or "5 years", "12 people": too common to identify a passage
        mult = SCALES[scale.lower()] if scale else 1.0
        before = text[max(0, a - 25):a]
        add(Mention(text[a:b].strip(), a, b, kind, value * mult, digits,
                    len(digits.split(".")[1]) if "." in digits else 0, bool(APPROX.search(before)), mult,
                    {"unit": unit, "currency": (cur or "").strip(), "scale_word": scale, "range": len(v) > 6}))
    out.sort(key=lambda x: x.start)
    return out


WORD = re.compile(r"[A-Za-z][A-Za-z'-]{3,}")


def content_words(sentence: str) -> set[str]:
    return {w.lower() for w in WORD.findall(blank_markup(sentence)) if w.lower() not in STOP and w.lower() not in MONTHS}


def normalize_page(text: str) -> str:
    return (text.replace(" ", " ").replace(" ", " ").replace(" ", " ").replace("−", "-")
            .replace("–", "-").replace("’", "'"))


class NumberPage:
    """A page's numbers, parsed once."""

    def __init__(self, text: str) -> None:
        self.text = normalize_page(text)
        self.lower = self.text.lower()
        self.numbers = mentions(self.text, page=True)
        self.by_kind: dict[str, list[Mention]] = {}
        for m in self.numbers:
            self.by_kind.setdefault(m.kind, []).append(m)

    def near(self, start: int, end: int, words: set[str]) -> int:
        window = self.lower[max(0, start - WINDOW):end + WINDOW]
        return sum(1 for w in words if w in window)

    def locate(self, claim: Mention, words: set[str]) -> dict:
        hits: list[tuple[str, Mention]] = []
        if claim.kind in ("date", "month"):
            for m in self.by_kind.get("date", []) + self.by_kind.get("month", []):
                if m.value == claim.value or (claim.kind == "month" and m.kind == "date" and m.value[:2] == claim.value):
                    hits.append(("FOUND" if m.text.lower() == claim.text.lower() else "FOUND_NORMALIZED", m))
        elif claim.kind == "year":
            for m in self.numbers:
                if (m.kind == "year" and m.value == claim.value) or (m.kind in ("date", "month") and m.value[0] == claim.value):
                    hits.append(("FOUND" if m.kind == "year" else "FOUND_NORMALIZED", m))
        else:
            for m in self.numbers:
                if m.kind in ("date", "month", "year") and not (m.kind == "year" and claim.kind == "value"):
                    continue
                v = m.value if m.kind != "year" else float(m.value)
                if claim.kind == "percent" and m.kind not in ("percent", "value"):
                    continue
                if claim.kind != "percent" and m.kind == "percent":
                    continue
                verdict = self._same(claim, m, v)
                if verdict:
                    hits.append((verdict, m))
        if not hits:
            return {"verdict": "NOT_FOUND"}
        rank = {"FOUND": 0, "FOUND_NORMALIZED": 1, "FOUND_ROUNDED": 2}
        scored = sorted(((self.near(m.start, m.end, words), -rank[v], v, m) for v, m in hits),
                        key=lambda t: (t[0] > 0, t[1], t[0]), reverse=True)
        near, _, verdict, m = scored[0]
        res = {"verdict": verdict if near else "NO_CONTEXT", "match": m.text, "offset": m.start, "near_words": near,
               "occurrences": len(hits), "context": self.text[max(0, m.start - 120):m.end + 120]}
        if not near:
            res["would_be"] = verdict
        return res

    @staticmethod
    def _same(claim: Mention, m: Mention, v: float) -> str | None:
        cv = claim.value
        if v == cv or abs(v - cv) <= 1e-9 * max(1.0, abs(cv)):
            same_digits = m.digits == claim.digits and m.scale == claim.scale
            if same_digits and claim.kind == "percent" and m.kind != "percent":
                return "FOUND_NORMALIZED"
            return "FOUND" if same_digits else "FOUND_NORMALIZED"
        half = 0.5 * 10 ** (-claim.decimals) * claim.scale
        if abs(v - cv) <= half + 1e-9 * max(1.0, abs(cv)) and (m.decimals > claim.decimals or m.scale < claim.scale
                                                                 or (m.scale > 1 and v != cv)):
            return "FOUND_ROUNDED"
        if claim.approx and cv and abs(v - cv) <= 0.05 * abs(cv):
            return "FOUND_ROUNDED"
        return None


def check_sentence(sentence: str, page_text: str | None, page: NumberPage | None = None) -> list[dict]:
    """Verdict for every number of the sentence against one page's visible text (None: page unreadable)."""
    words = content_words(sentence)
    if page is None and page_text is not None:
        page = NumberPage(page_text)
    out = []
    for m in mentions(sentence):
        r = {**m.as_dict(), **(page.locate(m, words) if page else {"verdict": "SOURCE_UNAVAILABLE"})}
        out.append(r)
    return out
