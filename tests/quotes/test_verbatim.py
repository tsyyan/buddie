"""verbatim tests. Regression data: E001 byte snapshots (raw/) and the quotes E002 located in them."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from verbatim.check import check_claims, loose
from verbatim.cli import main
from verbatim.report import from_markdown
from verbatim.store import Store
from verbatim.textlayer import layers

# Regression tests read third-party page snapshots kept in the lab repository only; a standalone copy of verbatim
# (e.g. the public repo) points VERBATIM_LAB at a lab checkout or skips them.
LAB = Path(os.environ.get("VERBATIM_LAB") or Path(__file__).resolve().parents[3])
E001 = LAB / "experiments" / "E001-claude-outage-2026-09-29"
E002 = LAB / "experiments" / "E002-blind-recheck-e001"
HAVE_LAB = (E001 / "raw" / "FETCH.json").exists()
needs_lab = pytest.mark.skipif(not HAVE_LAB, reason="needs lab snapshots (set VERBATIM_LAB)")
FETCH = json.loads((E001 / "raw" / "FETCH.json").read_text())["sources"] if HAVE_LAB else {}
URL = {k: v["url"] for k, v in FETCH.items()}


@pytest.fixture(scope="module")
def store(tmp_path_factory) -> Store:
    s = Store(tmp_path_factory.mktemp("store"))
    for src in FETCH.values():
        s.add(src["url"], (E001 / "raw" / src["file"]).read_bytes(), content_type=src["content_type"],
              fetched_at=src["date"])
    return s


FILLER = "<p>" + "Unrelated filler text on the same page. " * 8 + "</p>"  # pages need EMPTY_PAGE_CHARS of text
ARTICLE = FILLER * 5  # and THIN_PAGE_CHARS to be more than a teaser


def verdicts(store: Store, quote: str, *urls: str) -> dict:
    return check_claims([{"id": "t", "line": 1, "quote": quote, "urls": list(urls)}], store)[0]


# --- regression on E001/E002 ----------------------------------------------------------------------


@needs_lab
def test_store_keeps_fetch_hashes(store):
    for src in FETCH.values():
        assert store.latest(src["url"])["sha256"] == src["sha256"]


@needs_lab
def test_every_quote_e002_located_is_found(store):
    """E002 located 88 of 90 quotes; its 2 misses were its own text layer gluing spaces at inline tags."""
    located = json.loads((E002 / "locate.json").read_text())
    claims = [{"id": c["id"], "line": None, "quote": c["quote"], "urls": [URL[c["source"]]]}
              for c in located if c.get("quote")]
    results = check_claims(claims, store)
    assert len(results) == 90
    bad = [(r["id"], r["verdict"]) for r in results if r["verdict"] not in ("FOUND", "FOUND_NORMALIZED")]
    assert bad == []
    previously_missed = {r["id"]: r["verdict"] for r in results if r["id"] in ("B:S3:12", "B:S4:10")}
    assert previously_missed == {"B:S3:12": "FOUND", "B:S4:10": "FOUND"}


def test_inline_tags_do_not_split_words():
    page = b"<html><body><p>outages on <a href='x'>September 22</a>, <em>September</em> 15.</p></body></html>"
    assert "outages on September 22, September 15." in layers(page, "text/html")["visible"]


@needs_lab
def test_wrong_number_is_not_found_with_close_match(store):
    # the status page says 14:59; a misquote with 14:58 must not pass, and must point at the real sentence
    r = verdicts(store, "all services have been operating normally since 14:58 UTC", URL["S7"])
    assert r["verdict"] == "NOT_FOUND"
    assert r["closest"]["ratio"] > 0.9
    assert "14:59" in r["closest"]["text"]


@needs_lab
def test_invented_sentence_is_not_found(store):
    r = verdicts(store, "Anthropic confirmed that no customer data was lost during the outage", URL["S7"])
    assert r["verdict"] == "NOT_FOUND"
    assert r["closest"]["ratio"] < 0.8


@needs_lab
def test_quote_from_another_source_is_not_found_in_cited_one(store):
    # true sentence from 9to5Google, attributed to Android Authority
    assert verdicts(store, "The errors that began at 14:00 UTC were mitigated at 14:36 UTC", URL["S3"])["verdict"] == "FOUND"
    assert verdicts(store, "The errors that began at 14:00 UTC were mitigated at 14:36 UTC", URL["S4"])["verdict"] == "NOT_FOUND"


@needs_lab
def test_best_of_several_cited_sources(store):
    r = verdicts(store, "The errors that began at 14:00 UTC were mitigated at 14:36 UTC", URL["S4"], URL["S3"])
    assert r["verdict"] == "FOUND" and r["url"] == URL["S3"]


@needs_lab
def test_elided_quote(store):
    r = verdicts(store, "The errors that began at 14:00 UTC … existing conversations are mostly working again",
                 URL["S3"])
    assert r["verdict"] == "FOUND_NORMALIZED" and r["note"] == "elided"


@needs_lab
def test_curly_quotes_and_case_are_normalized(store):
    r = verdicts(store, "anthropic warns users not to sign out of their accounts until it’s resolved", URL["S4"])
    assert r["verdict"] == "FOUND_NORMALIZED"


@needs_lab
def test_unavailable_and_no_source(store):
    assert verdicts(store, "anything at all here", "https://example.invalid/x")["verdict"] == "SOURCE_UNAVAILABLE"
    assert verdicts(store, "anything at all here")["verdict"] == "NO_SOURCE"


def test_failed_fetch_is_recorded(tmp_path):
    s = Store(tmp_path)
    s.record("https://example.org/gone", {"sha256": None, "http_status": 404, "error": "HTTP 404"})
    r = check_claims([{"id": "t", "line": 1, "quote": "something long enough", "urls": ["https://example.org/gone"]}], s)[0]
    assert r["verdict"] == "SOURCE_UNAVAILABLE" and r["error"] == "HTTP 404"


def test_loose_keeps_a_map_to_the_original():
    text = "Hello ,  “World” — again"
    folded, where = loose(text)
    assert folded == 'hello, world - again'
    assert len(folded) == len(where) and text[where[folded.index("w")]] == "W"


# --- Markdown extraction --------------------------------------------------------------------------


def test_markdown_pairs_quotes_with_links_in_the_same_block():
    md = """# Report

The status page said “Most services have recovered as of 14:59 UTC” ([status](https://status.example/i/1)).

- AI Weekly wrote "partial mitigation at 14:41 UTC" [^aw]
- Unsourced: «this sentence has no link at all»
- Short "term" is skipped

> A blockquote that cites nothing inline but follows a linked paragraph.

```
"code is never a quote, even if long"
```

[^aw]: AI Weekly, https://aiweekly.example/a
"""
    claims, skipped = from_markdown(md)
    got = [(c["line"], c["quote"], c["urls"]) for c in claims]
    assert got == [
        (3, "Most services have recovered as of 14:59 UTC", ["https://status.example/i/1"]),
        (5, "partial mitigation at 14:41 UTC", ["https://aiweekly.example/a"]),
        (6, "this sentence has no link at all", []),
        (9, "A blockquote that cites nothing inline but follows a linked paragraph.", []),
    ]
    assert skipped == 1


def test_markdown_blockquote_inherits_previous_links_and_link_titles_are_not_quotes():
    md = 'Per [the page](https://a.example/p "Some long link title here"):\n\n> quoted passage that is long enough\n'
    claims, _ = from_markdown(md)
    assert [(c["quote"], c["urls"]) for c in claims] == [("quoted passage that is long enough", ["https://a.example/p"])]


# --- CLI end to end -------------------------------------------------------------------------------


@needs_lab
def test_cli_check_exit_codes_and_json(store, tmp_path, capsys):
    good = tmp_path / "good.md"
    good.write_text(f'AI Weekly: "partial mitigation at 14:41 UTC" ({URL["S7"]}).\n')
    bad = tmp_path / "bad.md"
    bad.write_text(f'AI Weekly: "partial mitigation at 14:44 UTC" ({URL["S7"]}).\n')
    out = tmp_path / "v.json"
    assert main(["check", str(good), "--store", str(store.root)]) == 0
    assert main(["check", str(bad), "--store", str(store.root), "--json", str(out)]) == 1
    doc = json.loads(out.read_text())
    assert doc["summary"] == {"NOT_FOUND": 1}
    assert doc["claims"][0]["sha256"] == FETCH["S7"]["sha256"]
    assert "closest" in capsys.readouterr().out


@needs_lab
def test_cli_text_grep(store, capsys):
    assert main(["text", URL["S7"], "--store", str(store.root), "--grep", r"14:2\d UTC"]) == 0
    assert "14:21 UTC" in capsys.readouterr().out


def test_text_fragment_links_with_spaces_are_links_not_quotes():
    md = ('The sutra asks *“How should one proceed on the path?”* '
          '([Diamond Sutra](https://en.wikipedia.org/wiki/Diamond_Sutra#:~:text=“All living beings%2C whether born,”)).\n')
    claims, _ = from_markdown(md)
    assert [(c["quote"], c["urls"]) for c in claims] == [
        ("How should one proceed on the path?",
         ["https://en.wikipedia.org/wiki/Diamond_Sutra#:~:text=“All living beings%2C whether born,”"])]


def test_curly_quote_may_span_lines_in_a_blockquote():
    md = "Per [the page](https://a.example/p):\n\n> “All conditioned phenomena\n> are like a dream.” (ch. 32)\n"
    claims, _ = from_markdown(md)
    assert [(c["quote"], c["urls"]) for c in claims] == [
        ("All conditioned phenomena\nare like a dream.", ["https://a.example/p"])]


def test_gzip_body_is_decompressed():
    import gzip
    page = gzip.compress(b"<html><body><p>The quick brown fox jumps.</p></body></html>")
    assert layers(page, "text/html")["visible"] == "The quick brown fox jumps."


def test_nested_quotation_marks_are_ignored(tmp_path):
    s = Store(tmp_path)
    s.add("https://a.example/p", ("<p>red light penetrates the dermis, where it’s “absorbed by porphyrins” in cells</p>"
                                  + FILLER).encode())
    r = check_claims([{"id": "t", "line": 1, "urls": ["https://a.example/p"],
                       "quote": "penetrates the dermis, where it’s absorbed by porphyrins in cells"}], s)[0]
    assert r["verdict"] == "FOUND_NORMALIZED"


def test_cookie_gate_is_unavailable_not_a_miss(tmp_path):
    s = Store(tmp_path)
    s.add("https://pubmed.example/1", b"<html><body><h1>Cookies must be enabled</h1><p>Enable cookies and reload.</p></body></html>")
    r = check_claims([{"id": "t", "line": 1, "quote": "a finding that the abstract states", "urls": ["https://pubmed.example/1"]}], s)[0]
    assert r["verdict"] == "SOURCE_UNAVAILABLE" and "gate page" in r["error"]


# --- E004: misquotes in published deep-research reports ------------------------------------------

E004 = LAB / "experiments" / "E004-deep-research-quotes"


@needs_lab
def test_e004_showcase_misquotes_are_caught():
    import shutil
    store = Store(E004 / "raw" / "store")
    for c in json.loads((E004 / "showcase.json").read_text())["claims"]:
        cited = check_claims([{"id": c["claim"], "line": c["line"], "quote": c["quote"], "urls": [c["cited"]]}], store)[0]
        assert cited["verdict"] == "NOT_FOUND", (c["system"], c["task"], c["claim"])
        for url in c["also_found_in"]:
            if url.endswith(".pdf") and not shutil.which("pdftotext"):
                continue
            other = check_claims([{"id": "x", "line": 1, "quote": c["quote"], "urls": [url]}], store)[0]
            assert other["verdict"] in ("FOUND", "FOUND_NORMALIZED"), (c["claim"], url)


# --- v0.2: fewer false alarms ---------------------------------------------------------------------

LONG = "<p>" + " ".join(["The committee met again on Tuesday and reviewed the long list of open questions."] * 50) + "</p>"


def _page(tmp_path, body: str, url="https://a.example/p") -> Store:
    s = Store(tmp_path)
    s.add(url, f"<html><body>{body}{LONG}</body></html>".encode())
    return s


def test_square_bracket_edit_is_found_normalized(tmp_path):
    s = _page(tmp_path, "<p>Brands are often leading to a homogenized landscape where designs look alike.</p>")
    r = check_claims([{"id": "t", "line": 1, "urls": ["https://a.example/p"],
                       "quote": "often [led] to a homogenized landscape where designs look alike"}], s)[0]
    assert r["verdict"] == "FOUND_NORMALIZED" and r["note"] == "bracketed"


def test_unattributed_miss_is_uncertain(tmp_path):
    s = _page(tmp_path, "<p>Airports are judged by passengers.</p>")
    md = ('There are underused airports (the infamous “build it and they didn’t come” cases) [p](https://a.example/p).\n\n'
          'The director said “we built it and they never came at all” [p](https://a.example/p).\n')
    claims, _ = from_markdown(md)
    r1, r2 = check_claims(claims, s)
    assert (r1["verdict"], r1["doubts"]) == ("UNCERTAIN", ["unattributed"])
    assert r2["verdict"] == "NOT_FOUND"


def test_thin_page_and_other_language_make_a_miss_uncertain(tmp_path):
    s = Store(tmp_path)
    s.add("https://thin.example/", ("<html><body><p>Subscribe to read the full story.</p>" + FILLER
                                    + "</body></html>").encode())
    s.add("https://es.example/", ("<html><body><p>" + "El compromiso era construir un Macondo cercano a la realidad. " * 80
                                  + "</p></body></html>").encode())
    r1, r2 = check_claims([
        {"id": "a", "line": 1, "quote": "the full story says something else entirely", "urls": ["https://thin.example/"]},
        {"id": "b", "line": 2, "quote": "The commitment was to build a Macondo close to reality", "urls": ["https://es.example/"]},
    ], s)
    assert (r1["verdict"], r1["doubts"]) == ("UNCERTAIN", ["thin_page"])
    assert (r2["verdict"], r2["doubts"]) == ("UNCERTAIN", ["other_language"])


@needs_lab
def test_cli_strict_exit_code(store, tmp_path):
    md = tmp_path / "u.md"
    md.write_text(f'Think of it as “a production studio in the palm of your hand” for everyone. Source: {URL["S7"]}\n')
    assert main(["check", str(md), "--store", str(store.root)]) == 0
    assert main(["check", str(md), "--store", str(store.root), "--strict"]) == 1


# --- E005: defects found by the blind re-label ---------------------------------------------------


def test_url_keeps_balanced_parentheses():
    md = ('Variety called it “an ambitious adaptation of the novel” '
          '([Wikipedia](https://en.wikipedia.org/wiki/One_Hundred_Years_of_Solitude_(TV_series))); '
          'see also https://en.wikipedia.org/wiki/Macondo_(place).\n')
    claims, _ = from_markdown(md)
    assert claims[0]["urls"] == ["https://en.wikipedia.org/wiki/One_Hundred_Years_of_Solitude_(TV_series)"]
    assert claims[0]["block_urls"][1] == "https://en.wikipedia.org/wiki/Macondo_(place)"


def test_quote_is_bound_to_its_own_link_not_the_whole_paragraph():
    md = ('Buffett wrote “Price is what you pay; value is what you get” ([Nasdaq](https://nasdaq.example/a)). '
          'In 1996 he said “Inactivity strikes us as intelligent behavior” ([1996 letter](https://brk.example/1996)). '
          'He also said “Our favorite holding period is forever”. '
          'As the [1989 letter](https://brk.example/1989) put it, “Time is the friend of the wonderful business”.[^7][^8]\n\n'
          '[^7]: https://brk.example/n7\n[^8]: https://brk.example/n8\n')
    claims, _ = from_markdown(md)
    got = [(c["quote"][:12], c["urls"], c.get("binding")) for c in claims]
    assert got == [
        ("Price is wha", ["https://nasdaq.example/a"], "next"),
        ("Inactivity s", ["https://brk.example/1996"], "next"),
        ("Our favorite", ["https://nasdaq.example/a", "https://brk.example/1996", "https://brk.example/1989",
                          "https://brk.example/n7", "https://brk.example/n8"], None),
        ("Time is the ", ["https://brk.example/n7", "https://brk.example/n8"], "next"),
    ]
    assert len(claims[0]["block_urls"]) == 5


def test_quote_without_a_following_link_takes_the_previous_one_in_its_sentence():
    md = 'As the [1989 letter](https://brk.example/1989) put it, “Time is the friend of the wonderful business”.\n'
    claims, _ = from_markdown(md)
    assert claims[0]["urls"] == ["https://brk.example/1989"] and "block_urls" not in claims[0]


def test_unreadable_own_link_is_unavailable_even_if_a_neighbour_is_readable(tmp_path):
    s = Store(tmp_path)
    s.record("https://nasdaq.example/a", {"sha256": None, "fetched_at": "t", "http_status": 403, "content_type": None,
                                         "final_url": "https://nasdaq.example/a", "error": "HTTP 403"})
    s.add("https://imdb.example/t", b"<html><body><div id=app></div></body></html>")
    s.add("https://brk.example/1996", ("<p>Inactivity strikes us as intelligent behavior.</p>" + ARTICLE).encode())
    neighbours = ["https://nasdaq.example/a", "https://imdb.example/t", "https://brk.example/1996"]
    r1, r2, r3 = check_claims([
        {"id": "a", "line": 1, "quote": "Price is what you pay; value is what you get",
         "urls": ["https://nasdaq.example/a"], "block_urls": neighbours},
        {"id": "b", "line": 1, "quote": "a line the empty app shell cannot show", "urls": ["https://imdb.example/t"],
         "block_urls": neighbours},
        {"id": "c", "line": 1, "quote": "Inactivity strikes us as intelligent behavior",
         "urls": ["https://nasdaq.example/a"], "block_urls": neighbours},
    ], s)
    assert r1["verdict"] == "SOURCE_UNAVAILABLE" and r1["error"] == "HTTP 403"
    assert r2["verdict"] == "SOURCE_UNAVAILABLE" and "no text" in r2["error"]
    # found only in a neighbour: the own link could not be read, so this is not a find either
    assert (r3["verdict"], r3["doubts"], r3["found_in"]) == ("SOURCE_UNAVAILABLE", ["other_link"],
                                                             "https://brk.example/1996")


def test_found_only_in_another_link_of_the_paragraph_is_uncertain(tmp_path):
    s = Store(tmp_path)
    s.add("https://brk.example/1996", ("<p>Something else entirely.</p>" + ARTICLE).encode())
    s.add("https://brk.example/2008", ("<p>Price is what you pay; value is what you get.</p>" + ARTICLE).encode())
    r = check_claims([{"id": "a", "line": 1, "quote": "Price is what you pay; value is what you get",
                       "urls": ["https://brk.example/1996"],
                       "block_urls": ["https://brk.example/1996", "https://brk.example/2008"]}], s)[0]
    assert (r["verdict"], r["doubts"], r["found_in"]) == ("UNCERTAIN", ["other_link"], "https://brk.example/2008")


def test_miss_with_an_unread_own_link_is_uncertain(tmp_path):
    s = Store(tmp_path)
    s.add("https://a.example/p", ("<p>Something else entirely.</p>" + ARTICLE).encode())
    r = check_claims([{"id": "a", "line": 1, "quote": "words that may be on the other page",
                       "urls": ["https://a.example/p", "https://never.example/fetched"]}], s)[0]
    assert (r["verdict"], r["doubts"]) == ("UNCERTAIN", ["unread_link"])


@pytest.mark.parametrize("codec", ["gzip", "deflate", "brotli"])
def test_compressed_body_without_content_encoding_is_decoded(codec):
    import gzip
    import zlib
    page = b"<html><body><p>Our favorite holding period is forever.</p></body></html>"
    if codec == "brotli":
        brotli = pytest.importorskip("brotli")
        body = brotli.compress(page)
    else:
        body = gzip.compress(page) if codec == "gzip" else zlib.compress(page)
    assert "holding period is forever" in layers(body, "text/html")["visible"]


def test_binary_body_is_unreadable_not_text():
    from verbatim.textlayer import Unreadable
    with pytest.raises(Unreadable):
        layers(bytes(range(256)) * 20, "text/html")


# --- E006: defects found on the second blind sample ----------------------------------------------


def test_empty_citation_parens_mean_no_source_not_the_neighbour():
    md = ('One objective is to **“Extend U.S. space situational awareness capabilities into cislunar space.”** () '
          'It notes that SSA is “essential to safe and successful spacecraft operations in all orbits” (), '
          'and more ([tag page](https://news.example/tag/cislunar)).\n')
    claims, _ = from_markdown(md)
    assert [(c["urls"], c.get("binding")) for c in claims] == [([], "empty_cite"), ([], "empty_cite")]
    assert check_claims(claims, Store("/nonexistent"))[0]["verdict"] == "NO_SOURCE"


def test_article_redirected_to_home_page_is_unavailable(tmp_path):
    s = Store(tmp_path)
    s.add("https://blog.example/how-singapore-solved-housing/", ("<p>Welcome to my blog.</p>" + ARTICLE).encode(),
          final_url="https://blog.example/")
    r = verdicts(s, "HDB was able to efficiently build over 54,000 flats", "https://blog.example/how-singapore-solved-housing/")
    assert r["verdict"] == "SOURCE_UNAVAILABLE" and "home page" in r["error"]


def test_single_quotes_inside_a_quote_match_double_ones_but_apostrophes_stay(tmp_path):
    s = Store(tmp_path)
    s.add("https://a.example/p", ("<p>a ubiquitous figure in the New Iranian Cinema: the “boy-girl” of films, "
                                  "and it’s here</p>" + ARTICLE).encode())
    assert verdicts(s, "a ubiquitous figure in the New Iranian Cinema: the 'boy-girl' of films",
                    "https://a.example/p")["verdict"] == "FOUND_NORMALIZED"
    assert verdicts(s, "the boy-girl of films, and its here", "https://a.example/p")["verdict"] != "FOUND_NORMALIZED"


def test_inch_marks_are_not_quotes():
    md = 'The Flex 2 has a 5.0" IPS HD display, while the Flex 3 has a larger 5.99" display [^1].\n\n[^1]: https://a.example/spec\n'
    assert from_markdown(md)[0] == []


@pytest.mark.parametrize("text", [
    "Rana thinks it “certainly something no family should ever accept” ([Facing Mirrors](https://w.example/fm)).",
    "*“Machines can never truly empathize with a human being”* Turkle reminds us, in her essay https://a.example/t",
    "Tablets replace registers (“the modern cash register built for every business” as Elo’s marketing says) https://e.example",
    "They found that AI adoption in metro areas **“increases hiring of AI-skilled workers”** https://a.example/s",
])
def test_attribution_after_the_quote_or_by_its_citation(text):
    claims, _ = from_markdown(text + "\n")
    assert claims[0]["attributed"] is True

# --- access cascade (E007): offline, the network methods are replaced by fakes ------------------------------

from verbatim import access as acc  # noqa: E402

QUOTE = "a production studio in the palm of your hand"
WITH_QUOTE = f"<html><body>{ARTICLE}<p>“You’ve got {QUOTE},” Gahan said.</p>{ARTICLE}</body></html>".encode()
WITHOUT = f"<html><body>{ARTICLE}</body></html>".encode()


def fake(method, body, calls=None, **meta):
    def run(store, url, **_):
        if calls is not None:
            calls.append((method, url))
        if body is None:
            return None
        return store.add(url, body, content_type="text/html", via=f"{method} fake", provenance=acc.PROVENANCE[method],
                         **meta)
    return run


@pytest.fixture
def blocked(tmp_path, monkeypatch) -> Store:
    s = Store(tmp_path)
    s.record("https://news.example/a", {"sha256": None, "http_status": 403, "error": "HTTP 403", "final_url": ""})
    for m in acc.METHODS:
        monkeypatch.setitem(acc.METHODS, m, fake(m, None))
    return s


def check1(store, quote=QUOTE, **kw):
    return check_claims([{"id": "t", "line": 1, "quote": quote, "urls": ["https://news.example/a"]}], store, **kw)[0]


def test_without_access_a_blocked_page_stays_unavailable(blocked):
    assert check1(blocked)["verdict"] == "SOURCE_UNAVAILABLE"


def test_browser_render_counts_as_the_publisher(blocked, monkeypatch):
    monkeypatch.setitem(acc.METHODS, "browser", fake("browser", WITH_QUOTE))
    r = check1(blocked, access=acc.DEFAULT)
    assert (r["verdict"], r["provenance"], r["via"]) == ("FOUND", "publisher", "browser fake")


def test_cascade_stops_at_the_first_readable_method(blocked, monkeypatch):
    calls = []
    monkeypatch.setitem(acc.METHODS, "browser", fake("browser", b"<p>Just a moment...</p>", calls))
    monkeypatch.setitem(acc.METHODS, "archive", fake("archive", WITH_QUOTE, calls, archived_at="20260313210501"))
    monkeypatch.setitem(acc.METHODS, "open_access", fake("open_access", WITH_QUOTE, calls))
    r = check1(blocked, access=acc.DEFAULT)
    assert [c[0] for c in calls] == ["browser", "archive"]
    assert (r["verdict"], r["provenance"], r["archived_at"]) == ("FOUND", "archive", "20260313210501")


def test_earlier_cascade_result_is_reused(blocked, monkeypatch):
    monkeypatch.setitem(acc.METHODS, "archive", fake("archive", WITH_QUOTE))
    check1(blocked, access=("archive",))
    calls = []
    monkeypatch.setitem(acc.METHODS, "archive", fake("archive", WITH_QUOTE, calls))
    blocked.record("https://news.example/a", {"sha256": None, "http_status": 403, "error": "HTTP 403", "final_url": ""})
    assert check1(blocked, access=("archive",))["provenance"] == "archive" and calls == []


def test_a_copy_is_not_the_cited_page(blocked, monkeypatch):
    monkeypatch.setitem(acc.METHODS, "copy", fake("copy", WITH_QUOTE))
    r = check1(blocked, access=("copy",))
    assert (r["verdict"], r["match"], r["provenance"]) == ("FOUND_IN_COPY", "FOUND", "copy")


def test_a_miss_in_a_copy_is_uncertain(blocked, monkeypatch):
    monkeypatch.setitem(acc.METHODS, "relay", fake("relay", WITHOUT))
    r = check1(blocked, access=("relay",))
    assert r["verdict"] == "UNCERTAIN" and "copy_only" in r["doubts"]


def test_a_miss_in_an_abstract_is_uncertain(blocked, monkeypatch):
    monkeypatch.setitem(acc.METHODS, "open_access", fake("open_access", WITHOUT, abstract_only=True))
    r = check1(blocked, access=("open_access",))
    assert r["verdict"] == "UNCERTAIN" and "abstract_only" in r["doubts"]


def test_all_methods_failing_lists_each_reason(blocked, monkeypatch):
    monkeypatch.setitem(acc.METHODS, "browser", fake("browser", b"<p>Access Denied</p>"))
    r = check1(blocked, access=acc.DEFAULT)
    assert r["verdict"] == "SOURCE_UNAVAILABLE"
    assert r["error"].startswith("direct: HTTP 403; browser: gate page")


def test_relay_is_opt_in():
    assert "relay" not in acc.DEFAULT and "relay" in acc.parse("all")
    assert acc.parse("browser,archive") == ("browser", "archive")
    with pytest.raises(ValueError):
        acc.parse("bypass")


def test_surt_and_doi():
    assert acc.surt("https://www.bcg.com/news/23april2024-bcgs-leap-ai") == "com,bcg)/news/23april2024-bcgs-leap-ai"
    assert acc.DOI.search("https://onlinelibrary.wiley.com/doi/10.1111/1467-8675.12678").group(1) == "10.1111/1467-8675.12678"
    assert acc.DOI.search("https://www.nasdaq.com/articles/x") is None


@needs_lab
def test_missing_space_after_a_sentence_in_rendered_dom(tmp_path):
    """E007, futunn: block elements joined without a space ("similar.Just like")."""
    s = Store(tmp_path)
    s.add("https://f.example", f"<p>{ARTICLE}They look very similar.Just like in Macau, casinos win.</p>".encode(),
          content_type="text/html")
    r = check_claims([{"id": "t", "line": 1, "quote": "they look very similar. Just like in Macau",
                       "urls": ["https://f.example"]}], s)[0]
    assert r["verdict"] == "FOUND_NORMALIZED"


@needs_lab
def test_second_look_when_the_read_page_lacks_the_quote(tmp_path, monkeypatch):
    """A paywalled page reads fine but holds only the teaser (E007: Washington Post); its republished copy has it."""
    s = Store(tmp_path)
    s.add("https://news.example/a", WITHOUT, content_type="text/html")
    for m in acc.METHODS:
        monkeypatch.setitem(acc.METHODS, m, fake(m, None))
    assert check1(s)["verdict"] == "NOT_FOUND"
    monkeypatch.setitem(acc.METHODS, "copy", fake("copy", WITH_QUOTE))
    r = check1(s, access=acc.DEFAULT)
    assert (r["verdict"], r["first_read"], r["provenance"]) == ("FOUND_IN_COPY", "NOT_FOUND", "copy")


def test_second_look_keeps_the_miss_when_no_alternative_has_it(tmp_path, monkeypatch):
    s = Store(tmp_path)
    s.add("https://news.example/a", WITHOUT, content_type="text/html")
    for m in acc.METHODS:
        monkeypatch.setitem(acc.METHODS, m, fake(m, WITHOUT))
    r = check1(s, access=acc.DEFAULT)
    assert r["verdict"] == "NOT_FOUND" and r["provenance"] == "publisher" and "first_read" not in r


# --- deferring a slow method to GitHub Actions: check --defer, access, merge ---------------------------------

def test_deferred_archive_is_listed_then_reused(blocked, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setitem(acc.METHODS, "archive", fake("archive", WITH_QUOTE, calls, archived_at="20250101000000"))
    deferred = set()
    r = check1(blocked, access=acc.DEFAULT, defer=("archive",), deferred=deferred)
    assert r["verdict"] == "SOURCE_UNAVAILABLE" and calls == [] and deferred == {"https://news.example/a"}
    elsewhere = Store(tmp_path / "actions")  # what the workflow does with `verbatim access archive`
    acc.METHODS["archive"](elsewhere, "https://news.example/a")
    assert main(["merge", str(tmp_path / "actions"), "--store", str(blocked.root)]) == 0
    calls.clear()
    deferred = set()
    r = check1(blocked, access=acc.DEFAULT, defer=("archive",), deferred=deferred)
    assert (r["verdict"], r["provenance"]) == ("FOUND", "archive") and calls == [] and deferred == set()


def test_merge_twice_adds_nothing(tmp_path):
    a, b = Store(tmp_path / "a"), Store(tmp_path / "b")
    b.add("https://x.example", b"<p>hello</p>", content_type="text/html")
    assert main(["merge", str(b.root), "--store", str(a.root)]) == 0
    assert main(["merge", str(b.root), "--store", str(a.root)]) == 0
    assert len(a.index()["https://x.example"]) == 1 and a.resolve("https://x.example")[1] == b"<p>hello</p>"


def test_access_cli_reads_deferred_urls(blocked, monkeypatch, tmp_path, capsys):
    monkeypatch.setitem(acc.METHODS, "archive", fake("archive", WITH_QUOTE))
    j = tmp_path / "v.json"
    j.write_text(json.dumps({"deferred": {"methods": ["archive"], "urls": ["https://news.example/a"]}}))
    assert main(["access", "archive", "--from", str(j), "--store", str(blocked.root)]) == 0
    assert "1/1 URLs read" in capsys.readouterr().out
    assert blocked.latest("https://news.example/a")["provenance"] == "archive"


def test_unreachable_wayback_and_cc_index_are_given_up_after_three_failures(monkeypatch, tmp_path):
    asked = []

    def down(url, *a, **k):
        asked.append(url.split("/")[2])
        raise OSError("Connection reset by peer")
    monkeypatch.setattr(acc, "_down", set())
    monkeypatch.setattr(acc, "_fails", {})
    monkeypatch.setattr(acc, "_get", down)
    monkeypatch.setattr(acc, "_crawls", lambda: ["CC-MAIN-2026-39"])
    monkeypatch.setattr(acc, "cc_lookup", lambda url, crawl: [])
    s = Store(tmp_path)
    for n in range(5):
        assert acc.archive(s, f"https://a.example/{n}")["sha256"] is None
    assert asked.count("archive.org") == 3 and asked.count("index.commoncrawl.org") == 3


@needs_lab
def test_one_reset_does_not_stop_wayback(monkeypatch, tmp_path):
    """Actions run 1 (E008): a single reset under load switched Wayback off for the remaining URLs."""
    calls = []

    def flaky(url, *a, **k):
        calls.append(url)
        if len(calls) == 1:
            raise OSError("Connection reset by peer")
        if "wayback/available" in url:
            return 200, {}, json.dumps({"archived_snapshots": {"closest": {"timestamp": "20250101000000"}}}).encode(), url
        return 200, {"content-type": "text/html"}, WITH_QUOTE, url
    monkeypatch.setattr(acc, "_down", set())
    monkeypatch.setattr(acc, "_fails", {})
    monkeypatch.setattr(acc, "_get", flaky)
    monkeypatch.setattr(acc, "_crawls", lambda: [])
    s = Store(tmp_path)
    acc.archive(s, "https://a.example/1")
    assert acc.archive(s, "https://a.example/2")["via"].startswith("archive web.archive.org")


def test_access_jobs_keep_every_index_entry(monkeypatch, tmp_path):
    monkeypatch.setitem(acc.METHODS, "archive", fake("archive", WITH_QUOTE))
    urls = [f"https://n.example/{i}" for i in range(40)]
    assert main(["access", "archive", *urls, "--jobs", "8", "--store", str(tmp_path)]) == 0
    assert len(Store(tmp_path).index()) == 40


def test_cc_index_hit_is_read_without_bisect(monkeypatch, tmp_path):
    hit = {"url": "https://a.example/1", "timestamp": "20260901000000", "status": "200", "filename": "f.warc.gz",
           "offset": "10", "length": "5"}
    monkeypatch.setattr(acc, "_down", {"wayback"})
    monkeypatch.setattr(acc, "_get", lambda url, *a, **k: (200, {}, (json.dumps(hit) + "\n").encode(), url))
    monkeypatch.setattr(acc, "_crawls", lambda: ["CC-MAIN-2026-39"])
    monkeypatch.setattr(acc, "cc_lookup", lambda url, crawl: pytest.fail("bisect used although the index answered"))
    monkeypatch.setattr(acc, "cc_record", lambda h: (200, "text/html", WITH_QUOTE))
    e = acc.archive(Store(tmp_path), "https://a.example/1")
    assert e["provenance"] == "archive" and e["archived_at"] == "20260901000000"


# --- E008: not a quote, punctuation between words -------------------------------------------------------------------

@pytest.mark.parametrize("md, kind", [
    ("> (Note: This document may contain AI-generated content.)\n", "boilerplate"),
    ("- IEEE P7131 – “Standard for Quantum Computing Performance Metrics and Benchmarking.” Specifies metrics [x](https://a.example/p)\n", "title"),
    ("- Xu, J., et al. “Cry4 in light-dependent magnetic compass of birds.” Current Biology 28(13), 2018 [x](https://a.example/p)\n", "title"),
    ("Her work, particularly her 2009 article “the politics of gender and witnessing in postwar Bosnia,” matters [x](https://a.example/p).\n", "title"),
    ("For example, a teacher might gently review: “You thought there was a real fire and were very scared.” [x](https://a.example/p)\n", "example"),
    ("These are rules never taught (e.g. “Don’t interrupt a teacher when they look busy”) [x](https://a.example/p).\n", "example"),
    ("A fuzzy rule “if load is high then scale out more servers” replaces cutoffs. More [x](https://a.example/p).\n", "example"),
    ("Here the guiding question is “How does anime as animation work in practice?” and so on [x](https://a.example/p).\n", "example"),
    ("The logic is akin to the adage “don’t count your chickens before they hatch” [x](https://a.example/p).\n", "example"),
    # E010 hints (0.3.1)
    ("In sum, firms define KPIs like “X% reduction in review time” or less [x](https://a.example/p).\n", "example"),
    ("In concrete numbers, we may forecast something like: “Cohort 2025 retains 85% of its revenue after one year” [x](https://a.example/p).\n", "example"),
    ("For instance, criteria might include: _“Does the startup’s solution fill a gap in our product portfolio?”_ [x](https://a.example/p)\n", "example"),
    ("The AI can take complex questions (“What are the risks of this bond issuance for us?”) and answer [x](https://a.example/p).\n", "example"),
])
def test_not_a_quote_kinds(md, kind):
    claims, _ = from_markdown(md)
    assert [c.get("not_quote") for c in claims] == [kind]


def test_a_quote_listed_after_an_example_is_an_example_too():
    md = ("Firms define KPIs like “X% reduction in review time” or “Y minutes to first relevant hit.” Then "
          "the director said “we built it and they never came at all” [x](https://a.example/p).\n")
    assert [c.get("not_quote") for c in from_markdown(md)[0]] == ["example", "example", None]


@pytest.mark.parametrize("md", [
    "For example, the WHO states “countries must invest in primary health care first” [x](https://a.example/p).\n",
    "As Williams would often say, “The blues was really important – this is your healing” [x](https://a.example/p).\n",
    "When Rachel demands children, Jacob exclaims, “Am I in the place of God, who has withheld from you?” [x](https://a.example/p).\n",
    "The director said “we built it and they never came at all” [p](https://a.example/p).\n",
    "It looks like “the market will keep growing for many more years” [p](https://a.example/p).\n",
    "Nitro’s popular features (“animated emoji, higher game streaming and server boosts”) drive it [p](https://a.example/p).\n",
    # a standard that speaks is the speaker, not a title (NEXT №37: a wrong quote of RFC 9110 passed the hook)
    "RFC 9110 says HTTP is “a stateful application-level protocol for distributed systems” ([RFC](https://a.example/p)).\n",
])
def test_quotes_with_a_speaker_stay_quotes(md):
    claims, _ = from_markdown(md)
    assert [c.get("not_quote") for c in claims] == [None]


def test_not_a_quote_is_its_own_verdict_only_when_missing(tmp_path):
    s = _page(tmp_path, "<p>IEEE P1913 Standard for Software-Defined Quantum Communication defines a YANG model.</p>")
    md = ("- IEEE P1913 – “Standard for Software-Defined Quantum Communication.” Defines a model [x](https://a.example/p)\n\n"
          "- IEEE P3172 – “Recommended Practice for Post-Quantum Cryptography Migration.” Steps [x](https://a.example/p)\n")
    found, missing = check_claims(from_markdown(md)[0], s)
    assert found["verdict"] in ("FOUND", "FOUND_NORMALIZED")
    assert (missing["verdict"], missing["not_quote"], missing["miss"]) == ("NOT_A_QUOTE", "title", "NOT_FOUND")


@pytest.mark.parametrize("page, quote", [
    ("The blues was really important—this is your healing and love in the music.",
     "The blues was really important – this is your healing and love in the music"),
    ("they no longer have heroes -- like Babe Ruth, she said.", "no longer have heroes – like Babe Ruth"),
    ("I took him back to Fats Waller. I had him swinging the left hand. He can play anything.",
     "I took him back to Fats Waller – I had him swinging the left hand"),
    ("they think they’re so far out until they’re greater than the other cats but they’re not.",
     "they’re so far out…they’re greater than the other cats – but they’re not,"),
    ("formulas such as he knew his wife and she conceived and bore a son (Gen 4:1)",
     "he knew his wife, and she conceived and bore [a son]"),
])
def test_punctuation_between_words_is_normalized(tmp_path, page, quote):
    s = _page(tmp_path, f"<p>{page}</p>")
    r = check_claims([{"id": "t", "line": 1, "urls": ["https://a.example/p"], "quote": quote}], s)[0]
    assert r["verdict"] == "FOUND_NORMALIZED", r


@pytest.mark.parametrize("quote", ["no longer have heroes like Lou Gehrig", "up to $300,000 for two years"])
def test_punctuation_normalization_keeps_words_and_numbers(tmp_path, quote):
    s = _page(tmp_path, "<p>they no longer have heroes -- like Babe Ruth. Credits up to $200,000 for two years.</p>")
    r = check_claims([{"id": "t", "line": 1, "urls": ["https://a.example/p"], "quote": quote}], s)[0]
    assert r["verdict"] == "NOT_FOUND"


# --- E011: quotes on the page that search missed (0.3.2) ------------------------------------------------------------

@pytest.mark.parametrize("page, quote, note", [
    # F064: two replies of one speaker, the speech tag between them dropped
    ("“That was very much my vision for capturing these wonderful, unexplainable, sometimes slightly terrifying "
     "moments,” García López continues. “There’s a lot of comedy in the book.”",
     "That was very much my vision for capturing these wonderful, unexplainable, sometimes slightly terrifying "
     "moments. There's a lot of comedy in the book.", "speech_tag"),
    ('"We kept the budget flat for the third year in a row," said Ann Lee, the city treasurer. '
     '"Next year we will have to raise it for schools."',
     "We kept the budget flat for the third year in a row. Next year we will have to raise it for schools.",
     "speech_tag"),
    # F001: the page's own brackets; F031: blanks of another length
    ("“This is an average regional impact….[A]t a nonhub airport, it takes fewer than half the annual departing "
     "seats to “result” in a regional job…” (Ballard et al. 2020)",
     "at a nonhub airport, it takes fewer than half the annual departing seats to 'result' in a regional job.",
     "punctuation"),
    ("they might offer the sentence, ‘If _____ was added, then _____ because _____.’ This sentence frame provides "
     "clues that empower ELLs to sound and think like scientists.",
     "they might offer the sentence, 'If ___ was added, then ___ because _.' This sentence frame provides clues",
     "punctuation"),
])
def test_search_misses_of_e011_are_found(tmp_path, page, quote, note):
    s = _page(tmp_path, f"<p>{page}</p>")
    r = check_claims([{"id": "t", "line": 1, "urls": ["https://a.example/p"], "quote": quote}], s)[0]
    assert (r["verdict"], r.get("note")) == ("FOUND_NORMALIZED", note), r


def test_mojibake_on_the_page_is_repaired(tmp_path):
    # F074: the text layer read U+201C/U+201D as C1 controls (lead byte lost); "â€™" is the cp1252 reading of U+2019
    page = ("\u0080\u009cThe best compliment I can give Rod is that I personally observed him maintain his focus "
            "despite the pressures,\u0080\u009d said Eric Newcomer. \u0080\u009cIt was this dedication that set "
            "him apart.\u0080\u009d Heâ€™d go on.")
    s = Store(tmp_path)
    s.add("https://a.example/p", f"<html><body>{ARTICLE}<p>{page}</p></body></html>".encode("utf-8"),
          content_type="text/html")
    quote = ("The best compliment I can give Rod is that I personally observed him maintain his focus despite the "
             "pressures. It was this dedication that set him apart.")
    r, apostrophe = check_claims([{"id": "t", "line": 1, "urls": ["https://a.example/p"], "quote": q}
                                  for q in (quote, "this dedication that set him apart.” He’d go on")], s)
    assert (r["verdict"], r["note"], r["tag"], r["repaired"]) == ("FOUND_NORMALIZED", "speech_tag",
                                                                    "said Eric Newcomer.", 5)
    assert apostrophe["verdict"] in ("FOUND", "FOUND_NORMALIZED")


@pytest.mark.parametrize("quote", [
    # a word changed in either reply is still a miss
    "We kept the budget flat for the fourth year in a row. Next year we will have to raise it for schools.",
    "We kept the budget flat for the third year in a row. Next year we will have to cut it for schools.",
    # replies that are not next to each other, or not separated by a speech tag
    "We kept the budget flat for the third year in a row. The council approved the plan on Monday night.",
    "Next year we will have to raise it for schools. We kept the budget flat for the third year in a row.",
])
def test_speech_tag_joins_only_adjacent_replies_word_for_word(tmp_path, quote):
    s = _page(tmp_path, '<p>"We kept the budget flat for the third year in a row," said Ann Lee, the city treasurer. '
                        '"Next year we will have to raise it for schools." The council approved the plan on Monday '
                        'night after a long debate about other matters.</p>')
    r = check_claims([{"id": "t", "line": 1, "urls": ["https://a.example/p"], "quote": quote}], s)[0]
    assert r["verdict"] == "NOT_FOUND", r


def test_page_brackets_and_blanks_keep_words(tmp_path):
    s = _page(tmp_path, "<p>[A]t a nonhub airport it takes fewer seats. If _____ was added, then nothing.</p>")
    for quote in ("at a hub airport it takes fewer seats", "If water was added, then nothing"):
        r = check_claims([{"id": "t", "line": 1, "urls": ["https://a.example/p"], "quote": quote}], s)[0]
        assert r["verdict"] == "NOT_FOUND", r


# --- 0.3.3 (E014) ----------------------------------------------------------------------------------


@pytest.mark.parametrize("md,quote", [
    ('He said, "Times New Roman[1](https://t.example/)? More like Times OLD Roman."',
     "Times New Roman? More like Times OLD Roman."),
    ('It is "the earth may be borrowed but not bought.[2][11](https://a.example/) It may be used, but not '
     'owned.[2][11][14](https://b.example/) But we are tenants."[3](https://c.example/)',
     "the earth may be borrowed but not bought. It may be used, but not owned. But we are tenants."),
    ('They "read Chapter 11 and weren\'t impressed[1](https://t.example/). So we moved on."',
     "read Chapter 11 and weren't impressed. So we moved on."),
    ('She wrote "a bare marker[3] stays out of the words" [4](https://d.example/)', "a bare marker stays out of the words"),
])
def test_footnote_markers_inside_a_quote_are_not_its_words(md, quote):
    claims = from_markdown(md)[0]
    assert [c["quote"].replace("  ", " ") for c in claims] == [quote]


def test_editorial_brackets_and_numbers_stay_in_a_quote():
    q = from_markdown('He said "she bore [a son] in 1999 and [AI\'s] rise took 11 years" [1](https://e.example/)')[0][0]
    assert q["quote"] == "she bore [a son] in 1999 and [AI's] rise took 11 years"


def test_footnote_link_inside_a_quote_is_found_on_the_page(tmp_path):
    s = Store(tmp_path)
    url = "https://t.example/"
    s.add(url, f"<p>Webmaster: Times New Roman? More like Times OLD Roman.</p>{ARTICLE}".encode(), content_type="text/html")
    md = f'Delabor is quoted as saying, "Times New Roman[1]({url})? More like Times OLD Roman."'
    assert check_claims(from_markdown(md)[0], s)[0]["verdict"] in ("FOUND", "FOUND_NORMALIZED")


def test_cut_off_body_is_a_failed_fetch_not_a_crash(tmp_path, monkeypatch):
    import http.client
    import urllib.request

    class Cut:
        status, headers = 200, {}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            raise http.client.IncompleteRead(b"<html>half", 5000)

        def geturl(self):
            return "https://cut.example/"

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Cut())
    entry = Store(tmp_path).fetch("https://cut.example/")
    assert entry["sha256"] is None and entry["error"].startswith("incomplete read")
    r = check_claims([{"id": "t", "line": 1, "quote": "something long enough here", "urls": ["https://cut.example/"]}],
                     Store(tmp_path), fetch=False)[0]
    assert r["verdict"] == "SOURCE_UNAVAILABLE"


# --- 0.3.4 (E009 gates, NEXT №42) -----------------------------------------------------------------------------------


@pytest.mark.parametrize("page", [
    # nature.com and Springer: 226 characters, not in the old wall phrases
    "<p>Client Challenge A required part of this site couldn’t load. This may be due to a browser extension, "
    "network issues, or browser settings. Please check your connection, disable any ad blockers.</p>",
    # ScienceDirect's captcha on top of a long page of script text: too long for the old 2000-character limit
    "<p>Just a moment... Help Are you a robot? Please confirm you are a human by completing the captcha.</p>" + ARTICLE * 3,
])
def test_gates_are_unavailable(tmp_path, page):
    s = Store(tmp_path)
    s.add("https://journal.example/articles/x1", page.encode(), content_type="text/html")
    r = verdicts(s, "HDB was able to efficiently build over 54,000 flats", "https://journal.example/articles/x1")
    assert r["verdict"] == "SOURCE_UNAVAILABLE" and "gate page" in r["error"]


def test_article_about_captchas_is_still_read(tmp_path):
    s = Store(tmp_path)
    s.add("https://news.example/robots", ("<p>" + "Some text before the topic. " * 10 + "Sites ask: are you a robot? "
                                          "</p>" + ARTICLE * 2).encode(), content_type="text/html")
    assert verdicts(s, "Unrelated filler text on the same page", "https://news.example/robots")["verdict"] == "FOUND"


def test_app_shell_is_unavailable(tmp_path):
    s = Store(tmp_path)
    shell = ("<html><head>" + "<script>var x = 1;</script>" * 4000 + "</head><body><p>BERKSHIRE HATHAWAY INC Top 13F "
             "Holdings We give you the access and tools to invest like a Wall Street money manager. Key Features "
             "Backtester Combined Holdings Excel Add-in 13F Fund Performance Evaluator Developer API About Us "
             "Getting Started FAQ Contact Us Premium Subscriptions News and Articles Privacy Policy</p></body></html>")
    s.add("https://whale.example/filer/brk", shell.encode(), content_type="text/html")
    r = verdicts(s, "Apple remains the largest holding of the fund", "https://whale.example/filer/brk")
    assert r["verdict"] == "SOURCE_UNAVAILABLE" and "app shell" in r["error"]


@pytest.mark.parametrize("asked, final, why", [
    ("https://www.pif.gov.sa/-/media/pdf/fitch-25-dec-2024.pdf", "https://www.pif.gov.sa/en/", "home page"),
    ("https://www.informit.com/articles/article.aspx?p=31072&seqNum=5", "https://www.informit.com/articles/", "section"),
    ("https://paperswithcode.com/paper/tracknetv2-efficient-shuttlecock-tracking",
     "https://huggingface.co/papers/trending", "another site"),
])
def test_redirects_away_from_the_document_are_unavailable(tmp_path, asked, final, why):
    s = Store(tmp_path)
    s.add(asked, ("<p>Welcome.</p>" + ARTICLE).encode(), content_type="text/html", final_url=final)
    r = verdicts(s, "HDB was able to efficiently build over 54,000 flats", asked)
    assert r["verdict"] == "SOURCE_UNAVAILABLE" and why in r["error"]


@pytest.mark.parametrize("asked, final", [
    ("https://doi.org/10.1016/j.techfore.2016.08.019",
     "https://www.sciencedirect.com/science/article/pii/S0040162516302244"),  # a resolver lands deep
    ("https://doi.org/10.1057/s41599-024-03557-6", "https://www.nature.com/articles/s41599-024-03557-6"),
    ("https://example.com/docs/index.html", "https://example.com/docs/"),
    ("https://example.com/story", "https://example.com/en/story"),
    ("https://example.com/en", "https://example.com/en/"),
])
def test_resolvers_and_equivalent_paths_stay_the_document(tmp_path, asked, final):
    s = Store(tmp_path)
    s.add(asked, ARTICLE.encode(), content_type="text/html", final_url=final)
    assert verdicts(s, "Unrelated filler text on the same page", asked)["verdict"] == "FOUND"


# --- 0.3.5 (E015 gates, NEXT №53) -----------------------------------------------------------------------------------


def test_anubis_check_is_a_gate(tmp_path):
    s = Store(tmp_path)
    s.add("https://gupea.example/handle/2077/70422", (
        "<p>Making sure you're not a bot! Loading... Please wait a moment while we ensure the security of your "
        "connection. Protected by Anubis From Techaro. This website is running Anubis version v1.27.0.</p>").encode(),
        content_type="text/html")
    r = verdicts(s, "HDB was able to efficiently build over 54,000 flats", "https://gupea.example/handle/2077/70422")
    assert r["verdict"] == "SOURCE_UNAVAILABLE" and "gate page" in r["error"]


def test_login_page_is_unavailable(tmp_path):
    # Facebook's video page for a visitor without an account: navigation in the locale's language and a sign-in form
    s = Store(tmp_path)
    page = ('<html><body><form id="login_form"><input type="text" name="email"><input dir="rtl" type="password" '
            'name="pass"></form><p>' + "ویڈیو ہوم Live Reels ایکسپلور کریں " * 40 + "</p></body></html>")
    s.add("https://social.example/county/videos/2496721583791745/", page.encode(), content_type="text/html")
    r = verdicts(s, "HDB was able to efficiently build over 54,000 flats",
                 "https://social.example/county/videos/2496721583791745/")
    assert r["verdict"] == "SOURCE_UNAVAILABLE" and "login page" in r["error"]


def test_article_with_a_sign_in_box_is_still_read(tmp_path):
    s = Store(tmp_path)
    s.add("https://news.example/story", ('<form><input type="password" name="pw"></form><p>' + ARTICLE * 2 + "</p>")
          .encode(), content_type="text/html")
    assert verdicts(s, "Unrelated filler text on the same page", "https://news.example/story")["verdict"] == "FOUND"


def test_encoded_payload_is_unavailable(tmp_path):
    import base64
    blob = base64.b64encode(bytes(range(256)) * 12).decode()
    s = Store(tmp_path)
    s.add("https://journal.example/articles/OJ93", f"<p>Loading</p><p>{blob}</p>".encode(), content_type="text/html")
    r = verdicts(s, "HDB was able to efficiently build over 54,000 flats", "https://journal.example/articles/OJ93")
    assert r["verdict"] == "SOURCE_UNAVAILABLE" and "encoded payload" in r["error"]


def test_prose_without_spaces_is_not_a_payload(tmp_path):
    s = Store(tmp_path)
    prose = "截至2月5日0时，导演饺子的哪吒系列两部电影总票房已超100亿元，哪吒成为影史首位3岁百亿影人相关话题冲上热搜。" * 20
    s.add("https://cn.example/a/1", f"<p>{prose}</p>".encode(), content_type="text/html")
    assert verdicts(s, "导演饺子的哪吒系列两部电影总票房已超100亿元", "https://cn.example/a/1")["verdict"] == "FOUND"


def test_redirect_to_a_local_address_is_unavailable(tmp_path):
    # DSpace links its PDF to the repository's internal host; the browser got the local proxy's error page
    s = Store(tmp_path)
    s.add("https://ir.example.edu.tw/bitstream/11536/5298/1/000277884100024.pdf", ("<p>Proxy error.</p>" + ARTICLE)
          .encode(), content_type="text/html", final_url="http://0.0.0.0:4000/bitstreams/2b22093a/download")
    r = verdicts(s, "HDB was able to efficiently build over 54,000 flats",
                 "https://ir.example.edu.tw/bitstream/11536/5298/1/000277884100024.pdf")
    assert r["verdict"] == "SOURCE_UNAVAILABLE" and "local address" in r["error"]
