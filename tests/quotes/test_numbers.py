"""verbatim.numbers: numbers and dates of a cited sentence against a page (E009)."""
from __future__ import annotations

from verbatim.numbers import check_sentence, content_words, mentions


def texts(sentence: str) -> list[str]:
    return [m.text for m in mentions(sentence)]


def verdicts(sentence: str, page: str) -> dict[str, str]:
    return {r["text"]: r["verdict"] for r in check_sentence(sentence, page)}


def test_mentions_kinds_and_values():
    ms = {m.text: m for m in mentions("Income set a record in 2017 of 3.349 million yen[^3], up 4.4%, "
                                      "reaching ¥115 trillion on April 28, 2025.5")}
    assert ms["2017"].kind == "year"
    assert ms["3.349 million yen"].kind == "money" and ms["3.349 million yen"].value == 3_349_000
    assert ms["4.4%"].kind == "percent" and ms["4.4%"].decimals == 1
    assert ms["¥115 trillion"].value == 115e12
    assert ms["April 28, 2025"].value == (2025, 4, 28)
    assert "3" not in ms and "5" not in ms  # footnote markers are not claims


def test_mentions_skip_small_integers_codes_and_citation_markup():
    assert texts("There are 3 key areas and 12 people.") == []
    assert texts("The CR3BP model and a masculine 2PP.10 Female characters") == []
    assert texts("see [2019 report](https://example.com/2019/report-45) and 【3†L10-L12】") == []
    assert texts("over 5 m deep") == []  # metres, not millions


def test_mentions_ranges_take_the_unit_of_their_end():
    ms = mentions("citing 15-40% savings, lengths around 40-45 cm, $1-2 billion")
    assert [(m.text, m.kind) for m in ms][:2] == [("15", "percent"), ("40%", "percent")]
    assert ms[2].text == "40" and ms[3].text == "45 cm"
    assert ms[4].value == 1e9 and ms[5].value == 2e9


def test_mentions_approx():
    (m,) = mentions("accounting for approximately 29.6% of the population")
    assert m.approx


def test_found_in_other_spellings():
    s = "Income was 3.349 million yen in 2017, growth 4.4%, ¥115 trillion, on April 28, 2025."
    page = ("In 2017 the average annual income was 3,349,000 yen. Growth was 4.38 per cent; "
            "spending reached 115 trillion yen. Published 28 April 2025, average annual income figures.")
    v = verdicts(s, page)
    assert v == {"3.349 million yen": "FOUND_NORMALIZED", "2017": "FOUND", "4.4%": "FOUND_ROUNDED",
                 "¥115 trillion": "FOUND", "April 28, 2025": "FOUND_NORMALIZED"}


def test_not_found_and_no_context():
    s = "Senior households spent 230,000 yen monthly on consumption in 2019."
    page = "Unrelated text. Monthly household consumption by seniors was 241,500 yen." + " filler" * 200 + " 2019"
    v = verdicts(s, page)
    assert v["230,000 yen"] == "NOT_FOUND"
    assert v["2019"] == "NO_CONTEXT"  # on the page, but far from every content word of the sentence


def test_rounding_needs_a_more_precise_page_number():
    s = "Exports grew 29% in the year."
    assert verdicts(s, "exports grew by 29.4% that year")["29%"] == "FOUND_ROUNDED"
    assert verdicts(s, "exports grew by 30% that year")["29%"] == "NOT_FOUND"
    assert verdicts("Exports grew nearly 30% in the year.", "exports grew by 29.2% that year")["30%"] == "FOUND_ROUNDED"


def test_percent_is_not_matched_by_a_money_value():
    assert verdicts("Margins were 12.5% for exporters.", "exporters paid $12.5 in fees")["12.5%"] == "NOT_FOUND"


def test_month_year_matches_a_full_date():
    assert verdicts("Netflix acquired the rights in March 2019.", "On 5 March 2019 Netflix acquired the rights")[
        "March 2019"] == "FOUND_NORMALIZED"


def test_unreadable_page():
    (r,) = check_sentence("Revenue reached $3.1 billion.", None)
    assert r["verdict"] == "SOURCE_UNAVAILABLE"


def test_content_words():
    assert content_words("Revenue reached $3.1 billion in March[^2].") == {"revenue", "reached"}


# --- 0.3.4 (NEXT №42) ------------------------------------------------------------------------------------------------


def test_year_needs_a_word_of_its_own_clause_nearby():
    # E009 S003: "26% in 2019" was called found by a "2019" in the page's copyright line, 300 characters from other
    # words of the sentence
    sentence = "Nearly 37% of households used e-commerce in 2020, a marked increase from 26% in 2019 among seniors."
    page = ("Households and e-commerce: nearly 37% of senior households shopped online in 2020. " + "x " * 60
            + "Download the full Japan report ©2019 | This report was produced by FP Analytics.")
    v = verdicts(sentence, page)
    assert v["2020"] == "FOUND" and v["2019"] == "NO_CONTEXT"


def test_gemini_footnotes_after_a_space_are_citations():
    from verbatim.numbers import cited_sentences
    article = ("# Report\n\nNearly 37% of households used e-commerce in 2020, up from 26% in 2019 16, and usage has "
               "multiplied since the early 2000s.3\n\n# Works cited\n\n3. AARP, https://aarp.example/japan\n"
               "16. Trade.gov, https://trade.example/japan-ecommerce\n")
    (c,) = cited_sentences(article)
    assert c["urls"] == ["https://trade.example/japan-ecommerce", "https://aarp.example/japan"]
    assert [n["text"] for n in c["numbers"]] == ["37%", "2020", "26%", "2019"]


def test_spaced_digits_that_are_values_are_not_footnotes():
    from verbatim.numbers import cites
    defs = {"10": "https://a.example/10", "16": "https://a.example/16"}
    assert cites("In 2019 16 companies listed, and the top 10 firms grew.", defs, True) == []


def test_check_report_judges_numbers_on_readable_links_only(tmp_path):
    from verbatim.numbers import check_report
    from verbatim.store import Store
    s = Store(tmp_path)
    body = ("<p>" + "Market background and other text. " * 40 + "</p><p>The tablet POS market was valued at "
            "USD 3.4 billion in 2022, growing at 7.1% a year.</p>").encode()
    s.add("https://r.example/pos", body, content_type="text/html")
    s.add("https://gate.example/pos", b"<p>Client Challenge A required part of this site couldn't load.</p>",
          content_type="text/html")
    md = ("# R\n\nThe tablet POS market was worth $3.4 billion in 2022 and grows 9.5% a year ([Zion](https://r.example/pos)).\n\n"
          "The market will reach $15 billion by 2030 ([Gate](https://gate.example/pos)).\n")
    rows = {r["text"]: (r["verdict"], r["id"]) for r in check_report(md, s)}
    assert rows["$3.4 billion"] == ("FOUND", "L3.n1") and rows["9.5%"][0] == "NOT_FOUND"
    assert rows["$15 billion"][0] == "SOURCE_UNAVAILABLE" and rows["2030"][1] == "L5.n2"
