"""Claims out of a report: each quoted string, paired with the links that cite it.

Markdown rules (deliberately simple, and written down so a reader can predict them):
  - a block is a paragraph, a list item, a table row, or a run of "> " blockquote lines; code is ignored;
  - a quote is text in “…”, «…» or "…" inside a block; a blockquote with no inner quotes is itself one quote;
  - links are [text](url), <url>, bare http(s) URLs, [text][ref], [^note] (resolved through "[ref]: url" /
    "[^note]: ... url" definitions anywhere in the file); balanced parentheses stay in a URL (Wikipedia "_(TV_series)");
  - a quote's own sources ("urls") are the first link after it in the same sentence plus the links right next to it
    ("…” [1][2]", "…” ([a](u), [b](v))"); an empty "()" there means the citation was lost, so the quote has no
    source ("binding": "empty_cite", NO_SOURCE); failing that, the last link before it in the same sentence; failing that,
    every link of the block ("binding": "block"). All links of the block are kept in "block_urls": in a long
    paragraph they cite other sentences, so a quote found only there is not taken as found (E005);
  - a blockquote without links of its own takes the links of the block right before it;
  - quotes shorter than min_chars, and quoted bare URLs (HTML attributes), are skipped;
  - each quote records whether the text presents it as somebody's words ("attributed", see CUE_BEFORE), and
    "not_quote" when it is boilerplate, a title or the agent's own example (see not_a_quote).

JSON input is also accepted: [{"quote": ..., "url": ...}] or {"claims": [...]}; "urls" may be a list.
"""
from __future__ import annotations

import json
import re

FENCE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.M | re.S)
INLINE_CODE = re.compile(r"`[^`\n]*`")
DEF = re.compile(r"^\s{0,3}\[(\^?[^\]]+)\]:\s*(.+)$", re.M)
_U = r"[^\s<>()\[\]\"'“”«»]"
URL = re.compile(rf"https?://(?:{_U}|\({_U}*\))*(?:[^\s<>()\[\]\"'“”«».,;:!?]|\({_U}*\))")
# the target may contain spaces: OpenAI-style text fragments (#:~:text=The exact date of the,1) are not encoded
INLINE_LINK = re.compile(r"!?\[([^\]]*)\]\(<?(https?://(?:[^()<>\s]|\([^()<>\s]*\))+(?:[^()<>\"]*?))>?"
                         r"(?:\s+\"[^\"]*\")?\)")
# a sentence ends before a capital letter or an opening quote; "…” ([src](u))" and "….[1]" stay one sentence
SENTENCE_END = re.compile(r"[.!?][”\"»)\]*]*\s+(?=[A-Z“\"«*_])")
SENTENCE_START = re.compile(r"(?<!\be\.g)(?<!\bi\.e)(?<!\bvs)(?<!\bal)[.!?][”\"»)\]*]*\s+(?=[A-Z“\"«*_])")
# "…” ()" - OpenAI reports where the citation link was stripped (E006 B06, B23)
EMPTY_CITE = re.compile(r"(?<!\])\(\s*\)")
BETWEEN_LINKS = re.compile(r"^[\s,;()\[\]*_]*$")
REF_LINK = re.compile(r"\[([^\]]*)\]\[([^\]]*)\]")
NOTE = re.compile(r"\[\^([^\]]+)\]")
ANGLE = re.compile(r"<(https?://[^>\s]+)>")
# curly quotes and guillemets may span lines inside a block (verse, blockquotes); straight quotes may not
QUOTES = [re.compile(r"“([^”]+)”"), re.compile(r"«([^»]+)»"), re.compile(r'(?<![\d.])"([^"\n]+)"')]
ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


# Is the quote presented as somebody's words? A speech or citation cue just before it ("Turkle explains:",
# "according to", "describes X as"), or a citation / speaker right after it. Quotes without one are often examples,
# hypotheticals or terms ("the infamous “build it and they didn't come”"); a miss on them is reported as uncertain.
# The text after the quote is read with its link syntax, so "…” ([Title](url))" counts as a citation (E006: 12 of 25
# agent errors were hidden as unattributed, most of them cited this way or with the speaker after the quote).
CUE_BEFORE = re.compile(
    r"(\b(?:say|says|said|saying|state|states|stated|stating|write|writes|wrote|according to|note|notes|noted|"
    r"noting|argue|argues|argued|explain|explains|explained|describ\w*|call|calls|called|cite|cites|cited|advis\w*|"
    r"answer\w*|report\w*|quot\w*|statement|words|defin\w*|marvel\w*|acknowledg\w*|articulat\w*|insist\w*|"
    r"indicat\w*|warn\w*|declar\w*|emphasi\w*|stress\w*|added|adds|told|tells|put it|remark\w*|observ\w*|"
    r"claim\w*|conclud\w*|recall\w*|announc\w*|recommend\w*|suggest\w*|asks|asked|in general|in the words of|"
    r"found that|finds that|points? out|remind\w*|per)\b|[:–—][\s*_]*$)", re.I)
CUE_AFTER = re.compile(
    r"^[”\"»]?[*_]*\s*(?:\(\s*\[|\[\^|\[[^\]]+\]\(|\(https?://|,?\s*(?:as\s+)?(?:[\w’'.-]+\s){0,3}"
    r"(?:said|says|according|wrote|writes|explained|explains|notes?|noted|added|states?|stated|reminds?|argues?|"
    r"puts it)\b)", re.I)


def attributed(before: str, after: str) -> bool:
    return bool(CUE_BEFORE.search(before[-90:])) or bool(CUE_AFTER.match(after[:60]))


# Not a quote at all (E008: 46 of 55 false NOT_FOUND). Text in quotation marks that nobody is said to have written:
#   boilerplate - a line the system adds to every report (Doubao "(Note: This document may contain AI-generated content.)")
#   title       - the name of a standard, paper, article, book or song: after a standard's number ("IEEE P7131 – “…”"),
#                 a document noun ("her 2009 article “…”"), at the head of a reference-list item ("- Xu, J., et al. “…”"),
#                 or in Title Case with no speaker
#   example     - the agent's own illustration: after "for example", "e.g.", "such as", "say,", "KPIs like",
#                 "something like:", "might include:", "questions (", or a hypothetical
#                 speaker ("it might generate a statement: “…”", "a teacher could ask ChatGPT to “…”"); a question or a
#                 rule ("if … then …") nobody is said to have asked; a saying ("the adage “…”", "the old “…” trope")
# A named speaker closer to the quote than the cue keeps it a quote ("For example, the WHO states “…”"). The check still
# looks for the words: a not-a-quote that is on the page stays FOUND, one that is not gets NOT_A_QUOTE, not NOT_FOUND.
BOILERPLATE = re.compile(r"may contain AI[- ]generated content|(?:document|report|content|answer) (?:is|was|has been) "
                         r"(?:AI[- ]generated|generated by (?:an? )?AI)", re.I)
STANDARD = re.compile(r"\b(?:ISO|IEC|IEEE|ETSI|ITU(?:-[TR])?|NIST|RFC|ANSI|FIPS|CEN|CENELEC|ASTM|IETF|W3C|3GPP|ISA|"
                      r"BS|DIN|GB/T|JIS)\b[\w\s./:()-]{0,40}[–—:,-]?\s*$")
DOC_NOUN = re.compile(r"\b(?:titled|entitled|named|renamed|article|paper|book|chapter|essay|song|tune|album|poem|novel|"
                      r"film|movie|standard|regulations?|white ?paper|thesis|dissertation|op-ed|blog post|report)"
                      r"\s*(?:\([^()]*\)\s*)?[,:–—]?\s*$", re.I)
SAYING = re.compile(r"\b(?:adage|proverb|idiom|maxim|saying|motto|slogan|mantra|old|cliché)\s*$", re.I)
SAYING_AFTER = re.compile(r"^[”\"»]?\s*(?:trope|cliché|mantra|slogan|motto|adage|stereotype)\b", re.I)
# the cue right before the quote: at most a short gap without names or numbers ("for example, “…”", "(e.g. “…”")
EXAMPLE = re.compile(r"(?:\bfor (?:example|instance)|\be\.g\.|\bi\.e\.|\bsuch as|[(,]\s*say,|\bimagine|\bscenario:|"
                     r"\bhypothetical\w*)(?:[^A-Z0-9“”\"]{0,25})$", re.I)
# "might/could/would … say/ask/generate": a speaker the agent imagines, not one it quotes
MODAL_SPEECH = re.compile(r"\b(?:might|could|may|can)\s+(?:\w+\s+){0,3}?"
                          r"(?:say|ask|answer|generate|produce|review|explain|tell|respond|reply|write|read|prompt|"
                          r"type|request|state|summari[sz]e|note)\w*\b[^.;!?“”\"]{0,40}$", re.I)
SPEECH = re.compile(CUE_BEFORE.pattern.replace(r"|[:–—][\s*_]*$", ""), re.I)  # words only: a colon is no speaker
ASKED = re.compile(r"\b(?:exclaim|cr(?:y|ies|ied) out|respond|demand|pray|plead|repl|shout|lament|refrain|verse|"
                   r"line|surah|psalm)\w*\b|[—–:]\s*$", re.I)
# E010 hints (0.4): the five false NOT_FOUND left by 0.3 were examples after cues the rules above did not know:
# "KPIs like “…”", "something like: “…”", "criteria might include: “…”", "complex questions (“…”". Only these cues,
# right before the quote; a plain noun before "(“" is no cue (it hid 3 agent errors in E010, see not_a_quote).
HINT = re.compile(r"(?:\b(?:something|anything|things?)\s+(?:like|along the lines of)"
                  r"|\b(?!(?:looks|sounds|seems|feels|reads|is|was|tastes|smells)\b)[a-z][\w’'-]*s\s+like"
                  r"|\b(?:might|could|may|would)\s+(?:\w+\s+){0,2}?(?:include|involve)\w*"
                  r"|\b(?:might|could|may|would)\s+(?:\w+\s+){0,2}?(?:be|look|read)(?:\s+like)?\s*:"
                  r"|\b(?:questions?|quer(?:y|ies)|prompts?)\s*\()\s*[:,]?[\s*_]*$", re.I)
LISTED = re.compile(r"^[\s*_]*[,;]?[\s*_]*(?:(?:or|and|and/or)\b)?[\s*_]*$", re.I)
RULE = re.compile(r"^if\b.{3,80}?\b(?:then\b|,\s)", re.I)  # "if load is high then scale out"
LIST_HEAD = re.compile(r"^\s*(?:[-*+]|\d+[.)]|\|)\s*")
REFERENCE = re.compile(r"et al\.?|\b[A-Z][a-z]+,\s+(?:[A-Z]\.|[A-Z][a-z]+)|\((?:19|20)\d{2}[a-z]?\)|"
                       r"\b(?:19|20)\d{2}\b|[–—]\s*$|[,.]\s*$")
SMALL = frozenset("a an the and or of for to in on at by with from as vs via into over under per is are its".split())


def _title_case(quote: str) -> bool:
    words = re.findall(r"[^\W\d_][\w’'-]*", quote)
    content = [w for w in words if w.lower() not in SMALL]
    if len(content) < 3 or quote.rstrip().endswith(("?", "!")):
        return False
    return sum(w[0].isupper() for w in content) / len(content) >= 0.85


def not_a_quote(quote: str, before: str, after: str) -> str | None:
    """Why this quoted text is not somebody's words (rules above), or None. before: the block up to the opening mark,
    after: the block from the closing mark."""
    if BOILERPLATE.search(quote):
        return "boilerplate"
    sentence = SENTENCE_START.split(before)[-1] if before else ""
    head = LIST_HEAD.match(before) and len(before) <= 150 and "\n" not in before.strip() and ":" not in before \
        and re.search(r"[,.–—]\s*$", before)
    spoken = list(SPEECH.finditer(sentence))
    near = sentence[-60:]
    if STANDARD.search(near) or DOC_NOUN.search(near):
        return "title"
    if head and not spoken and REFERENCE.search(before):
        return "title"
    if not spoken and _title_case(quote) and not re.search(r"[:–—]\s*$", sentence):
        return "title"
    if SAYING.search(near) or SAYING_AFTER.match(after):
        return "example"
    if MODAL_SPEECH.search(sentence):
        return "example"
    # not "rules (“…”)": a quote opening a parenthesis after a noun was an example in E008 but the source's own words,
    # reworded, in all 3 such cases of E010 (F014, F049, F094), so the parenthesis alone is no cue
    cue = max((m.end() for m in EXAMPLE.finditer(sentence)), default=-1)
    said = spoken[-1].end() if spoken else -1
    if cue >= 0 and cue >= said:
        return "example"
    if HINT.search(sentence):
        return "example"
    if not attributed(before, after) and not ASKED.search(sentence[-40:]) and (
            quote.rstrip(" ,.").endswith("?") or RULE.match(quote)):
        return "example"
    return None


def _links(block: str, defs: dict[str, str]) -> list[tuple[int, int, str]]:
    """(start, end, url) of every link in the block, in order of position."""
    found: list[tuple[int, int, str]] = []
    for m in INLINE_LINK.finditer(block):
        found.append((m.start(), m.end(), m.group(2).strip()))
    for m in REF_LINK.finditer(block):
        url = defs.get((m.group(2) or m.group(1)).lower())
        if url:
            found.append((m.start(), m.end(), url))
    for m in NOTE.finditer(block):
        url = defs.get("^" + m.group(1).lower())
        if url:
            found.append((m.start(), m.end(), url))
    for m in ANGLE.finditer(block):
        found.append((m.start(), m.end(), m.group(1)))
    for m in EMPTY_CITE.finditer(block):
        found.append((m.start(), m.end(), ""))  # a citation whose link was lost: it still belongs to its quote
    blank = lambda m: " " * len(m.group(0))  # noqa: E731 - keep offsets
    stripped = ANGLE.sub(blank, INLINE_LINK.sub(blank, block))
    for m in URL.finditer(stripped):
        found.append((m.start(), m.end(), m.group(0)))
    return sorted((a, b, u) for a, b, u in found if u == "" or u.startswith(("http://", "https://")))


def _unique(urls) -> list[str]:
    seen: list[str] = []
    for u in urls:
        if u not in seen:
            seen.append(u)
    return seen


def _own_links(block: str, links: list[tuple[int, int, str]], start: int, end: int) -> tuple[list[str], str]:
    """The links that cite the quote at block[start:end] (rules in the module docstring)."""
    after = [link for link in links if link[0] >= end]
    if after and not SENTENCE_END.search(block, end, after[0][0]):
        own = [after[0]]
        for link in after[1:]:
            if not BETWEEN_LINKS.match(block[own[-1][1]:link[0]]):
                break
            own.append(link)
        urls = _unique(u for _, _, u in own if u)
        return (urls, "next") if urls else ([], "empty_cite")
    before = [link for link in links if link[1] <= start]
    if before and before[-1][2] and not SENTENCE_END.search(block, before[-1][1], start):
        return [before[-1][2]], "previous"
    return _unique(u for _, _, u in links if u), "block"


# footnote markers inside the quotation marks are the report's citations, not the source's words: "[1](url)",
# "[2][11](url)", "[2][11][14](url)", a bare "[3]" (E014: "Times New Roman[1](url)?", "bought.[2][11](url)" were read as
# "Roman1?", "bought.[2]11" and missed, S097, S151, S171). Only digits in brackets: "[a son]", "[AI's]" are editorial.
FOOTNOTE = re.compile(r"(?:\[\d{1,3}\])+(?:\(<?https?://(?:[^()<>\s]|\([^()<>\s]*\))+>?\))?")


def _plain(text: str) -> str:
    """Quote text as a reader sees it: footnote markers, link syntax and emphasis markers removed."""
    text = FOOTNOTE.sub("", text)
    text = INLINE_LINK.sub(lambda m: m.group(1), text)
    text = REF_LINK.sub(lambda m: m.group(1), text)
    text = NOTE.sub("", text)
    text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|<>~])", r"\1", text)  # Markdown backslash escapes
    text = re.sub(r"(\*\*|__|\*)(\S(?:.*?\S)?)\1", r"\2", text)
    return text.strip()


def _blocks(markdown: str) -> list[tuple[int, str, bool]]:
    """(first line number, text, is_blockquote)."""
    out: list[tuple[int, str, bool]] = []
    cur: list[str] = []
    start, quote_run = 0, False

    def flush():
        nonlocal cur
        if cur:
            out.append((start, "\n".join(cur), quote_run))
        cur = []

    for n, line in enumerate(markdown.splitlines(), 1):
        is_q = line.lstrip().startswith(">")
        if not line.strip():
            flush()
            continue
        if ITEM.match(line) or line.lstrip().startswith("|") or line.lstrip().startswith("#") or is_q != quote_run:
            flush()
        if not cur:
            start, quote_run = n, is_q
        cur.append(re.sub(r"^\s*>\s?", "", line) if is_q else line)
        if line.lstrip().startswith(("|", "#")):
            flush()
    flush()
    return out


def _blank_code(markdown: str) -> str:
    # keep line numbers stable: replace code with spaces of the same shape
    markdown = FENCE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), markdown)
    return INLINE_CODE.sub(lambda m: " " * len(m.group(0)), markdown)


def from_markdown(markdown: str, min_chars: int = 12) -> tuple[list[dict], int]:
    text = _blank_code(markdown)
    defs = {}
    for key, value in DEF.findall(text):
        found = URL.search(value)
        if found:
            defs[key.lower()] = found.group(0)
    body = DEF.sub("", text)
    claims: list[dict] = []
    skipped = 0
    prev_links: list[str] = []
    for line, block, is_bq in _blocks(body):
        links = _links(block, defs)
        block_urls = _unique(u for _, _, u in links if u)
        # link targets and titles are not quotes: blank them in place, so offsets still point into the block
        masked = INLINE_LINK.sub(lambda m: m.group(0)[:m.start(2) - m.start()]
                                 + " " * (m.end() - m.start(2) - 1) + ")", block)
        quotes: list[tuple[str, bool, int, int]] = []
        spans: list[tuple[int, int]] = []
        for pattern in QUOTES:
            for m in pattern.finditer(masked):
                if any(a <= m.start() < b for a, b in spans):
                    continue  # straight quotes inside a “…” already taken
                spans.append(m.span())
                before = INLINE_LINK.sub(lambda x: x.group(1), block[:m.start()])
                after = block[m.end():]
                quotes.append((block[m.start(1):m.end(1)], attributed(before, after), m.start(), m.end(),
                               not_a_quote(_plain(block[m.start(1):m.end(1)]), before, after)))
        # "questions (“A?” or “B?”)", "KPIs like “X” or “Y”": a quote listed right after another shares its cue (E010
        # F001, F059 were the second quote of such a list)
        quotes.sort(key=lambda t: t[2])
        for i in range(1, len(quotes)):
            prev, cur = quotes[i - 1], quotes[i]
            if prev[4] and not cur[4] and LISTED.match(block[prev[3]:cur[2]]):
                quotes[i] = cur[:4] + (prev[4],)
        if is_bq:
            quotes = quotes or [(block, True, 0, len(block), not_a_quote(_plain(block), "", ""))]  # a citation by form
        for q, attr, a, b, kind in quotes:
            q = _plain(q)
            if len(q) < min_chars or URL.fullmatch(q):
                skipped += 1
                continue
            if is_bq and not links:
                urls, binding, around = prev_links, "previous_block", prev_links
            else:
                (urls, binding), around = _own_links(masked, links, a, b), block_urls
            claim = {"id": f"L{line}.{len([c for c in claims if c['line'] == line]) + 1}",
                     "line": line, "quote": q, "urls": urls, "attributed": attr}
            if kind:
                claim["not_quote"] = kind
            if around != urls:
                claim.update(binding=binding, block_urls=around)
            claims.append(claim)
        prev_links = block_urls
    return claims, skipped


def from_json(data) -> list[dict]:
    items = data.get("claims", []) if isinstance(data, dict) else data
    out = []
    for i, c in enumerate(items, 1):
        urls = c.get("urls") or ([c["url"]] if c.get("url") else [])
        out.append({"id": str(c.get("id", f"C{i}")), "line": c.get("line"), "quote": c["quote"], "urls": urls,
                    "attributed": c.get("attributed", True), **({"not_quote": c["not_quote"]} if c.get("not_quote") else {})})
    return out


def load(path: str, text: str, min_chars: int = 12) -> tuple[list[dict], int]:
    if path.endswith(".json"):
        return from_json(json.loads(text)), 0
    return from_markdown(text, min_chars)
