"""Text encodings of a page: the Content-Type charset, <meta charset>, the XML declaration, a byte-order mark.

Russian legal sources (garant.ru, pravo.gov.ru) are windows-1251. Read as UTF-8, their text was U+FFFD and no quote
was found, or a page with Cyrillic in its first 4 KB was called "binary body, not text" (a ChatGPT run, 2026-10-19).
"""
from __future__ import annotations

import gzip

from buddie.verbatim.store import Store
from buddie.verbatim.textlayer import charset, layers, looks_binary
from buddie.verify import verify

QUOTE = "Юридическое лицо, присоединившее другое юридическое лицо, подлежит ответственности"
URL = "https://example.ru/koap/2.10"


def page(meta: str = '<meta charset="windows-1251">') -> bytes:
    body = f"<p>{QUOTE} за правонарушение присоединённого лица.</p>" * 30
    return f"<html><head>{meta}<title>Статья 2.10 КоАП РФ</title></head><body>{body}</body></html>".encode("cp1251")


def test_charset_sources_in_order():
    assert charset(b"\xef\xbb\xbf<html>", "text/html; charset=windows-1251") == "utf-8-sig"
    assert charset(page(""), "text/html; charset=windows-1251") == "cp1251"
    assert charset(page()) == "cp1251"
    assert charset(page('<meta http-equiv="Content-Type" content="text/html; charset=windows-1251">')) == "cp1251"
    assert charset(b'<?xml version="1.0" encoding="koi8-r"?><rss/>') == "koi8-r"
    assert charset(b"<html>", "text/html; charset=no-such-codec") == "utf-8"
    assert charset(b"<html>") == "utf-8"


def test_cp1251_page_is_text_and_reads_in_russian():
    data = page()
    assert looks_binary(data)  # what 1.0.0 did: judged as UTF-8, a Russian page looked binary
    assert not looks_binary(data, charset(data))
    visible = layers(data)["visible"]
    assert visible.startswith("Статья 2.10 КоАП РФ") and QUOTE in visible
    assert QUOTE in layers(page(""), "text/html; charset=windows-1251")["visible"]
    assert QUOTE in layers(gzip.compress(page()), "text/html", "gzip")["visible"]


def test_quote_from_a_cp1251_source_is_found(tmp_path):
    store = Store(tmp_path / "store")
    store.add(URL, page(""), content_type="text/html; charset=windows-1251")
    good = f"По статье 2.10 «{QUOTE}» ([КоАП]({URL})).\n"
    bad = f"По статье 2.10 «Юридическое лицо, присоединившее другое юридическое лицо, освобождается от ответственности» ([КоАП]({URL})).\n"
    assert verify(good, store=store.root, fetch=False, mandate=False)["predicate"]["outcome"] == "PASS"
    assert verify(bad, store=store.root, fetch=False, mandate=False)["predicate"]["outcome"] == "FAIL"
