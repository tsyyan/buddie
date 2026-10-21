"""Every quote and number verdict has one meaning for the outcome; a check that did not finish is never a PASS."""
from __future__ import annotations

import pytest

from buddie import verify as v
from buddie.verbatim import check, numbers
from buddie.verbatim.store import Store

QUOTES = {"FOUND": "PASS", "FOUND_NORMALIZED": "PASS", "NOT_A_QUOTE": "PASS", "HIDDEN_ONLY": "GAPS",
          "FOUND_IN_COPY": "GAPS", "UNCERTAIN": "GAPS", "SOURCE_UNAVAILABLE": "GAPS", "NO_SOURCE": "GAPS",
          "NOT_FOUND": "FAIL"}
NUMBERS = {"FOUND": "PASS", "FOUND_NORMALIZED": "PASS", "FOUND_ROUNDED": "PASS", "NO_CONTEXT": "GAPS",
           "UNCERTAIN": "GAPS", "SOURCE_UNAVAILABLE": "GAPS", "NOT_FOUND": "GAPS"}


def test_every_verdict_verbatim_can_return_has_a_meaning():
    assert set(v.QUOTE_OUTCOME) == set(check.ORDER) == set(QUOTES)
    assert set(v.NUMBER_OUTCOME) == set(numbers.RANK) == set(NUMBERS)


@pytest.mark.parametrize("verdict", [*QUOTES, "SOME_FUTURE_VERDICT"])
def test_quote_verdict_outcome(verdict):
    assert v.outcome([{"verdict": verdict}], []) == QUOTES.get(verdict, "GAPS")


@pytest.mark.parametrize("mode", ["gap", "fail"])
@pytest.mark.parametrize("verdict", [*NUMBERS, "SOME_FUTURE_VERDICT"])
def test_number_verdict_outcome(verdict, mode):
    want = "FAIL" if verdict == "NOT_FOUND" and mode == "fail" else NUMBERS.get(verdict, "GAPS")
    assert v.outcome([], [], numbers=[{"verdict": verdict}], numbers_mode=mode) == want


def test_an_unfinished_number_is_a_gap_beside_found_quotes():
    found = [{"verdict": "FOUND"}]
    assert v.outcome(found, [], numbers=[{"verdict": "FOUND"}]) == "PASS"
    for verdict in ("SOURCE_UNAVAILABLE", "NO_CONTEXT", "SOME_FUTURE_VERDICT"):
        assert v.outcome(found, [], numbers=[{"verdict": "FOUND"}, {"verdict": verdict}]) == "GAPS"


URL = "https://market.example/pos"
PAGE = ("<p>" + "Zebra giraffe lemur otter. " * 40 + "</p><p>Shipping crates weighed 3.4 billion grams overall.</p>")


@pytest.mark.parametrize("url, verdict", [(URL, "NO_CONTEXT"), ("https://gone.example/x", "SOURCE_UNAVAILABLE")])
def test_the_receipt_names_the_unfinished_number(tmp_path, url, verdict):
    Store(tmp_path).add(URL, PAGE.encode(), content_type="text/html")
    text = f"The tablet POS market was worth $3.4 billion ([Zion]({url})).\n"
    for mode in ("gap", "fail"):
        pred = v.verify(text, store=str(tmp_path), fetch=False, numbers=mode)["predicate"]
        assert pred["numbers"][0]["verdict"] == verdict
        assert pred["outcome"] == "GAPS" and pred["blocking"] == []
        assert pred["gaps"] == [f"number L1.n1 “$3.4 billion” {verdict}: {url}"]
        assert pred["line"].startswith("buddie GAPS: numbers 0/1 found")
