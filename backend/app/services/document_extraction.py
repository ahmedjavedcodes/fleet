"""Spatial PDF extraction (hybrid-document-rag-pipeline.md §2.1).

Plain text extraction flattens tables into interleaved cell soup. Instead,
tables and text blocks are extracted separately with their coordinates and
reassembled in reading order:

- every table's box is expanded upward by CONTEXT_EXPANSION_PT to capture
  the heading/intro sentence that explains it (the spec says "60 pixels";
  PDF coordinates are points, so it is 60pt);
- text blocks overlapping an expanded table box are folded into that table
  as its context rather than emitted twice;
- everything is sorted by (page, y0, x0);
- the structure is recovered from the fonts (`structure_units`): headings are the lines set larger than the body
  text, and the wrapped lines of a paragraph -- which many PDFs store as one block each -- are stitched back into
  paragraphs, so chunking sees sections and paragraphs, not a stream of lines.

`assemble_blocks`, `structure_units` and `is_heading` are pure (no PDF needed), so the ordering/dedupe and the
heading/paragraph rules are unit-testable with synthetic coordinates and sizes.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Literal

CONTEXT_EXPANSION_PT = 60.0

# What a text unit is, when the PDF's fonts say so (None = unknown: plain text, or no font information).
BODY, MAJOR_HEADING, SUB_HEADING, TITLE = 0, 1, 2, 3
TITLE_RATIO = 1.9  # set at least this many times larger than the body text: the document's title
HEADING_RATIO = 1.35  # ...at least this much larger (and short): a major heading ("1.0 Toyota Hilux Specifications")
MAX_HEADING_CHARS = 80
MAX_LARGE_HEADING_CHARS = 120
PARAGRAPH_GAP = 0.6  # a line closer than this fraction of a line's height below the last one continues its paragraph

_NUMBERED_HEADING = re.compile(r"^\d+\.\d+(?:\.\d+)*[.)]?\s+\S")
_PAGE_MARKER = re.compile(r"\bpage\s+\d+\b", re.IGNORECASE)
_SENTENCE_END = re.compile(r"[.,;:!?]$")
_ENDS_SENTENCE = re.compile(r"[.!?][\"')\]]*$")
# A running header or footer such as "Fleet Operations & Maintenance Manual Page 1 of 2": on every page, never content.
PAGE_FURNITURE = re.compile(r"^(?:.{0,80}\s)?page\s+\d+(?:\s+of\s+\d+)?$", re.IGNORECASE)


def is_numbered_heading(line: str) -> bool:
    return bool(_NUMBERED_HEADING.match(line.strip()))


def is_heading(line: str) -> bool:
    """A short line that names a section: numbered ("2.0 Incident Protocols") or Title Case ("Standard Tyre Pressure
    Guidelines"), and not a sentence, a label ("Heavy Cargo:"), a page footer or a bare number."""
    line = line.strip()
    if not line or len(line) > MAX_HEADING_CHARS or _SENTENCE_END.search(line) or _PAGE_MARKER.search(line):
        return False
    if not re.search(r"[A-Za-z]", line) or "|" in line or ":" in line:  # "Label: value" and metadata lines are not headings
        return False
    if is_numbered_heading(line):
        return True
    words = line.split()
    content_words = [w for w in words if len(w) > 3 and re.search(r"[A-Za-z]", w)]
    return 2 <= len(words) <= 8 and bool(content_words) and all(w[0].isupper() for w in content_words)


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
    size: float = 0.0  # the largest font size in the block, in points (0 = unknown)


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
    y1: float = 0.0
    size: float = 0.0
    heading: int | None = None  # BODY / MAJOR_HEADING / SUB_HEADING / TITLE, or None when not known


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
            Unit(
                kind="table", page=table.page, y0=expanded.y0, text=table.markdown, context=context, markdown=table.markdown,
                y1=table.box.y1,
            )
        )
    for i, block in enumerate(text_blocks):
        if i not in consumed and block.text.strip():
            units.append(
                Unit(kind="text", page=block.page, y0=block.box.y0, text=block.text.strip(), y1=block.box.y1, size=block.size)
            )
    return sorted(units, key=lambda u: (u.page, u.y0))


def _body_size(units: list[Unit]) -> float:
    """The font size most of the text is set in, weighted by how much text there is."""
    weight: Counter[float] = Counter()
    for unit in units:
        weight[round(unit.size, 1)] += len(unit.text)
    return weight.most_common(1)[0][0]


def _join(previous: str, following: str) -> str:
    previous, following = previous.rstrip(), following.strip()
    return previous + following if following[:1] in ".,;:!?" else previous + " " + following


def structure_units(units: list[Unit]) -> list[Unit]:
    """Recovers headings and paragraphs from font sizes.

    Text set much larger than the body text is a heading (or, at twice the size, the document's title); a short
    standalone Title-Case line at about body size is a sub-heading. Lines that continue a sentence, end in a colon
    ("Heavy Cargo:" labelling the text after it), or sit right under the last line are joined into one paragraph:
    many PDFs store every wrapped line as a block of its own. Does nothing when no font sizes are known."""
    sized = [u for u in units if u.kind == "text" and u.size > 0]
    if not sized:
        return units
    # A running header/footer ("... Page 1 of 2") is on every page and never content: gone before anything is joined.
    units = [u for u in units if not (u.kind == "text" and PAGE_FURNITURE.match(" ".join(u.text.split())))]
    sized = [u for u in units if u.kind == "text" and u.size > 0]
    if not sized:
        return units
    body = _body_size(sized)

    classified: list[Unit] = []
    for unit in units:
        if unit.kind != "text" or unit.size <= 0:
            classified.append(unit)
            continue
        text = " ".join(unit.text.split())
        ratio = unit.size / body
        if ratio >= TITLE_RATIO:
            level = TITLE
        elif ratio >= HEADING_RATIO and len(text) <= MAX_LARGE_HEADING_CHARS:
            level = MAJOR_HEADING
        elif ratio >= 0.98 and "\n" not in unit.text.strip() and is_heading(text):
            level = SUB_HEADING
        else:
            level = BODY
        classified.append(replace(unit, heading=level))

    merged: list[Unit] = []
    line_height = 0.0  # the height of the last fragment joined on: a wrapped line, not the whole paragraph so far
    for unit in classified:
        last = merged[-1] if merged else None
        if (
            last is not None
            and unit.kind == "text" and last.kind == "text"
            and unit.heading == BODY and last.heading == BODY
            and unit.page == last.page
            and abs(unit.size - last.size) <= 0.15 * body  # set in the same type: not a footnote or a caption
            and (
                not _ENDS_SENTENCE.search(last.text.rstrip())  # the sentence runs on
                or last.text.rstrip().endswith(":")
                or (line_height > 0 and unit.y0 - last.y1 <= PARAGRAPH_GAP * line_height)
            )
        ):
            merged[-1] = replace(last, text=_join(last.text, unit.text), y1=unit.y1)
        else:
            merged.append(unit)
        line_height = unit.y1 - unit.y0
    return merged


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
            for block in page.get_text("dict")["blocks"]:
                if block["type"] != 0:  # 1 = image block
                    continue
                lines = ["".join(span["text"] for span in line["spans"]) for line in block["lines"]]
                sizes = [span["size"] for line in block["lines"] for span in line["spans"] if span["text"].strip()]
                text = "\n".join(lines)
                if text.strip():
                    text_blocks.append(TextBlock(page_number, Box(*block["bbox"]), text, size=max(sizes, default=0.0)))
    return structure_units(assemble_blocks(text_blocks, tables))


def extract_text_units(text: str) -> list[Unit]:
    """Plain-text documents (e.g. a typed policy): paragraphs in order."""
    paragraphs = [p.strip() for p in text.replace("\r\n", "\n").split("\n\n")]
    return [Unit(kind="text", page=0, y0=float(i), text=p) for i, p in enumerate(paragraphs) if p]
