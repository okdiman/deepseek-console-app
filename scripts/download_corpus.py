#!/usr/bin/env python3
"""
Download corpus documents for the RAG indexing demo (Day 21).

Run once:
    python3 scripts/download_corpus.py

Sources:
  - Wikipedia API  (plain text with == Section == markers)
  - GitHub raw     (FastAPI README.md, PEP 8 RST)
"""

import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

CORPUS_DIR = Path(__file__).parent.parent / "docs" / "corpus"
TIMEOUT = 30
UA = "Mozilla/5.0 (compatible; corpus-downloader/1.0)"


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ── Wikipedia ──────────────────────────────────────────────────────────────

def fetch_wikipedia_extract(title: str) -> str:
    """Fetch Wikipedia article as plain text with == Section == markers.

    Tries exsectionformat=wiki first; falls back to plain extract if empty.
    """
    base = "https://en.wikipedia.org/w/api.php"

    def _query(extra: dict) -> dict:
        params = urllib.parse.urlencode({
            "action": "query",
            "titles": title,
            "prop": "extracts",
            "explaintext": "1",
            "redirects": "1",
            "format": "json",
            **extra,
        })
        data = json.loads(fetch(f"{base}?{params}"))
        pages = data["query"]["pages"]
        page = next(iter(pages.values()))
        if "missing" in page:
            raise ValueError(f"Wikipedia page not found: {title!r}")
        return page

    # Attempt 1: with section markers
    page = _query({"exsectionformat": "wiki"})
    text = page.get("extract", "").strip()
    if text:
        return text

    # Attempt 2: plain text, no section markers
    page = _query({})
    text = page.get("extract", "").strip()
    if text:
        return text

    raise ValueError(f"Empty extract for Wikipedia page: {title!r}")


def wiki_to_markdown(text: str, doc_title: str) -> str:
    """Convert Wikipedia plain text (== Section ==) to Markdown."""
    out = [f"# {doc_title}", ""]
    for line in text.splitlines():
        s = line.strip()
        if re.match(r"^=== .+ ===$", s):
            out.append(f"### {s[4:-4].strip()}")
        elif re.match(r"^== .+ ==$", s):
            out.append(f"## {s[3:-3].strip()}")
        else:
            out.append(line)
    return "\n".join(out)


# ── RST → Markdown (PEP 8) ────────────────────────────────────────────────

def fetch_pep8_rst() -> str:
    return fetch(
        "https://raw.githubusercontent.com/python/peps/main/peps/pep-0008.rst"
    )


def rst_to_markdown(rst: str, doc_title: str) -> str:
    """Convert PEP RST to Markdown using underline-detection heuristic."""
    lines = rst.splitlines()
    out = [f"# {doc_title}", ""]
    i = 0
    while i < len(lines):
        cur = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        nxt_s = nxt.strip()

        # Detect underline-only section header
        if (
            nxt_s
            and re.match(r"^([=\-~^`])\1{2,}$", nxt_s)
            and cur.strip()
            and len(nxt_s) >= len(cur.strip()) - 2
        ):
            char = nxt_s[0]
            text = cur.strip()
            # Skip the document title (already in # heading)
            if char == "=" and not out[-2:] == ["", ""]:
                out.append(f"## {text}")
            elif char == "=":
                out.append(f"## {text}")
            elif char == "-":
                out.append(f"### {text}")
            else:
                out.append(f"#### {text}")
            out.append("")
            i += 2
            continue

        # Skip RST metadata lines
        if re.match(r"^\.\. (pep|title|version|author|status|type|created|python-version|post-history|resolution)::", cur):
            i += 1
            continue

        # RST code blocks → fenced markdown
        if re.match(r"^\.\. code-block::\s*(python)?", cur):
            out.append("```python")
            i += 1
            if i < len(lines) and not lines[i].strip():
                i += 1
            while i < len(lines) and (lines[i].startswith("    ") or not lines[i].strip()):
                out.append(lines[i][4:] if lines[i].startswith("    ") else "")
                i += 1
            out.append("```")
            continue

        # Inline RST → Markdown substitutions
        cur = re.sub(r":pep:`(\d+)`", r"PEP \1", cur)
        cur = re.sub(r"``(.+?)``", r"`\1`", cur)
        cur = re.sub(r":func:`(.+?)`", r"`\1()`", cur)
        cur = re.sub(r":class:`(.+?)`", r"`\1`", cur)

        out.append(cur)
        i += 1

    return "\n".join(out)


# ── Documents ──────────────────────────────────────────────────────────────

DOCUMENTS = [
    {
        "filename": "pep8_style_guide.md",
        "title": "PEP 8 – Style Guide for Python Code",
        "fetch": "pep8",
    },
    {
        "filename": "retrieval_augmented_generation.md",
        "title": "Information Retrieval",
        "fetch": "wiki",
        "wiki_title": "Information retrieval",
    },
    {
        "filename": "transformer_architecture.md",
        "title": "Transformer (Deep Learning Architecture)",
        "fetch": "wiki",
        "wiki_title": "Transformer (deep learning architecture)",
    },
    {
        "filename": "large_language_models.md",
        "title": "Large Language Model",
        "fetch": "wiki",
        "wiki_title": "Large language model",
    },
    {
        "filename": "python_concurrency_guide.md",
        "title": "Concurrency in Computing",
        "fetch": "wiki",
        "wiki_title": "Concurrent computing",
    },
    {
        "filename": "fastapi_overview.md",
        "title": "FastAPI Overview",
        "fetch": "github",
        "url": "https://raw.githubusercontent.com/tiangolo/fastapi/master/README.md",
    },
]


def main() -> None:
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    errors = []

    for doc in DOCUMENTS:
        filename = doc["filename"]
        title = doc["title"]
        path = CORPUS_DIR / filename
        print(f"Fetching {filename}...", end=" ", flush=True)

        try:
            if doc["fetch"] == "pep8":
                rst = fetch_pep8_rst()
                content = rst_to_markdown(rst, title)
            elif doc["fetch"] == "wiki":
                raw = fetch_wikipedia_extract(doc["wiki_title"])
                content = wiki_to_markdown(raw, doc["title"])
            elif doc["fetch"] == "github":
                content = fetch(doc["url"])
            else:
                raise ValueError(f"Unknown fetch type: {doc['fetch']}")

            path.write_text(content, encoding="utf-8")
            lines = content.count("\n")
            print(f"✓  {lines} lines")

        except Exception as exc:
            print(f"✗  {exc}")
            errors.append((filename, exc))

    print()
    if errors:
        print(f"Failed: {len(errors)} file(s):")
        for name, err in errors:
            print(f"  {name}: {err}")
        sys.exit(1)
    else:
        total = sum((CORPUS_DIR / d["filename"]).stat().st_size for d in DOCUMENTS)
        print(f"Done. {len(DOCUMENTS)} files saved to {CORPUS_DIR}")
        print(f"Total size: {total // 1024} KB")


if __name__ == "__main__":
    main()
