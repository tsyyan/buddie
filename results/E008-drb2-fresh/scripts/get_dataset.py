"""E008 step 0. Run in data/ (gitignored): download DeepResearch Bench II reports and turn each into Markdown.

Dataset: muset-ai/DeepResearch-Bench-II-Dataset (Apache-2.0) at a pinned commit. Reports come as .md (Gemini 3 Pro,
Doubao, Perplexity), .docx (GPT-o3, Gemini 2.5 Pro) or .html (Grok). Qwen ships PDFs whose links pdftotext loses, so
it is left out. docx and html are converted here with the standard library: paragraphs become lines, hyperlinks
become [text](url), headings and list items keep a Markdown marker. Writes md/<system>/idx-N.md and DATASET.json.
"""
import concurrent.futures as cf, hashlib, html, json, re, subprocess, urllib.parse, urllib.request, zipfile
from html.parser import HTMLParser
from pathlib import Path

REPO = "muset-ai/DeepResearch-Bench-II-Dataset"
REV = "73c8b0010f6c63a13df52250561dd8c5a68d9612"
BASE = f"https://huggingface.co/datasets/{REPO}/resolve/{REV}/"
SYSTEMS = {"GPT-o3-DeepResearch": "docx", "Gemini2.5-Pro-DeepResearch": "docx", "Gemini3-Pro-DeepResearch": "md",
           "Perplexity-Research": "md", "Grok-DeepSearch": "html", "Doubao-DeepResearch": "md"}
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def docx_md(path: Path) -> str:
    import xml.etree.ElementTree as ET
    z = zipfile.ZipFile(path)
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("word/_rels/document.xml.rels"))}
    out = []
    for p in ET.fromstring(z.read("word/document.xml")).iter(W + "p"):
        style = p.find(f"{W}pPr/{W}pStyle")
        style = style.get(W + "val") if style is not None else ""
        parts = []
        for el in p:
            if el.tag == W + "r":
                parts.append("".join(t.text or "" for t in el.iter(W + "t")))
            elif el.tag == W + "hyperlink":
                txt = "".join(t.text or "" for t in el.iter(W + "t"))
                url = rels.get(el.get(R + "id"))
                parts.append(f"[{txt}]({url.replace(' ', '%20').replace(')', '%29')})" if url else txt)
        line = "".join(parts)
        m = re.match(r"Heading(\d)", style)
        if m:
            line = "#" * int(m.group(1)) + " " + line
        elif p.find(f"{W}pPr/{W}numPr") is not None:
            line = "- " + line
        out.append(line)
    return "\n\n".join(out) + "\n"


class _H(HTMLParser):
    BLOCK = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "div", "br", "blockquote", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.cur, self.href, self.atext, self.skip = [], [], None, [], 0

    def flush(self):
        line = re.sub(r"[ \t\r\n]+", " ", "".join(self.cur)).strip()
        if line:
            self.out.append(line)
        self.cur = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag == "a":
            self.href, self.atext = dict(attrs).get("href"), []
        elif tag in self.BLOCK:
            self.flush()
            if tag[0] == "h" and tag[1:].isdigit():
                self.cur.append("#" * int(tag[1:]) + " ")
            elif tag == "li":
                self.cur.append("- ")
        elif tag in ("td", "th"):
            self.cur.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1
        elif tag == "a" and self.href is not None:
            t = "".join(self.atext)
            u = self.href
            self.cur.append(f"[{t}]({u.replace(' ', '%20').replace(')', '%29')})" if u.startswith("http") else t)
            self.href = None
        elif tag in self.BLOCK:
            self.flush()

    def handle_data(self, data):
        if self.skip:
            return
        (self.atext if self.href is not None else self.cur).append(data)


def html_md(path: Path) -> str:
    h = _H()
    h.feed(path.read_text(errors="replace"))
    h.flush()
    return "\n\n".join(h.out) + "\n"


def main():
    tree = json.loads(urllib.request.urlopen(f"https://huggingface.co/api/datasets/{REPO}/tree/{REV}?recursive=true").read())
    want = [t["path"] for t in tree if "/" in t["path"] and t["path"].split("/")[0] in SYSTEMS
            and t["path"].endswith("." + SYSTEMS[t["path"].split("/")[0]])]
    def get(p):
        dst = Path("orig") / p
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            subprocess.run(["curl", "-sSfL", "--retry", "3", "-o", str(dst), BASE + urllib.parse.quote(p)], check=True)
        return p
    with cf.ThreadPoolExecutor(16) as ex:
        list(ex.map(get, want))
    files = {}
    for p in sorted(want):
        src = Path("orig") / p
        sysname, name = p.split("/")
        ext = SYSTEMS[sysname]
        md = src.read_text() if ext == "md" else docx_md(src) if ext == "docx" else html_md(src)
        dst = Path("md") / sysname / (name.rsplit(".", 1)[0] + ".md")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(md)
        files[p] = hashlib.sha256(src.read_bytes()).hexdigest()
    Path("DATASET.json").write_text(json.dumps({"dataset": f"{REPO} (Apache-2.0), DeepResearch Bench II", "revision": REV,
                                                "files_sha256": files}, indent=1) + "\n")
    print(len(files))


if __name__ == "__main__":
    main()
