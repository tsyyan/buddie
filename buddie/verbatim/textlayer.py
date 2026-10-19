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

import gzip
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


def looks_binary(data: bytes) -> bool:
    """More than 10 % of the first 4 KB is not text: undecodable bytes or control characters."""
    head = data[:4096].decode("utf-8", errors="replace")
    bad = sum(1 for ch in head if ch == "\ufffd" or (ord(ch) < 32 and ch not in "\t\n\r\f"))
    return bool(head) and bad > len(head) / 10


def decode_body(data: bytes, content_encoding: str | None = None) -> bytes:
    """Undo a Content-Encoding the server applied even though none was asked for (bytes are stored as sent).

    Servers also compress without saying so (E005: gzip from longportapp and ojs.aaai.org, brotli from
    berkshirehathaway.com with no Content-Encoding header), so a body is sniffed: gzip and zlib by their magic bytes,
    brotli by trying it on a body that does not read as text. A body that stays binary raises Unreadable.
    """
    enc = (content_encoding or "").lower().strip()
    if not enc and data[:5] != b"%PDF-":
        if data[:1] == b"\x78" and data[1:2] in (b"\x01", b"\x5e", b"\x9c", b"\xda"):
            enc = "deflate"
        elif looks_binary(data) and data[:2] != b"\x1f\x8b":
            try:
                import brotli
                return _text_or_unreadable(brotli.decompress(data))
            except Exception as error:  # noqa: BLE001 - brotli.error, ImportError: either way not readable text
                raise Unreadable("binary body, not text (and not gzip, deflate or brotli)") from error
    try:
        if enc in ("gzip", "x-gzip") or data[:2] == b"\x1f\x8b":
            return gzip.decompress(data)
        if enc == "deflate":
            try:
                return zlib.decompress(data)
            except zlib.error:
                return zlib.decompress(data, -zlib.MAX_WBITS)
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


def _text_or_unreadable(data: bytes) -> bytes:
    if looks_binary(data):
        raise Unreadable("binary body, not text")
    return data


def layers(data: bytes, content_type: str | None = None, content_encoding: str | None = None) -> dict[str, str]:
    data = decode_body(data, content_encoding)
    if data[:5] == b"%PDF-" or "pdf" in (content_type or "").lower():
        return {"visible": collapse(pdf_text(data)), "hidden": ""}
    _text_or_unreadable(data)
    text = data.decode("utf-8", errors="replace")
    if is_feed(data, content_type):
        once = html.unescape(TAG.sub(" ", text))
        return {"visible": collapse(html.unescape(TAG.sub(" ", once))), "hidden": ""}
    if is_html(data, content_type):
        parser = _Layers()
        parser.feed(text)
        parser.close()
        return {"visible": collapse("".join(parser.visible)), "hidden": collapse(" ".join(parser.hidden))}
    return {"visible": collapse(text), "hidden": ""}
