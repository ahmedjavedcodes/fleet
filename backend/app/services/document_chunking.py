"""Semantic chunking (hybrid-document-rag-pipeline.md §2.3).

Same algorithm as LangChain's SemanticChunker (percentile breakpoints over
adjacent-sentence embedding distance), implemented here in ~40 lines rather
than pulling langchain_experimental + LangChain into the backend just for it.
Sentence embeddings are batched (one inference call per 96 sentences).

Tables never go through the splitter: each table unit (summary, or Markdown
fallback) becomes exactly one chunk, so a table is never cut in half.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Callable

from app.services.document_extraction import Unit

BREAKPOINT_PERCENTILE = 95.0
MAX_CHUNK_CHARS = 2_000

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.split(" ".join(text.split())) if s.strip()]


def _cosine_distance(a: list[float], b: list[float]) -> float:
    dot = math.fsum(x * y for x, y in zip(a, b))
    norm = math.sqrt(math.fsum(x * x for x in a)) * math.sqrt(math.fsum(y * y for y in b))
    return 1.0 - (dot / norm if norm else 0.0)


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    rank = (pct / 100.0) * (len(ordered) - 1)
    low, high = math.floor(rank), math.ceil(rank)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def semantic_split(
    sentences: list[str],
    embed: Callable[[list[str]], list[list[float]]],
    *,
    percentile: float = BREAKPOINT_PERCENTILE,
    max_chars: int = MAX_CHUNK_CHARS,
) -> list[str]:
    if len(sentences) <= 2:
        return [" ".join(sentences)] if sentences else []
    vectors = embed(sentences)
    distances = [_cosine_distance(vectors[i], vectors[i + 1]) for i in range(len(sentences) - 1)]
    threshold = _percentile(distances, percentile)

    chunks: list[str] = []
    current: list[str] = [sentences[0]]
    for i, sentence in enumerate(sentences[1:]):
        topic_shift = distances[i] > threshold
        too_long = len(" ".join(current)) + len(sentence) + 1 > max_chars
        if topic_shift or too_long:
            chunks.append(" ".join(current))
            current = []
        current.append(sentence)
    chunks.append(" ".join(current))
    return chunks


@dataclass(frozen=True)
class Chunk:
    embed_text: str  # what the dense/sparse vectors are computed from
    text: str  # what is stored and returned to the agent


def build_chunks(
    units: list[Unit], table_texts: dict[int, tuple[str, str]], embed: Callable[[list[str]], list[list[float]]]
) -> list[Chunk]:
    """units in reading order; table_texts maps a table unit's index to its
    (embed_text, text) pair from table_summarizer. Runs of consecutive text
    units are split semantically; each table is exactly one chunk."""
    chunks: list[Chunk] = []
    pending_text: list[str] = []

    def flush() -> None:
        if pending_text:
            for piece in semantic_split(split_sentences(" ".join(pending_text)), embed):
                chunks.append(Chunk(embed_text=piece, text=piece))
            pending_text.clear()

    for index, unit in enumerate(units):
        if unit.kind == "table":
            flush()
            embed_text, text = table_texts.get(index, (unit.markdown, unit.markdown))
            chunks.append(Chunk(embed_text=embed_text, text=text))
        else:
            pending_text.append(unit.text)
    flush()
    return [c for c in chunks if c.text.strip()]
