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
                    (a year: no word of its own clause within YEAR_WINDOW characters)
  UNCERTAIN         not on the page, but the miss may not be the report's fault ("doubts" says why, as for quotes):
                    abstract_only - the page is the paper's abstract (arXiv /abs/, OpenAlex), not the paper
                    rewritten     - a market report whose page now forecasts a later period than the sentence
                                    (2026-2034 against the sentence's 2025-2033): the agent read an earlier edition
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
# Russian scale words after a number ("$35.0 млн" is "$35.0 million", E016 de7a5d): abbreviations and full words
RU_SCALES = (("тыс", 1e3), ("млрд", 1e9), ("млн", 1e6), ("трлн", 1e12), ("миллиард", 1e9), ("миллион", 1e6),
             ("триллион", 1e12))
SCALE = (r"(?:thousand|million|billion|trillion|crore|lakh|mn|mln|bn|tn|k|m|b|t|тыс|млрд|млн|трлн|"
         r"тысяч[аиуе]?|миллиард(?:а|ов|ы)?|миллион(?:а|ов|ы)?|триллион(?:а|ов|ы)?)\b")


def scale_of(word: str) -> float:
    w = word.lower()
    return SCALES.get(w) or next(mult for stem, mult in RU_SCALES if w.startswith(stem))
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
# PubMed's citation line ("J Clin Med. 2024 Jan 5;13(2):304", E015 N036) and numeric dates ("10/09/2018", N044)
DATE_YMD = re.compile(rf"\b((?:19|20)\d\d)\s+({MON})\s+(\d{{1,2}})\b(?![\d,.]\d)", re.I)
DATE_NUM = re.compile(r"(?<![\d/.])(\d{1,2})/(\d{1,2})/((?:19|20)\d\d)\b(?!/)")
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
# A part of a sentence that says the number is not on the page names the year it is missing for ("за 2023 год на
# странице её нет", E016 de7a5d): that year is not a claim of the page, and looking for it only finds a false NOT_FOUND
ABSENT = re.compile(r"на странице\s+(?:\w+\s+){0,2}нет\b|\bнет на странице|\b(?:числа|данных|цифры|значения|выручки)\s+"
                    r"(?:\w+\s+){0,4}нет\b|\bне (?:указан|приведен|приведён|найден|упомянут|упомина|встречает)\w*|"
                    r"\b(?:нет|ноль) совпадений|"
                    r"\bnot (?:on|in|given on|stated on|found on|found in|reported on) the (?:page|source)\b|"
                    r"\b(?:page|source) (?:does not|doesn't) (?:give|state|report|mention|show|list|contain|include)\b|"
                    r"\bno (?:figure|number|value|data) (?:for|on)\b", re.I)
CLAUSE_END = re.compile(r"[.!?;](?=\s|$)|\n|`")
# A year is on almost every page (footers, archives, reference lists), and the sentence's words are usually somewhere
# within 300 characters too: E009 called 9 of 15 wrong years found that way. A year counts as found only with a word of
# its own clause (YEAR_CLAUSE characters around it in the sentence) within YEAR_WINDOW characters on the page.
YEAR_CLAUSE = 60
YEAR_WINDOW = 150


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


# Evidence about the report's own work is not a claim of the page (E016, NEXT №99): a `run:` anchor holds a command
# and its output (`grep -c "2023" => 0` searches for the year the report says is missing), and the time a snapshot
# was taken ("sha256 a9c616f7…, 2026-10-03T17:21:26Z") is the year of the run, not of the page
RUN_ANCHOR = re.compile(r"`\s*run:[^`\n]*`?|⚓\s*run:[^`\n]*")
STAMP = re.compile(r"\b(?:19|20)\d\d-\d\d-\d\d[T ]\d\d:\d\d(?::\d\d(?:\.\d+)?)?(?:Z|[+-]\d\d:?\d\d|\s?UTC)?")
SNAPSHOT = re.compile(r"sha256|снимок|снимка|снимке|снят|копи[юяи]|сохранил|snapshot|captured|fetched|retrieved|"
                      r"saved|archived|downloaded", re.I)
SNAPSHOT_WINDOW = 120


def _blank(text: str, pattern: re.Pattern, keep=lambda m: False) -> str:
    return pattern.sub(lambda m: m.group(0) if keep(m) else " " * len(m.group(0)), text)


def blank_markup(text: str) -> str:
    """Citation markup, `run:` anchors and snapshot timestamps replaced by spaces of the same length, so offsets stay
    valid."""
    text = MARKUP.sub(lambda m: " " * len(m.group(0)), text.replace("\\$", " $").replace("\\.", " .").replace("\\-", " -"))
    text = _blank(text, RUN_ANCHOR)
    return _blank(text, STAMP, lambda m: not SNAPSHOT.search(text, max(0, m.start() - SNAPSHOT_WINDOW), m.start()))


# thousands grouped by a (thin) space, "94 239" (PMC, E015 N095): text layers collapse U+2009 into a plain space, so
# on a page a run of 3-digit groups is read both ways, as one number and as separate cells. Five digits or more:
# "Table 3 100" is more often two numbers than 3,100
SPACED_GROUPS = re.compile(r"(?<![\w.,])\d{1,3}(?: \d{3})+(?!\d|[.,]\d)")


def mentions(sentence: str, *, page: bool = False) -> list[Mention]:
    """Numbers a reader would check. page=True: every number, with small bare integers too (they can be a table
    cell that holds the claim's value), and no markup blanking."""
    if page:
        grouped = SPACED_GROUPS.sub(lambda m: m.group(0).replace(" ", ",") if len(m.group(0)) >= 6 else m.group(0),
                                    sentence)
        if grouped != sentence:
            out = _mentions(sentence, True)
            seen = {(m.start, m.end) for m in out}
            for m in _mentions(grouped, True):
                if (m.start, m.end) not in seen and " " in sentence[m.start:m.end].strip() and "," in m.text:
                    m.text = sentence[m.start:m.end].strip()
                    out.append(m)
            return sorted(out, key=lambda x: x.start)
    return _mentions(sentence, page)


def _mentions(sentence: str, page: bool) -> list[Mention]:
    text = sentence if page else blank_markup(sentence)
    out: list[Mention] = []
    taken: list[tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= x or a >= y for x, y in taken)

    def add(m: Mention) -> None:
        out.append(m)
        taken.append((m.start, m.end))

    for rx, order in ((DATE_MDY, "mdy"), (DATE_DMY, "dmy"), (DATE_ISO, "iso"), (DATE_YMD, "ymd"), (DATE_NUM, "num")):
        for m in rx.finditer(text):
            if not free(m.start(), m.end()):
                continue
            g = m.groups()
            y, mo, d = ((int(g[2]), _month(g[0]), int(g[1])) if order == "mdy" else
                        (int(g[2]), _month(g[1]), int(g[0])) if order == "dmy" else
                        (int(g[0]), _month(g[1]), int(g[2])) if order == "ymd" else
                        (int(g[2]), int(g[0]), int(g[1])) if order == "num" else (int(g[0]), int(g[1]), int(g[2])))
            extra = {}
            if order == "num":  # 10/09/2018: October 9 in the US, 10 September elsewhere; either reading may be meant
                if mo > 12:
                    mo, d = d, mo
                elif d <= 12 and d != mo:
                    extra["alt"] = (y, d, mo)
            if 1 <= mo <= 12 and 1 <= d <= 31:
                add(Mention(m.group(0), m.start(), m.end(), "date", (y, mo, d), extra=extra))
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
        # A larger first number is not a range start: "from 12.3 million in 2020 to 16.2 million" (E015 N055)
        if not (v[3] or v[4]) and i + 1 < len(values) and re.fullmatch(r"\s?(?:-|–|—|to)\s?", text[v[1]:values[i + 1][0]]) \
                and float(v[2].replace(",", "")) <= float(values[i + 1][2].replace(",", "")):
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
        mult = scale_of(scale) if scale else 1.0
        before = text[max(0, a - 25):a]
        add(Mention(text[a:b].strip(), a, b, kind, value * mult, digits,
                    len(digits.split(".")[1]) if "." in digits else 0, bool(APPROX.search(before)), mult,
                    {"unit": unit, "currency": (cur or "").strip(), "scale_word": scale, "range": len(v) > 6}))
    out.sort(key=lambda x: x.start)
    if not page and ABSENT.search(text):
        out = [m for m in out if m.kind != "year" or not _named_missing(text, m.start)]
    return out


def _named_missing(text: str, at: int) -> bool:
    """The year at `at` names what an ABSENT phrase of its clause says is missing: it stands before the phrase
    ("за 2023 год на странице её нет") or right after it, before a comma ("the page gives no figure for 2023"), but
    not in what follows ("нет, есть только перепись 2010")."""
    a = max([0] + [m.end() for m in CLAUSE_END.finditer(text, 0, at)])
    b = next((m.end() for m in CLAUSE_END.finditer(text, at)), len(text))
    for m in ABSENT.finditer(text, a, b):
        if at < m.start() or not re.search(r"[,:;(—–]", text[m.end():at]):
            return True
    return False


WORD = re.compile(r"[A-Za-z][A-Za-z'-]{3,}")


def content_words(sentence: str) -> set[str]:
    return {w.lower() for w in WORD.findall(blank_markup(sentence)) if w.lower() not in STOP and w.lower() not in MONTHS}


def normalize_page(text: str) -> str:
    return (text.replace(" ", " ").replace(" ", " ").replace(" ", " ").replace("−", "-")
            .replace("–", "-").replace("’", "'"))


# a table that declares its unit once: "Population aged 80+ (thousands) ... 2020: 12,347" is the 12.3 million of the
# sentence (E015 N055, UN ESCAP data sheet). Numbers without a unit of their own after such a declaration are read
# also at that scale
DECLARED = re.compile(r"\((?:in )?(thousands?|millions?|billions?)\)|\bin (thousands|millions|billions)\b|"
                      r"\((?:in )?'?(000)s?'?\)|\('(000)\)", re.I)
DECLARED_SCALE = {"thousand": 1e3, "000": 1e3, "million": 1e6, "billion": 1e9}
DECLARED_WINDOW = 1500


# a market report's forecast period ("Forecast Period 2026-2034", "forecast period (2026–2033)", "Forecasts, 2026-2034"):
# these pages are rewritten every year, figures and horizon together (E015 N032, E009 S038)
FORECAST_PERIOD = re.compile(r"\bforecasts?\b(?: period| years?)?[^.\d]{0,20}?\(?((?:19|20)\d\d)\s?(?:-|to)\s?((?:19|20)\d\d)\b",
                             re.I)
# a sentence that states a forecast or growth rate of an edition: its years are that edition's horizon
FORECAST_CLAIM = re.compile(r"\b(?:CAGR|compound annual growth|forecast\w*|projected|expected to (?:reach|grow|hit)|"
                            r"anticipated to (?:reach|grow))\b", re.I)
# a paper's abstract page, not the paper: numbers of the body are not there (E015 N061)
ABSTRACT_PAGE = re.compile(r"https?://(?:www\.|export\.)?arxiv\.org/abs/", re.I)


def page_doubts(entry: dict, url: str | None = None) -> list[str]:
    """Doubts a snapshot casts on every miss on it: an OpenAlex abstract (access.py) or an arXiv /abs/ page."""
    if entry.get("abstract_only") or url and ABSTRACT_PAGE.match(url) and not entry.get("provenance") in ("copy", "relay"):
        return ["abstract_only"]
    return []


class NumberPage:
    """A page's numbers, parsed once. doubts: what the snapshot itself casts on a miss (page_doubts)."""

    def __init__(self, text: str, doubts: list[str] | tuple = ()) -> None:
        self.doubts = list(doubts)
        self.text = normalize_page(text)
        self.lower = self.text.lower()
        self.numbers = mentions(self.text, page=True)
        declared = [(d.end(), DECLARED_SCALE[next(g for g in d.groups() if g).lower().rstrip("s")])
                    for d in DECLARED.finditer(self.text)]
        if declared:
            scaled = []
            for m in self.numbers:
                if m.kind not in ("value", "money") or m.scale != 1.0 or m.extra.get("unit"):
                    continue
                at = [mult for end, mult in declared if 0 <= m.start - end <= DECLARED_WINDOW]
                if at:
                    scaled.append(Mention(m.text, m.start, m.end, m.kind, m.value * at[-1], m.digits, m.decimals,
                                          m.approx, at[-1], dict(m.extra, declared=True)))
            self.numbers = sorted(self.numbers + scaled, key=lambda x: x.start)
        self.by_kind: dict[str, list[Mention]] = {}
        for m in self.numbers:
            self.by_kind.setdefault(m.kind, []).append(m)
        periods = [(int(a), int(b)) for a, b in FORECAST_PERIOD.findall(self.text) if 0 < int(b) - int(a) <= 20]
        self.horizon = max(periods, key=lambda p: (p[1], p[0])) if periods else None  # the latest period declared

    def rewritten(self, sentence: str) -> bool:
        """The sentence states a forecast of an earlier edition of this page: its end year ("by 2033", the later year
        of two) is before the page's forecast end, or its only year (the base: "valued at $266 million in 2023") is
        before the page's base year, the year before its forecast starts."""
        if not self.horizon or not FORECAST_CLAIM.search(sentence):
            return False
        ys = [m for m in mentions(sentence) if m.kind == "year"]
        if not ys:
            return False
        last = max(ys, key=lambda m: m.value)
        if len({m.value for m in ys}) > 1 or re.search(r"\bby\s*$", blank_markup(sentence)[:last.start]):
            return last.value < self.horizon[1]
        return last.value < self.horizon[0] - 1

    def near(self, start: int, end: int, words: set[str], window: int = WINDOW) -> int:
        span = self.lower[max(0, start - window):end + window]
        return sum(1 for w in words if w in span)

    def locate(self, claim: Mention, words: set[str], window: int = WINDOW) -> dict:
        hits: list[tuple[str, Mention]] = []
        if claim.kind in ("date", "month"):
            for m in self.by_kind.get("date", []) + self.by_kind.get("month", []):
                readings = [m.value] + ([m.extra["alt"]] if m.extra.get("alt") else [])
                if claim.value in readings or (claim.kind == "month" and m.kind == "date"
                                               and claim.value in [r[:2] for r in readings]):
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
        scored = sorted(((self.near(m.start, m.end, words, window), -rank[v], v, m) for v, m in hits),
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
    blanked = blank_markup(sentence)
    doubts = page.doubts + (["rewritten"] if page.rewritten(sentence) else []) if page is not None else []
    out = []
    for m in mentions(sentence):
        if page is None:
            found = {"verdict": "SOURCE_UNAVAILABLE"}
        elif m.kind == "year":
            clause = content_words(blanked[max(0, m.start - YEAR_CLAUSE):m.end + YEAR_CLAUSE])
            found = page.locate(m, clause, YEAR_WINDOW)
        else:
            found = page.locate(m, words)
        if found["verdict"] == "NOT_FOUND" and doubts:
            found = dict(found, verdict="UNCERTAIN", doubts=doubts)
        out.append({**m.as_dict(), **found})
    return out


# --- cited sentences of a report (E009 scripts/sentences.py, moved here so buddie and the experiments share it) ---

SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z*\"“(])|\n+")
INLINE = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+(?:\([^)\s]*\)[^)\s]*)*)\)")
NOTE = re.compile(r"\[\^?(\d+(?:_\d+)?)\]")
DEFN = re.compile(r"^\s{0,3}\[\^?(\d+(?:_\d+)?)\]:\s*(.+)$", re.M)
LIST = re.compile(r"^\s*(\d{1,3})\.\s+(.+)$", re.M)
# footnote digits of a report with a numbered source list and no link syntax (Gemini Deep Research): glued after a
# word ("outlook.5", "infarction.66"), or after a space where a number cannot be one ("in 2019 16, a", "2023 13, and",
# "ID) 41 and"): after a year, a closing bracket or a percent, before a comma or a small joining word (E009 S003,
# S007, S011 were checked against the sentence's other note)
GLUED = re.compile(r"(?<=[a-z\)\"”%])[.,]?(\d{1,3}(?:,\d{1,3})*)(?=[.,]?\s|$)")
SPACED = re.compile(r"(?:(?<=\b(?:19|20)\d\d)|(?<=[)%\"”])) (\d{1,3}(?:,\d{1,3})*)(?=[,;]\s|[,;]?$|\s(?:and|or|but|while|"
                    r"which|whereas|with|as|so|yet|although|though|can|is|are|was|were)\b)")
NOTES_END = re.compile(r"([a-z\)\"”%][.!?]\d{1,3}(?:,\d{1,3})*)[ \t]+(?=[A-Z*])")
SOURCE_LIST_ENTRY = re.compile(r"^\s*\d{1,3}\.\s")
ACCESSED = re.compile(r"访问时间|檢索日期|accessed", re.I)


def _first_url(text: str) -> str | None:
    from verbatim.report import URL as BARE
    m = INLINE.search(text)
    if m:
        return m.group(2)
    m = BARE.search(text.replace("\\_", "_"))
    return m.group(0) if m else None


def note_sources(article: str) -> dict[str, str]:
    """footnote number -> URL from `[^n]: url` definitions and from a numbered source list after the last heading."""
    defs = {n: _first_url(t) for n, t in DEFN.findall(article)}
    tail = article[article.rfind("\n#"):] if "\n#" in article else article[-len(article) // 3:]
    for n, t in LIST.findall(tail):
        if n not in defs and _first_url(t):
            defs[n] = _first_url(t)
    return {n: u.replace("\\_", "_") for n, u in defs.items() if u}


def cites(sentence: str, defs: dict[str, str], bare_notes: bool = False) -> list[str]:
    """URLs a sentence cites, in order: markdown links, bare URLs, `[^n]`/`[n]` notes; with bare_notes also footnote
    digits without brackets (GLUED, SPACED)."""
    from verbatim.report import URL as BARE
    found = [(m.start(), m.group(2)) for m in INLINE.finditer(sentence)]
    spans = [(m.start(), m.end()) for m in INLINE.finditer(sentence)]
    for m in BARE.finditer(sentence):
        if not any(a <= m.start() < b for a, b in spans):
            found.append((m.start(), m.group(0)))
    for m in NOTE.finditer(sentence):
        if m.group(1) in defs:
            found.append((m.start(), defs[m.group(1)]))
    if bare_notes:
        for rx in (GLUED, SPACED):
            for m in rx.finditer(sentence):
                for n in m.group(1).split(","):
                    if n in defs:
                        found.append((m.start(), defs[n]))
    urls: list[str] = []
    for _, u in sorted(found):
        u = u.replace("\\_", "_")
        if u not in urls:
            urls.append(u)
    return urls


def cited_sentences(article: str, bare_notes: bool | None = None) -> list[dict]:
    """Every sentence of a markdown report that has a number `mentions` would check and a citation that resolves to a
    URL: {"n" (sentence index), "sentence", "urls", "numbers"}. bare_notes None: on when the report has a numbered
    source list and no markdown links (Gemini's export)."""
    defs = note_sources(article)
    if bare_notes is None:
        bare_notes = bool(defs) and not INLINE.search(article) and not DEFN.search(article)
    if bare_notes:  # "infarction.66 Participants": a footnote glued after the full stop ends the sentence
        article = NOTES_END.sub(r"\1\n", article)
    out = []
    for i, s in enumerate(SENT.split(article)):
        if s.lstrip().startswith(("[^", "[")) and DEFN.match(s) or ACCESSED.search(s):
            continue
        if SOURCE_LIST_ENTRY.match(s) and _first_url(s) and len(s) < 600 and "http" in s[:400]:
            continue  # an entry of the source list
        ms = mentions(s)
        if not ms:
            continue
        urls = cites(s, defs, bare_notes)
        if urls:
            out.append({"n": i, "sentence": s.strip(), "urls": urls, "numbers": [x.as_dict() for x in ms]})
    return out


RANK = ["FOUND", "FOUND_NORMALIZED", "FOUND_ROUNDED", "NO_CONTEXT", "UNCERTAIN", "NOT_FOUND", "SOURCE_UNAVAILABLE"]


def check_report(markdown: str, store, *, fetch: bool = False) -> list[dict]:
    """Verdict for every number of every cited sentence of a markdown report, judged on the readable snapshots of
    the sentence's links (check.readable: errors, gates, app shells and redirects are SOURCE_UNAVAILABLE); the best
    verdict over the links wins, as a reader checks the sentence's sources, not one of them. fetch: download a link
    the store does not have. Rows: {"id" (L<line>.<n>), "line", "sentence", "text", "kind", "verdict", "url",
    "sha256", "match", "context", ...}."""
    from verbatim.check import readable
    pages: dict[str, list] = {}

    def read(url: str) -> list:
        if url not in pages:
            entries = store.index().get(_canonical(url), [])
            if not any(e.get("sha256") for e in entries) and fetch:
                entries = entries + [store.fetch(url)]
            pages[url] = []
            for e in entries:
                got = readable(store, e, url)
                if not isinstance(got, dict):
                    pages[url].append((e, NumberPage(got[1].visible, page_doubts(e, url))))
        return pages[url]

    rows, starts = [], [0] + [i + 1 for i, ch in enumerate(markdown) if ch == "\n"]
    for c in cited_sentences(markdown):
        at = markdown.find(c["sentence"])
        line = sum(1 for s in starts if s <= at) if at >= 0 else None
        best = None
        for url in c["urls"]:
            for e, pg in read(url):
                res = check_sentence(c["sentence"], None, pg)
                for r in res:
                    r.update(url=url, sha256=e["sha256"])
                best = res if best is None else [min(a, b, key=lambda r: RANK.index(r["verdict"])) for a, b in zip(best, res)]
        if best is None:
            best = [dict(r, url=c["urls"][0]) for r in check_sentence(c["sentence"], None)]
        for k, r in enumerate(best, 1):
            r.update(id=f"L{line}.n{k}", line=line, sentence=c["sentence"][:300])
            rows.append(r)
    return rows


def _canonical(url: str) -> str:
    from verbatim.store import canonical_url
    return canonical_url(url)
