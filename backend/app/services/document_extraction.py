"""Spatial PDF extraction (hybrid-document-rag-pipeline.md §2.1).

Plain text extraction flattens tables into interleaved cell soup. Instead,
tables and text blocks are extracted separately with their coordinates and
reassembled in reading order:

- every table's box is expanded upward by CONTEXT_EXPANSION_PT to capture
  the heading/intro sentence that explains it (the spec says "60 pixels";
  PDF coordinates are points, so it is 60pt);
- text blocks overlapping an expanded table box are folded into that table
  as its context rather than emitted twice;
- everything is sorted by (page, y0, x0).

`assemble_blocks` is pure (no PDF needed) so the ordering/dedupe rules are
unit-testable with synthetic coordinates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

CONTEXT_EXPANSION_PT = 60.0


@dataclass
class Box:
    x0: float
    y0: float
    x1: float
    y1: float

    def overlaps(self, other: "Box") -> bool:
        return self.x0 < other.x1 and other.x0 < self.x1 and self.y0 < other.y1 and other.y0 < self.y1


@dataclass
class TextBlock:
    page: int
    box: Box
    text: str


@dataclass
class TableBlock:
    page: int
    box: Box
    markdown: str


@dataclass
class Unit:
    """One reading-order unit handed to chunking. Tables are atomic: a table
    unit is never split across chunks."""

    kind: Literal["text", "table"]
    page: int
    y0: float
    text: str
    context: str = ""
    markdown: str = field(default="", repr=False)


def assemble_blocks(text_blocks: list[TextBlock], tables: list[TableBlock]) -> list[Unit]:
    units: list[Unit] = []
    consumed: set[int] = set()
    for table in tables:
        expanded = Box(table.box.x0, max(0.0, table.box.y0 - CONTEXT_EXPANSION_PT), table.box.x1, table.box.y1)
        context_parts: list[str] = []
        for i, block in enumerate(text_blocks):
            if block.page != table.page or not block.box.overlaps(expanded):
                continue
            consumed.add(i)
            if block.box.y0 < table.box.y0:  # above the table: header / intro sentence
                context_parts.append(block.text.strip())
        context = " ".join(p for p in context_parts if p)
        units.append(
            Unit(kind="table", page=table.page, y0=expanded.y0, text=table.markdown, context=context, markdown=table.markdown)
        )
    for i, block in enumerate(text_blocks):
        if i not in consumed and block.text.strip():
            units.append(Unit(kind="text", page=block.page, y0=block.box.y0, text=block.text.strip()))
    return sorted(units, key=lambda u: (u.page, u.y0))


def extract_pdf_units(pdf_bytes: bytes) -> list[Unit]:
    import pymupdf

    text_blocks: list[TextBlock] = []
    tables: list[TableBlock] = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page_number, page in enumerate(doc):
            for table in page.find_tables().tables:
                markdown = table.to_markdown().strip()
                if markdown:
                    tables.append(TableBlock(page_number, Box(*table.bbox), markdown))
            for x0, y0, x1, y1, text, _block_no, block_type in page.get_text("blocks"):
                if block_type == 0:  # 1 = image block
                    text_blocks.append(TextBlock(page_number, Box(x0, y0, x1, y1), text))
    return assemble_blocks(text_blocks, tables)


def extract_text_units(text: str) -> list[Unit]:
    """Plain-text documents (e.g. a typed policy): paragraphs in order."""
    paragraphs = [p.strip() for p in text.replace("\r\n", "\n").split("\n\n")]
    return [Unit(kind="text", page=0, y0=float(i), text=p) for i, p in enumerate(paragraphs) if p]
