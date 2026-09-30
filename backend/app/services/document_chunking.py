"""Chunking (hybrid-document-rag-pipeline.md §2.3).

Text is split with the algorithm of LangChain's RecursiveCharacterTextSplitter -- paragraphs first, then lines, then
sentences, then words -- into SMALL chunks (350 characters, with 50 of overlap), implemented here in ~70 lines rather
than pulling LangChain into the backend just for it. The earlier embedding-based "semantic" splitter produced chunks
of up to 2,000 characters: a whole page, so a question about accident reporting came back with the tyre pressure table
beside it, and the model pasted it all. A chunk now holds roughly one fact.

Each chunk after the first in a run starts with the tail of the one before it (about 50 characters, from a sentence
start when there is one), so a fact that straddles a boundary is whole in at least one chunk.

Small chunks lose their surroundings, so each one carries the heading of the section it sits in ("2.0 Company
Incident Protocols › Mandatory Incident Reporting Timelines"): that keeps a stray sentence retrievable and lets an
answer cite its section. Headings come from the PDF's fonts (services/document_extraction.py), or from the text itself
for plain-text documents. Sections are split separately, so a chunk never spans two of them and the overlap never
bridges unrelated topics.

Tables never go through the splitter: each table unit (summary, or Markdown fallback) becomes exactly one chunk, so a
table is never cut in half.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.document_extraction import (
    BODY,
    MAJOR_HEADING,
    PAGE_FURNITURE,
    SUB_HEADING,
    Unit,
    is_heading,
    is_numbered_heading,
)

CHUNK_SIZE = 350
CHUNK_OVERLAP = 50
MIN_SECTION_CHUNK = 120  # a long heading never squeezes the body below this

# (how to find a boundary, what to join pieces with when they are merged back together), coarsest first.
_SEPARATORS: list[tuple[str, str]] = [
    (r"\n\n", "\n\n"),
    (r"\n", "\n"),
    (r"(?<=[.!?])\s+", " "),  # sentence end; the punctuation stays with its sentence
    (r" ", " "),
    ("", ""),
]
_SENTENCE_GAP = re.compile(r"(?<=[.!?])\s+")


def _split_on(text: str, pattern: str) -> list[str]:
    if pattern == "":
        return list(text)
    return [piece for piece in re.split(pattern, text) if piece]


def _merge(pieces: list[str], joiner: str, chunk_size: int) -> list[str]:
    """Greedily packs pieces into chunks of at most chunk_size."""
    chunks: list[str] = []
    current: list[str] = []
    total = 0
    for piece in pieces:
        extra = len(joiner) if current else 0
        if current and total + len(piece) + extra > chunk_size:
            chunk = joiner.join(current).strip()
            if chunk:
                chunks.append(chunk)
            current, total = [], 0
            extra = 0
        current.append(piece)
        total += len(piece) + extra
    chunk = joiner.join(current).strip()
    if chunk:
        chunks.append(chunk)
    return chunks


def _split(text: str, chunk_size: int, level: int = 0) -> list[str]:
    if not text.strip():
        return []
    if len(text) <= chunk_size:
        return [text.strip()]
    while level < len(_SEPARATORS) - 1 and not re.search(_SEPARATORS[level][0], text):
        level += 1
    pattern, joiner = _SEPARATORS[level]

    chunks: list[str] = []
    small: list[str] = []
    for piece in _split_on(text, pattern):
        if len(piece) <= chunk_size:
            small.append(piece)
            continue
        if small:
            chunks.extend(_merge(small, joiner, chunk_size))
            small = []
        chunks.extend(_split(piece, chunk_size, level + 1))
    if small:
        chunks.extend(_merge(small, joiner, chunk_size))
    return chunks


def _tail(previous: str, limit: int) -> str:
    """The end of `previous`, at most `limit` characters, starting at a sentence start if there is one in range,
    otherwise at a word boundary (never mid-word); empty when `previous` is no longer than that."""
    if len(previous) <= limit:
        return ""
    tail = previous[-limit:]
    gap = _SENTENCE_GAP.search(tail)
    if gap:
        return tail[gap.end():].strip()
    if not previous[-limit - 1].isspace():  # the cut landed inside a word: drop the fragment
        _, _, tail = tail.partition(" ")
    return tail.strip()


def recursive_split(text: str, chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Splits `text` into chunks of at most `chunk_size` characters, each (after the first) beginning with up to
    `chunk_overlap` characters of the chunk before it."""
    text = text.strip()
    if len(text) <= chunk_size:
        return [text] if text else []
    overlap = max(0, min(chunk_overlap, chunk_size // 4))
    pieces = _split(text, chunk_size - overlap - 1)
    if overlap == 0 or len(pieces) < 2:
        return pieces
    return [pieces[0]] + [f"{tail} {piece}" if tail else piece for previous, piece in zip(pieces, pieces[1:], strict=False) for tail in [_tail(previous, overlap)]]


# --- section headings ---------------------------------------------------------------------------------------------

MAX_PREFIX_CHARS = 90  # a breadcrumb longer than this is cut back to its innermost heading


def _classify(unit: Unit) -> tuple[int, str]:
    """(level, text) of a text unit: a heading (MAJOR_HEADING / SUB_HEADING) and its own text, or BODY and the text."""
    if unit.heading in (MAJOR_HEADING, SUB_HEADING):
        return unit.heading, " ".join(unit.text.split())
    if unit.heading is None:  # no font information: plain text; a heading line may open the unit
        first, _, rest = unit.text.strip().partition("\n")
        if is_heading(first):
            level = MAJOR_HEADING if is_numbered_heading(first) else SUB_HEADING
            return level, " ".join(first.split()) + "\n" + " ".join(rest.split())
    return BODY, " ".join(unit.text.split())


def _breadcrumb(major: str | None, sub: str | None) -> str | None:
    parts = [h for h in (major, sub) if h]
    if not parts:
        return None
    crumb = " › ".join(parts)  # not ">": the agent's context escapes HTML, and the model would quote "&gt;" back
    return crumb if len(crumb) <= MAX_PREFIX_CHARS else parts[-1][:MAX_PREFIX_CHARS]


@dataclass(frozen=True)
class Chunk:
    embed_text: str  # what the dense/sparse vectors are computed from
    text: str  # what is stored and returned to the agent


@dataclass
class _Section:
    heading: str | None
    paragraphs: list[str]


def _section_chunks(section: _Section, chunk_size: int, chunk_overlap: int) -> list[str]:
    body = "\n\n".join(p for p in section.paragraphs if p)
    if not body:
        return []
    heading = section.heading
    if not heading:
        return recursive_split(body, chunk_size, chunk_overlap)
    size = max(MIN_SECTION_CHUNK, chunk_size - len(heading) - 1)
    return [f"{heading}\n{piece}" for piece in recursive_split(body, size, chunk_overlap)]


def build_chunks(
    units: list[Unit],
    table_texts: dict[int, tuple[str, str]],
    *,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[Chunk]:
    """units in reading order; table_texts maps a table unit's index to its (embed_text, text) pair from
    table_summarizer. Text units are grouped into sections (a heading starts a new one) and each section is split
    into small overlapping chunks that carry its heading; each table is exactly one chunk."""
    chunks: list[Chunk] = []
    major: str | None = None
    sub: str | None = None
    section = _Section(heading=None, paragraphs=[])
    headings: list[str] = []  # last resort: a document made of headings alone still yields something to search

    def start_section() -> None:
        nonlocal section
        section = _Section(heading=_breadcrumb(major, sub), paragraphs=[])

    def flush() -> None:
        for piece in _section_chunks(section, chunk_size, chunk_overlap):
            chunks.append(Chunk(embed_text=piece, text=piece))
        start_section()

    for index, unit in enumerate(units):
        if unit.kind == "table":
            flush()
            embed_text, text = table_texts.get(index, (unit.markdown, unit.markdown))
            context = unit.context.strip().lstrip(".,;: ")
            if context and embed_text.strip() == unit.markdown.strip():
                # No summary (none was asked for, or the cap was reached): the text the extraction folded into the
                # table ("...any attempt to use the card elsewhere will be declined") would otherwise be lost.
                embed_text = text = f"{context}\n\n{text}"
            # A sentence the PDF split across blocks can leave a stray ". " at the start of the folded-in text.
            embed_text, text = embed_text.lstrip(".,;: \n"), text.lstrip(".,;: \n")
            crumb = _breadcrumb(major, sub)
            if crumb:  # a table belongs to its section like any other passage
                embed_text, text = f"{crumb}\n{embed_text}", f"{crumb}\n{text}"
            chunks.append(Chunk(embed_text=embed_text, text=text))
            continue
        if PAGE_FURNITURE.match(" ".join(unit.text.split())):
            continue
        level, text = _classify(unit)
        if level in (MAJOR_HEADING, SUB_HEADING):
            heading, _, body = text.partition("\n")  # plain text may carry the paragraph after its heading line
            flush()
            headings.append(heading)
            if level == MAJOR_HEADING:
                major, sub = heading, None
            else:
                sub = heading
            start_section()
            if body:
                section.paragraphs.append(body)
        elif text:
            section.paragraphs.append(text)
    flush()
    if not chunks:
        chunks = [Chunk(embed_text=h, text=h) for h in headings]
    return [c for c in chunks if c.text.strip()]
