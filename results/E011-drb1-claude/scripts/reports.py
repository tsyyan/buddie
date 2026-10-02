"""Which reports E011 checks, shared by the step scripts (run in data/): the 50 English Claude 3.7 reports."""
from pathlib import Path

SYSTEMS = ["Claude-3.7-DRB"]


def reports():
    """(system, task id, Markdown) for every report."""
    for m in SYSTEMS:
        for f in sorted(Path("md", m).glob("row-*.md"), key=lambda p: int(p.stem.split("-")[1])):
            yield m, int(f.stem.split("-")[1]), f.read_text()
