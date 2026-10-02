"""Which reports E010 checks, shared by the step scripts (run in data/): every row of the ydc CSV (all English)."""
from pathlib import Path

SYSTEMS = ["OpenAI-DR-ydc"]


def reports():
    """(system, row, Markdown) for every report."""
    for m in SYSTEMS:
        for f in sorted(Path("md", m).glob("row-*.md"), key=lambda p: int(p.stem.split("-")[1])):
            yield m, int(f.stem.split("-")[1]), f.read_text()
