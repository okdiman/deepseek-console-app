"""
Two chunking strategies:
  - FixedSizeChunker  : sliding window over tokens (tiktoken)
  - StructureChunker  : markdown headings or Python AST class/function nodes
"""

import ast
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Chunk:
    chunk_id: str   # e.g. "pep8_style_guide_md_fixed_0"
    source: str     # relative path string
    title: str      # human-readable document title
    section: str    # heading text or "ClassName.method" (empty for fixed)
    strategy: str   # "fixed" or "structure"
    index: int      # 0-based position within this source
    text: str       # chunk content


def _make_slug(source: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "_", source).strip("_")


# ── Base ──────────────────────────────────────────────────────────────────

class BaseChunker(ABC):
    strategy_name: str = ""

    @abstractmethod
    def chunk(self, text: str, source: str, title: str) -> List[Chunk]:
        ...


# ── Strategy A: Fixed-size token window ──────────────────────────────────

class FixedSizeChunker(BaseChunker):
    """Splits text into fixed-size token windows with overlap."""

    strategy_name = "fixed"

    def __init__(self, chunk_size: int = 400, overlap: int = 50) -> None:
        import tiktoken
        self._size = chunk_size
        self._overlap = max(0, min(overlap, chunk_size - 1))
        self._enc = tiktoken.get_encoding("cl100k_base")

    def chunk(self, text: str, source: str, title: str) -> List[Chunk]:
        if not text.strip():
            return []

        tokens = self._enc.encode(text)
        slug = _make_slug(source)
        step = self._size - self._overlap
        chunks: List[Chunk] = []
        i = 0
        idx = 0

        while i < len(tokens):
            window = tokens[i: i + self._size]
            chunk_text = self._enc.decode(window)
            chunks.append(Chunk(
                chunk_id=f"{slug}_fixed_{idx}",
                source=source,
                title=title,
                section="",
                strategy="fixed",
                index=idx,
                text=chunk_text,
            ))
            i += step
            idx += 1

        return chunks


# ── Strategy B: Structure-aware ───────────────────────────────────────────

class StructureChunker(BaseChunker):
    """
    Markdown  → splits on ## / ### headings.
    Python    → splits on top-level class / function nodes via ast.
    Other     → falls back to FixedSizeChunker.

    Sections exceeding max_tokens are sub-chunked with FixedSizeChunker
    while preserving the section name.
    """

    strategy_name = "structure"

    def __init__(self, max_tokens: int = 800) -> None:
        import tiktoken
        self._max_tokens = max_tokens
        self._enc = tiktoken.get_encoding("cl100k_base")
        self._fallback = FixedSizeChunker(chunk_size=max_tokens, overlap=50)

    def _token_count(self, text: str) -> int:
        return len(self._enc.encode(text))

    def _sub_chunk(
        self,
        text: str,
        source: str,
        title: str,
        section: str,
        start_idx: int,
    ) -> List[Chunk]:
        """Split an oversized section with fixed chunker, keeping section name."""
        raw = self._fallback.chunk(text, source, title)
        slug = _make_slug(source)
        result = []
        for i, c in enumerate(raw):
            result.append(Chunk(
                chunk_id=f"{slug}_structure_{start_idx + i}",
                source=source,
                title=title,
                section=section,
                strategy="structure",
                index=start_idx + i,
                text=c.text,
            ))
        return result

    def chunk(self, text: str, source: str, title: str) -> List[Chunk]:
        if not text.strip():
            return []
        if source.endswith(".md"):
            return self._chunk_markdown(text, source, title)
        if source.endswith(".py"):
            return self._chunk_python(text, source, title)
        return self._fallback.chunk(text, source, title)

    # ── Markdown ──────────────────────────────────────────────────────────

    def _chunk_markdown(self, text: str, source: str, title: str) -> List[Chunk]:
        """Split on ## and ### ATX headings."""
        heading_re = re.compile(r"^(#{2,3})\s+(.+)", re.MULTILINE)
        slug = _make_slug(source)
        chunks: List[Chunk] = []
        idx = 0

        matches = list(heading_re.finditer(text))

        # Content before the first heading → section ""
        preamble = text[: matches[0].start()].strip() if matches else text.strip()
        if preamble:
            if self._token_count(preamble) > self._max_tokens:
                chunks.extend(self._sub_chunk(preamble, source, title, "", idx))
                idx += len(chunks)
            else:
                chunks.append(Chunk(
                    chunk_id=f"{slug}_structure_{idx}",
                    source=source, title=title, section="",
                    strategy="structure", index=idx, text=preamble,
                ))
                idx += 1

        for i, m in enumerate(matches):
            section_name = m.group(2).strip()
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            section_text = text[start:end].strip()

            if self._token_count(section_text) > self._max_tokens:
                sub = self._sub_chunk(section_text, source, title, section_name, idx)
                chunks.extend(sub)
                idx += len(sub)
            else:
                chunks.append(Chunk(
                    chunk_id=f"{slug}_structure_{idx}",
                    source=source, title=title, section=section_name,
                    strategy="structure", index=idx, text=section_text,
                ))
                idx += 1

        return chunks

    # ── Python ────────────────────────────────────────────────────────────

    def _chunk_python(self, text: str, source: str, title: str) -> List[Chunk]:
        """Split on top-level class / function definitions via ast."""
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return self._fallback.chunk(text, source, title)

        slug = _make_slug(source)
        chunks: List[Chunk] = []
        idx = 0

        top_nodes = [
            n for n in ast.iter_child_nodes(tree)
            if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        ]

        # Collect line ranges occupied by top-level nodes
        occupied: List[tuple] = [(n.lineno, n.end_lineno) for n in top_nodes]

        # Module header = everything outside top-level nodes (imports, constants, etc.)
        lines = text.splitlines(keepends=True)
        header_lines = []
        for lineno, line in enumerate(lines, start=1):
            if not any(start <= lineno <= end for start, end in occupied):
                header_lines.append(line)
        header_text = "".join(header_lines).strip()

        if header_text:
            if self._token_count(header_text) > self._max_tokens:
                sub = self._sub_chunk(header_text, source, title, "module header", idx)
                chunks.extend(sub)
                idx += len(sub)
            else:
                chunks.append(Chunk(
                    chunk_id=f"{slug}_structure_{idx}",
                    source=source, title=title, section="module header",
                    strategy="structure", index=idx, text=header_text,
                ))
                idx += 1

        for node in top_nodes:
            node_text = ast.get_source_segment(text, node) or ""
            if not node_text.strip():
                continue

            section = node.name

            if isinstance(node, ast.ClassDef) and self._token_count(node_text) > self._max_tokens:
                # Large class → split each method individually
                methods = [
                    n for n in ast.iter_child_nodes(node)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                if methods:
                    for method in methods:
                        method_text = ast.get_source_segment(text, method) or ""
                        method_section = f"{node.name}.{method.name}"
                        if self._token_count(method_text) > self._max_tokens:
                            sub = self._sub_chunk(method_text, source, title, method_section, idx)
                            chunks.extend(sub)
                            idx += len(sub)
                        else:
                            chunks.append(Chunk(
                                chunk_id=f"{slug}_structure_{idx}",
                                source=source, title=title, section=method_section,
                                strategy="structure", index=idx, text=method_text,
                            ))
                            idx += 1
                    continue

            if self._token_count(node_text) > self._max_tokens:
                sub = self._sub_chunk(node_text, source, title, section, idx)
                chunks.extend(sub)
                idx += len(sub)
            else:
                chunks.append(Chunk(
                    chunk_id=f"{slug}_structure_{idx}",
                    source=source, title=title, section=section,
                    strategy="structure", index=idx, text=node_text,
                ))
                idx += 1

        return chunks
