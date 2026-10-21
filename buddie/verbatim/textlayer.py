"""Text layers of a snapshot: what a reader sees, and what is only in the markup.

visible  text outside <script>/<style>/<noscript>/<template>, entities decoded, whitespace collapsed.
         Block tags (p, li, br, td ...) separate words; inline tags (a, em, span ...) do not, so
         "September 22</a>, September 15" stays "September 22, September 15" (E002 lost two quotes to this).
hidden   script bodies (JSON-LD), <meta content>, alt/title attributes: publisher text a reader does not see.

PDFs go through poppler's pdftotext when it is installed; words hyphenated across a line break are rejoined.
Without pdftotext a PDF raises Unreadable, and the check reports the source as unavailable rather than guessing.

Feeds (RSS/Atom) are XML whose descriptions carry escaped HTML, so they are unescaped and stripped twice.
"""
from __future__ import annotations

import codecs
import html
import re
import shutil
import subprocess
import zlib
from html.parser import HTMLParser

WS = re.compile(r"\s+")
TAG = re.compile(r"<[^>]+>")

BLOCK = {
    "address", "article", "aside", "blockquote", "body", "br", "caption", "dd", "details", "dialog", "div", "dl",
    "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "head",
    "header", "hr", "html", "img", "input", "li", "main", "nav", "ol", "option", "p", "pre", "section", "select",
    "summary", "table", "tbody", "td", "textarea", "tfoot", "th", "thead", "title", "tr", "ul", "button", "label",
}
SKIP = {"script", "style", "noscript", "template", "svg"}
HIDDEN_ATTRS = {"alt", "title", "aria-label"}


class Unreadable(Exception):
    """The snapshot exists but its text cannot be extracted here."""


MAX_DECODED_BYTES = 64 * 2**20  # a compressed body that expands past this is not read
GZIP, ZLIB, RAW = 16 + zlib.MAX_WBITS, zlib.MAX_WBITS, -zlib.MAX_WBITS


def inflate(data: bytes, wbits: int = GZIP, limit: int | None = None) -> bytes:
    """gzip, zlib or raw deflate `data` decompressed, never past `limit` bytes (MAX_DECODED_BYTES): a body of a few
    MiB can expand a thousandfold. Unreadable past the limit; EOFError for a cut-off stream and zlib.error for bad
    data, as gzip.decompress and zlib.decompress raise them. gzip members after the first are read in turn."""
    limit = MAX_DECODED_BYTES if limit is None else limit
    out = bytearray()
    while True:
        d = zlib.decompressobj(wbits)
        out += d.decompress(data, limit + 1 - len(out))
        if len(out) > limit or d.unconsumed_tail:
            raise Unreadable(f"compressed body expands past {limit // 2**20} MiB, not read")
        if not d.eof:
            raise EOFError("compressed stream ended before the end-of-stream marker")
        data = d.unused_data
        if wbits != GZIP or not data.startswith(b"\x1f\x8b"):
            return bytes(out)


def collapse(text: str) -> str:
    return WS.sub(" ", text).strip()


class _Layers(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip: list[str] = []
        self.visible: list[str] = []
        self.hidden: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skip.append(tag)
        elif tag in BLOCK:
            self.visible.append(" ")
        for name, value in attrs:
            if value and (name in HIDDEN_ATTRS or (tag == "meta" and name == "content")):
                self.hidden.append(value)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in SKIP and self.skip and self.skip[-1] == tag:
            self.skip.pop()

    def handle_endtag(self, tag):
        if tag in SKIP:
            if tag in self.skip:
                while self.skip and self.skip.pop() != tag:
                    pass
        elif tag in BLOCK:
            self.visible.append(" ")

    def handle_data(self, data):
        (self.hidden if self.skip else self.visible).append(data)


def is_feed(data: bytes, content_type: str | None) -> bool:
    ct = (content_type or "").lower()
    if "rss" in ct or "atom" in ct or ct.startswith(("application/xml", "text/xml")):
        return True
    head = data[:512].lstrip().lower()
    return head.startswith(b"<?xml") and (b"<rss" in data[:2048].lower() or b"<feed" in data[:2048].lower())


def is_html(data: bytes, content_type: str | None) -> bool:
    ct = (content_type or "").lower()
    if "html" in ct:
        return True
    if ct.startswith("text/plain") or ct.startswith("application/json"):
        return False
    head = data[:1024].lstrip().lower()
    return head.startswith((b"<!doctype html", b"<html")) or b"<body" in data[:4096].lower()


def pdf_text(data: bytes) -> str:
    exe = shutil.which("pdftotext")
    if not exe:
        raise Unreadable("PDF: pdftotext (poppler-utils) is not installed")
    try:
        out = subprocess.run([exe, "-enc", "UTF-8", "-", "-"], input=data, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired as error:
        raise Unreadable("PDF: pdftotext timed out") from error
    if out.returncode != 0:
        raise Unreadable(f"PDF: pdftotext failed ({out.stderr.decode(errors='replace')[:120].strip()})")
    text = out.stdout.decode("utf-8", errors="replace")
    return re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)


CHARSET_HEADER = re.compile(r"""charset\s*=\s*["']?([\w.:-]+)""", re.I)
CHARSET_META = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([\w.:-]+)""", re.I)
CHARSET_XML = re.compile(rb"""<\?xml[^>]+encoding\s*=\s*["']([\w.:-]+)""", re.I)


def charset(data: bytes, content_type: str | None = None) -> str:
    """The body's text encoding: a byte-order mark, else the Content-Type charset, else <meta charset> or
    http-equiv, else the XML declaration, else UTF-8. Russian legal sites (garant.ru, pravo.gov.ru) send
    windows-1251; read as UTF-8 their text became U+FFFD, or the page was called binary, and no quote was found."""
    for bom, name in ((codecs.BOM_UTF8, "utf-8-sig"), (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16")):
        if data.startswith(bom):
            return name
    found = CHARSET_HEADER.search(content_type or "")
    names = [found.group(1)] if found else []
    head = data[:4096]
    names += [m.group(1).decode("ascii", "replace") for m in (CHARSET_META.search(head), CHARSET_XML.search(head)) if m]
    for name in names:
        try:
            return codecs.lookup(name).name
        except LookupError:
            continue
    return "utf-8"


def looks_binary(data: bytes, encoding: str = "utf-8") -> bool:
    """More than 10 % of the first 4 KB is not text in `encoding`: undecodable bytes or control characters."""
    head = data[:4096].decode(encoding, errors="replace")
    bad = sum(1 for ch in head if ch == "\ufffd" or (ord(ch) < 32 and ch not in "\t\n\r\f"))
    return bool(head) and bad > len(head) / 10


def decode_body(data: bytes, content_encoding: str | None = None, content_type: str | None = None) -> bytes:
    """Undo a Content-Encoding the server applied even though none was asked for (bytes are stored as sent).

    Servers also compress without saying so (E005: gzip from longportapp and ojs.aaai.org, brotli from
    berkshirehathaway.com with no Content-Encoding header), so a body is sniffed: gzip and zlib by their magic bytes,
    brotli by trying it on a body that does not read as text. A body that stays binary raises Unreadable.
    """
    enc = (content_encoding or "").lower().strip()
    if not enc and data[:5] != b"%PDF-":
        if data[:1] == b"\x78" and data[1:2] in (b"\x01", b"\x5e", b"\x9c", b"\xda"):
            enc = "deflate"
        elif looks_binary(data, charset(data, content_type)) and data[:2] != b"\x1f\x8b":
            try:
                import brotli
                body = brotli.decompress(data)
                return _text_or_unreadable(body, charset(body, content_type))
            except Exception as error:  # noqa: BLE001 - brotli.error, ImportError: either way not readable text
                raise Unreadable("binary body, not text (and not gzip, deflate or brotli)") from error
    try:
        if enc in ("gzip", "x-gzip") or data[:2] == b"\x1f\x8b":
            return inflate(data, GZIP)
        if enc == "deflate":
            try:
                return inflate(data, ZLIB)
            except zlib.error:
                return inflate(data, RAW)
        if enc == "br":
            try:
                import brotli  # optional: pip install brotli
            except ImportError as error:
                raise Unreadable("body is brotli-compressed and the brotli module is not installed") from error
            return brotli.decompress(data)
    except (OSError, EOFError, zlib.error) as error:
        if not content_encoding and enc == "deflate":
            return data  # the magic bytes were a coincidence
        raise Unreadable(f"{enc or 'gzip'} body does not decompress: {error}") from error
    return data


def _text_or_unreadable(data: bytes, encoding: str = "utf-8") -> bytes:
    if looks_binary(data, encoding):
        raise Unreadable("binary body, not text")
    return data


def layers(data: bytes, content_type: str | None = None, content_encoding: str | None = None) -> dict[str, str]:
    data = decode_body(data, content_encoding, content_type)
    if data[:5] == b"%PDF-" or "pdf" in (content_type or "").lower():
        return {"visible": collapse(pdf_text(data)), "hidden": ""}
    encoding = charset(data, content_type)
    _text_or_unreadable(data, encoding)
    text = data.decode(encoding, errors="replace")
    if is_feed(data, content_type):
        once = html.unescape(TAG.sub(" ", text))
        return {"visible": collapse(html.unescape(TAG.sub(" ", once))), "hidden": ""}
    if is_html(data, content_type):
        parser = _Layers()
        parser.feed(text)
        parser.close()
        return {"visible": collapse("".join(parser.visible)), "hidden": collapse(" ".join(parser.hidden))}
    return {"visible": collapse(text), "hidden": ""}
