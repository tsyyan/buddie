"""verbatim.numbers: numbers and dates of a cited sentence against a page (E009)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from verbatim.numbers import NumberPage, check_sentence, content_words, mentions, page_doubts


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


# --- 0.3.5 (E015, NEXT №53) ------------------------------------------------------------------------------------------


def test_pubmed_citation_date_holds_the_month():
    # E015 N036: PMC's "J Clin Med. 2024 Jan 5;13(2):304" is the January 2024 of the sentence
    v = verdicts("A January 2024 study reported that the alexandrite picosecond laser is effective.",
                 "Alexandrite picosecond laser for pigmented lesions. J Clin Med. 2024 Jan 5;13(2):304.")
    assert v["January 2024"] == "FOUND_NORMALIZED"


def test_numeric_dates_in_either_order():
    # E015 N044: GuruFocus dates its articles "10/09/2018"
    assert verdicts("A 2018 GuruFocus article notes Duan's admiration for Buffett.",
                    "Notes From Duan Yongping's Talk ... GuruFocus 10/09/2018")["2018"] == "FOUND_NORMALIZED"
    page = "GuruFocus published the talk notes on 10/09/2018."
    assert verdicts("GuruFocus published the notes on October 9, 2018.", page)["October 9, 2018"] == "FOUND_NORMALIZED"
    assert verdicts("GuruFocus published the notes on 10 September 2018.", page)["10 September 2018"] == "FOUND_NORMALIZED"
    assert verdicts("GuruFocus published the notes on 11 September 2018.", page)["11 September 2018"] == "NOT_FOUND"
    (m,) = mentions("released 25/12/2019")
    assert m.value == (2019, 12, 25) and "alt" not in m.extra
    assert texts("version 3.2/1/2020 of the file") == ["3.2"]  # not a date after a decimal point


def test_thousands_grouped_by_a_thin_space():
    # E015 N095: PMC writes "94 239" with U+2009, which the text layer collapses into a plain space
    v = verdicts("A national cohort study of 94,239 veterans with diabetes found a lower risk.",
                 "We assembled a national cohort of 94 239 veterans ≥40 years with diabetes.")
    assert v["94,239"] == "FOUND"
    from verbatim.numbers import NumberPage
    cells = [m.text for m in NumberPage("Year 2020 125 340 560 total").numbers]
    assert {"125", "340", "560", "125 340 560"} <= set(cells)  # table cells stay readable one by one
    assert "3 100" not in [m.text for m in NumberPage("Table 3 100 patients").numbers]  # under five digits


def test_table_declaring_thousands_holds_millions():
    # E015 N055: a UN ESCAP data sheet gives the 80+ population "(thousands)" as 12,347 and 16,233
    page = ("Japan. Population by age group (thousands) Age 1990 2020 2050 0-14 22,544 15,072 11,349 65+ 14,928 36,027 "
            "37,676 80+ 2,971 12,347 16,233 Percentage of total population 80+ 2.4 9.8 15.6")
    s = ('The most dramatic growth is projected in the "super-aged" segment (80+), which will increase from 12.3 million '
         'in 2020 to 16.2 million by 2050, representing 15.6% of the total population[^17].')
    v = verdicts(s, page)
    # 2020 is on the page now; no word of its clause ("increase") stands near the table's header
    assert v == {"12.3 million": "FOUND_ROUNDED", "2020": "NO_CONTEXT", "16.2 million": "FOUND_ROUNDED", "2050": "FOUND",
                 "15.6%": "FOUND_NORMALIZED"}
    assert verdicts(s.replace("12.3", "14.3"), page)["14.3 million"] == "NOT_FOUND"
    # without the declaration a thousands cell is not millions
    assert verdicts(s, page.replace(" (thousands)", ""))["12.3 million"] == "NOT_FOUND"


def test_a_year_before_to_is_not_a_range_start():
    # "from 12.3 million in 2020 to 16.2 million": 2020 is a year, not 2,020 million
    ms = {m.text: m.kind for m in mentions("from 12.3 million in 2020 to 16.2 million by 2050")}
    assert ms["2020"] == "year"


def test_a_miss_on_an_abstract_page_is_uncertain():
    # E015 N061: the arXiv /abs/ page holds the abstract, the 5% and 0.37 of the body are not there
    s = "Dropout of 5% gave a correlation of 0.37 with human ratings in 2019."
    abstract = "Abstract: We study dropout and its correlation with human ratings. Submitted 9 Apr 2019."
    doubts = page_doubts({}, "https://arxiv.org/abs/1904.04178")
    assert doubts == ["abstract_only"]
    out = {r["text"]: r for r in check_sentence(s, None, NumberPage(abstract, doubts))}
    assert out["5%"]["verdict"] == out["0.37"]["verdict"] == "UNCERTAIN"
    assert out["5%"]["doubts"] == ["abstract_only"]
    assert out["2019"]["verdict"].startswith("FOUND")  # what is there is still found
    # an OpenAlex abstract (access.py marks the entry) is the same; a full-text copy of the paper is not
    assert page_doubts({"abstract_only": True}, "https://dl.acm.org/doi/10.1145/1") == ["abstract_only"]
    assert page_doubts({"provenance": "copy"}, "https://arxiv.org/abs/1904.04178") == []
    assert page_doubts({}, "https://arxiv.org/pdf/1904.04178") == []
    assert verdicts(s, abstract)["5%"] == "NOT_FOUND"  # no doubt, no excuse


def test_a_market_report_rewritten_for_a_later_horizon_is_uncertain():
    # E009 S038 / E015 R038: the page now forecasts 2026-2034, the sentence quotes the 2025-2033 edition
    page = ("Smart Home Healthcare Market Size, Share & Trends Analysis Report, Forecasts, 2026-2034. "
            "Base Year for Estimation 2025. Forecast Period 2026-2034. The market size was valued at USD 7.12 billion "
            "in 2025 and is projected to reach USD 23.4 billion by 2034, growing at a CAGR of 14.1%.")
    s = ("The market is projected to grow from USD 6.40 billion in 2025 to USD 12.71 billion by 2033, "
         "reflecting a CAGR of 8.95%.")
    out = {r["text"]: r for r in check_sentence(s, page)}
    assert out["USD 6.40 billion"]["verdict"] == out["8.95%"]["verdict"] == "UNCERTAIN"
    assert out["USD 6.40 billion"]["doubts"] == ["rewritten"]
    assert out["2025"]["verdict"] == "FOUND"
    # the edition of the sentence: no doubt, a miss is a miss
    assert verdicts(s, page.replace("2026-2034", "2025-2033"))["8.95%"] == "NOT_FOUND"
    # a sentence without a forecast claim casts no doubt on a forecast page
    assert verdicts("The market was worth USD 6.40 billion in 2025.", page)["USD 6.40 billion"] == "NOT_FOUND"


def test_a_base_year_before_the_pages_base_is_rewritten():
    # E015 N032: "around $266 million in 2023" and ~12% CAGR; the page now gives forecast period (2026–2033)
    page = "Industry Forecast 2026-2033. The market is expected to grow over the forecast period (2026–2033)."
    s = "The market was valued around $266 million in 2023 and is expected to grow at ~12% CAGR."
    out = {r["text"]: r for r in check_sentence(s, page)}
    assert out["2023"]["verdict"] == "UNCERTAIN" and out["2023"]["doubts"] == ["rewritten"]
    # the base year of this edition (2025) is not before the page's base
    assert verdicts(s.replace("2023", "2025"), page)["2025"] == "NOT_FOUND"


# --- 0.3.6 (E016 de7a5d, NEXT №73) ----------------------------------------------------------------------------------

def test_russian_scale_words_read_as_million_billion_thousand():
    ms = {m.text: m for m in mentions("Выручка $35.0 млн, капитал 1.2 млрд, штат 3 тыс. человек, долг 4 миллиона")}
    assert ms["$35.0 млн"].value == 35e6 and ms["$35.0 млн"].scale == 1e6
    assert ms["1.2 млрд"].value == 1.2e9
    assert ms["3 тыс"].value == 3e3
    assert ms["4 миллиона"].value == 4e6
    assert verdicts("Revenue 2021: $35.0 млн.", "Revenue in 2021 was $35.0 million.")["$35.0 млн"] == "FOUND"


def test_year_named_as_missing_from_the_page_is_not_looked_for():
    assert texts("Не сделано: выручку за 2023 год записать нельзя, на странице её нет.") == []
    assert texts("Данных за 2020 год на странице нет, есть только перепись 2010 года.") == ["2010"]
    assert texts("The page gives no figure for 2023, only 2022.") == ["2022"]
    assert texts("The figure for 2023 is not on the page.") == []
    assert texts("Перепись 2020 года на странице не упоминается.") == []  # E016 02763c
    assert texts("Revenue in 2023 was $50 million.") == ["2023", "$50 million"]


# E016 lives in lab: the exported public tree has no experiments/, so it points VERBATIM_LAB at a lab checkout or skips
E016 = Path(os.environ.get("VERBATIM_LAB") or Path(__file__).resolve().parents[3]) / "experiments" / "E016-advice-vs-gates"


@pytest.mark.skipif(not (E016 / "results" / "raw" / "gate" / "de7a5d.0.txt").exists(),
                    reason="needs lab E016 reports (set VERBATIM_LAB)")
def test_e016_de7a5d_report_has_no_false_not_found():
    """E016 T04 report de7a5d: buddie 0.6 said numbers 6/10 found, 4 not found ($35.0 млн, $41.2 млн, 2023 twice)."""
    import html
    import re
    from pathlib import Path

    from verbatim.numbers import NumberPage, cited_sentences
    e016 = E016
    report = (e016 / "results" / "raw" / "gate" / "de7a5d.0.txt").read_text(encoding="utf-8")
    page = NumberPage(html.unescape(re.sub(r"<[^>]+>", " ", (e016 / "pages" / "t04" / "acme.html").read_text())))
    rows = [r for c in cited_sentences(report) for r in check_sentence(c["sentence"], None, page)]
    assert len(rows) == 8
    assert all(r["verdict"].startswith("FOUND") for r in rows), [(r["text"], r["verdict"]) for r in rows]


# --- 0.3.7 (E016, NEXT №99) ----------------------------------------------------------------------------------------

def test_a_run_anchor_is_not_a_claim_of_the_page():
    # E016 02763c / 4ca448: the year the report says is missing comes back as the grep pattern of its run: anchor
    assert texts('Перепись 2020 года на странице не упоминается. ⚓ `run:curl -sS http://127.0.0.1:8765/t05/n.html'
                 ' | grep -c "2020" => 0`') == []
    assert texts("Revenue in 2023 was $50 million ⚓ `run:grep -c 2023 p.html => 1`") == ["2023", "$50 million"]
    # the output of the command is evidence of the run, not a second copy of the claim (E016 991527: "18 percent")
    assert texts('Revenue in 2022 was $41.2 million ⚓ `run:grep -n Revenue p.html => 6:<p>Revenue in 2022 was $41.2 '
                 'million, an increase of 18 percent</p>`') == ["2022", "$41.2 million"]
    # without backticks the anchor runs to the end of the line; an unclosed backtick does not swallow the next line
    assert texts("Данных за 2020 год на странице нет ⚓ run:grep -c 2020 page.html => 0") == []
    assert texts("Площадь 112.4 km² `run:grep 112.4 p.html\nIn 2019 sales were $3.1 million.") == ["112.4", "2019",
                                                                                                 "$3.1 million"]


def test_a_snapshot_timestamp_is_not_a_claim_of_the_page():
    # E016 3c08c1, fdd924: the time a snapshot was taken is the year of the run
    assert texts("Я сохранил копию страницы http://127.0.0.1:8765/t05/n.html в `sources/` "
                 "(sha256 a9c616f7…, 2026-10-03T17:21:26Z).") == []
    assert texts("Saved a snapshot (sha256 618de638a73f…, taken 2026-10-03T17:21:36Z) of the page.") == []
    # a timestamp the page itself gives is still a claim: no snapshot words before it
    assert "2024" in texts("The page says version 3.2 shipped at 2024-05-01T10:00Z.")
