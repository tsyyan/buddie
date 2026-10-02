"""Which DeepResearch Bench II reports E008 checks, shared by the step scripts (run in data/).

English reports only (fewer than 200 CJK characters): a quote in a Chinese report of an English page is a translation.
Gemini 3 Pro is listed but gives no quotes: it cites `[cite: N]` with vertexaisearch grounding redirects, and its
reports have no quoted phrase of 6+ words with a link. Gemini 2.5 Pro has one such quote in 17 English reports.
"""
import re
from pathlib import Path

SYSTEMS = ["GPT-o3-DeepResearch", "Perplexity-Research", "Doubao-DeepResearch", "Grok-DeepSearch",
           "Gemini2.5-Pro-DeepResearch", "Gemini3-Pro-DeepResearch"]


def reports():
    """(system, task id, Markdown) for every English report."""
    for m in SYSTEMS:
        for f in sorted(Path("md", m).glob("idx-*.md"), key=lambda p: int(p.stem.split("-")[1])):
            text = f.read_text()
            if len(re.findall(r"[一-鿿]", text)) < 200:
                yield m, int(f.stem.split("-")[1]), text
