"""F2 of the Feedback E2E benchmark (experiments/feedback-e2e-v1/REVIEW-F1-F4.md): two honest repairs that repair.py
rejects as out_of_scope today, and the protections any narrower scope rule must keep. Characterization only: the
rules proposed in REVIEW-F1-F4.md are not implemented, so the first two tests pin today's behaviour (change them
only together with the rule), and the guard tests must hold before and after.

Offline: scope is computed from a feedback alone (repair.scope, changes, outside); no check runs."""
from __future__ import annotations

import hashlib

import pytest

from buddie import repair
from buddie.verbatim.store import Store

URL = "https://news.example.org/outage"
PAGE = ("<p>" + "Background paragraph about the service. " * 40 + "</p><p>The company said the outage began at 14:59 "
        "UTC and was resolved within two hours.</p>").encode()
GOOD_Q = f"The vendor wrote that “the outage began at 14:59 UTC and was resolved within two hours” ([r]({URL}))."
BAD_Q = GOOD_Q.replace("14:59", "14:58")
ANCHOR = f"The data file is as stated. `⚓ data.txt#{hashlib.sha256(b'hello' + bytes([10])).hexdigest()}`"
CI = "CI passed. ⚓ `ci:o/r@0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c=success`"
GONE = "The postmortem says “the outage began at 14:59 UTC and was resolved” ([p](https://gone.example.org/pm))."


@pytest.fixture
def feedback_of(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "data.txt").write_bytes(b"hello\n")
    Store(tmp_path / "store").add(URL, PAGE, content_type="text/html")

    def make(text):
        from buddie import trace as tr
        got = repair.reverify(text, repos=[repo], store=tmp_path / "store", fetch=False, github=None)
        return tr.start(got, iteration_limit=2)[1]
    return make


def stray(feedback, original, corrected):
    return repair.outside(repair.scope(feedback, original), *repair.changes(original, corrected))


def test_today_removing_a_paragraph_with_its_separator_is_out_of_scope(feedback_of):
    original = f"{BAD_Q}\n\n{ANCHOR}"
    fb = feedback_of(original)
    assert stray(fb, original, ANCHOR) == [2]                              # the blank separator line
    assert stray(fb, original, f"\n\n{ANCHOR}") == []                       # the same removal, separator kept


def test_today_a_disclosure_next_to_a_non_actionable_finding_is_out_of_scope(feedback_of):
    original = f"{GONE}\n\n{CI}"
    fb = feedback_of(original)
    ci = next(f for f in fb["findings"] if f["check"] == "ci_anchor")
    assert ci["condition"] == "unavailable" and ci["action_id"] is None     # no action, so no scope
    disclosed = original + "\nbuddie: the CI status of 0f1e2d3 could not be read here; not verified."
    assert stray(fb, original, disclosed) == [3]
    assert repair.added(original, disclosed) == []                           # a disclosure is not added content


# --- guards: what any F2 rule must keep refusing ------------------------------------------------------------------

def test_guard_a_separator_between_two_kept_paragraphs_stays_protected(feedback_of):
    original = f"{BAD_Q}\n\n{ANCHOR}"
    fb = feedback_of(original)
    merged = f"{GOOD_Q}\n{ANCHOR}"                                          # fixes the quote and joins the paragraphs
    assert 2 in stray(fb, original, merged)


def test_guard_text_next_to_a_non_actionable_finding_stays_protected(feedback_of):
    original = f"{GONE}\n\n{CI}"
    fb = feedback_of(original)
    assert stray(fb, original, original + "\nCI is green on every branch.") == [3]   # a claim, not a disclosure
    assert repair.added(original, original + "\nCI is green on every branch.") == [4]  # and it is added content
    assert stray(fb, original, original.replace("CI passed", "CI succeeded")) == [3]


def test_guard_a_verified_claim_stays_protected(feedback_of):
    original = f"{BAD_Q}\n\n{ANCHOR}"
    fb = feedback_of(original)
    assert stray(fb, original, BAD_Q.replace("14:58", "14:59")) == [2, 3]   # removing the verified anchor's paragraph
    assert repair.lost_verified(fb, original, f"{GOOD_Q}\n\n") != []
