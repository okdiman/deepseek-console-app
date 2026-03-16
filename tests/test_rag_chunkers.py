"""Tests for FixedSizeChunker and StructureChunker."""

import pytest

from deepseek_chat.core.rag.chunkers import Chunk, FixedSizeChunker, StructureChunker

# ── Fixtures ──────────────────────────────────────────────────────────────

MARKDOWN_TEXT = """\
# Document Title

Intro paragraph before any heading.

## Section One

Content of section one. This is a fairly long paragraph that contains
multiple sentences to ensure we have enough text for testing purposes.

### Subsection 1.1

Subsection content here.

## Section Two

Content of section two. Another paragraph with enough text to be meaningful.
"""

PYTHON_TEXT = """\
import os
from typing import List

CONSTANT = "hello"


def standalone_function(x: int) -> int:
    return x * 2


class MyClass:
    def __init__(self, value: int) -> None:
        self.value = value

    def method_a(self) -> str:
        return str(self.value)

    def method_b(self) -> int:
        return self.value * 10
"""


# ── FixedSizeChunker ──────────────────────────────────────────────────────

class TestFixedSizeChunker:
    def test_empty_text_returns_empty(self):
        c = FixedSizeChunker()
        assert c.chunk("", "file.md", "Title") == []

    def test_whitespace_only_returns_empty(self):
        c = FixedSizeChunker()
        assert c.chunk("   \n\n  ", "file.md", "Title") == []

    def test_short_text_single_chunk(self):
        c = FixedSizeChunker(chunk_size=400, overlap=50)
        chunks = c.chunk("Hello world.", "test.md", "Test")
        assert len(chunks) == 1

    def test_chunk_returns_chunk_objects(self):
        c = FixedSizeChunker(chunk_size=50, overlap=10)
        chunks = c.chunk(MARKDOWN_TEXT, "test.md", "Test Doc")
        assert all(isinstance(ch, Chunk) for ch in chunks)

    def test_strategy_field_is_fixed(self):
        c = FixedSizeChunker()
        chunks = c.chunk(MARKDOWN_TEXT, "test.md", "Test")
        assert all(ch.strategy == "fixed" for ch in chunks)

    def test_section_is_always_empty(self):
        c = FixedSizeChunker()
        chunks = c.chunk(MARKDOWN_TEXT, "test.md", "Test")
        assert all(ch.section == "" for ch in chunks)

    def test_chunk_id_format(self):
        c = FixedSizeChunker(chunk_size=50, overlap=5)
        chunks = c.chunk("word " * 200, "path/to/file.md", "Title")
        assert chunks[0].chunk_id.endswith("_fixed_0")
        assert chunks[1].chunk_id.endswith("_fixed_1")

    def test_chunk_ids_are_unique(self):
        c = FixedSizeChunker(chunk_size=50, overlap=5)
        chunks = c.chunk("word " * 200, "file.md", "Title")
        ids = [ch.chunk_id for ch in chunks]
        assert len(ids) == len(set(ids))

    def test_overlap_produces_more_chunks_than_no_overlap(self):
        text = "word " * 300
        c_overlap = FixedSizeChunker(chunk_size=100, overlap=50)
        c_no_overlap = FixedSizeChunker(chunk_size=100, overlap=0)
        assert len(c_overlap.chunk(text, "f.md", "T")) > len(c_no_overlap.chunk(text, "f.md", "T"))

    def test_source_and_title_preserved(self):
        c = FixedSizeChunker()
        chunks = c.chunk("Some text.", "my/source.md", "My Title")
        assert chunks[0].source == "my/source.md"
        assert chunks[0].title == "My Title"

    def test_index_is_sequential(self):
        c = FixedSizeChunker(chunk_size=50, overlap=5)
        chunks = c.chunk("word " * 300, "f.md", "T")
        assert [ch.index for ch in chunks] == list(range(len(chunks)))


# ── StructureChunker — Markdown ───────────────────────────────────────────

class TestStructureChunkerMarkdown:
    def test_empty_text_returns_empty(self):
        c = StructureChunker()
        assert c.chunk("", "file.md", "Title") == []

    def test_splits_on_h2_headings(self):
        c = StructureChunker(max_tokens=800)
        chunks = c.chunk(MARKDOWN_TEXT, "doc.md", "Doc")
        sections = [ch.section for ch in chunks]
        assert "Section One" in sections
        assert "Section Two" in sections

    def test_section_field_populated(self):
        c = StructureChunker()
        chunks = c.chunk(MARKDOWN_TEXT, "doc.md", "Doc")
        chunks_with_section = [ch for ch in chunks if ch.section]
        assert len(chunks_with_section) > 0

    def test_strategy_field_is_structure(self):
        c = StructureChunker()
        chunks = c.chunk(MARKDOWN_TEXT, "doc.md", "Doc")
        assert all(ch.strategy == "structure" for ch in chunks)

    def test_chunk_ids_are_unique(self):
        c = StructureChunker()
        chunks = c.chunk(MARKDOWN_TEXT, "doc.md", "Doc")
        ids = [ch.chunk_id for ch in chunks]
        assert len(ids) == len(set(ids))

    def test_preamble_chunk_has_empty_section(self):
        c = StructureChunker()
        chunks = c.chunk(MARKDOWN_TEXT, "doc.md", "Doc")
        # First chunk should be the preamble (before ## Section One)
        assert chunks[0].section == ""

    def test_h3_subsection_captured(self):
        c = StructureChunker()
        chunks = c.chunk(MARKDOWN_TEXT, "doc.md", "Doc")
        sections = [ch.section for ch in chunks]
        assert "Subsection 1.1" in sections

    def test_no_markdown_returns_single_chunk(self):
        c = StructureChunker(max_tokens=800)
        text = "Just plain text with no headings at all."
        chunks = c.chunk(text, "plain.md", "Plain")
        assert len(chunks) == 1

    def test_oversized_section_is_sub_chunked(self):
        # Create a section larger than max_tokens
        big_section = "## Big Section\n\n" + "word " * 2000
        c = StructureChunker(max_tokens=50)
        chunks = c.chunk(big_section, "big.md", "Big")
        # Should produce multiple chunks, all with the same section
        big_chunks = [ch for ch in chunks if ch.section == "Big Section"]
        assert len(big_chunks) > 1


# ── StructureChunker — Python ─────────────────────────────────────────────

class TestStructureChunkerPython:
    def test_splits_on_class_definition(self):
        c = StructureChunker()
        chunks = c.chunk(PYTHON_TEXT, "module.py", "Module")
        sections = [ch.section for ch in chunks]
        assert "MyClass" in sections

    def test_splits_on_function_definition(self):
        c = StructureChunker()
        chunks = c.chunk(PYTHON_TEXT, "module.py", "Module")
        sections = [ch.section for ch in chunks]
        assert "standalone_function" in sections

    def test_module_header_chunk_exists(self):
        c = StructureChunker()
        chunks = c.chunk(PYTHON_TEXT, "module.py", "Module")
        assert any(ch.section == "module header" for ch in chunks)

    def test_large_class_split_into_methods(self):
        # Force small max_tokens so class is split into methods
        c = StructureChunker(max_tokens=30)
        chunks = c.chunk(PYTHON_TEXT, "module.py", "Module")
        method_sections = [ch.section for ch in chunks if "." in ch.section]
        assert len(method_sections) > 0

    def test_method_section_format(self):
        c = StructureChunker(max_tokens=30)
        chunks = c.chunk(PYTHON_TEXT, "module.py", "Module")
        method_sections = [ch.section for ch in chunks if "." in ch.section]
        assert any(s.startswith("MyClass.") for s in method_sections)

    def test_strategy_field_is_structure(self):
        c = StructureChunker()
        chunks = c.chunk(PYTHON_TEXT, "module.py", "Module")
        assert all(ch.strategy == "structure" for ch in chunks)

    def test_invalid_python_falls_back_to_fixed(self):
        c = StructureChunker()
        bad_python = "def broken syntax !!!"
        chunks = c.chunk(bad_python, "bad.py", "Bad")
        # Falls back to fixed chunker — should still return chunks
        assert len(chunks) > 0

    def test_unknown_extension_falls_back(self):
        c = StructureChunker()
        chunks = c.chunk("some content", "file.txt", "Text File")
        assert len(chunks) > 0
