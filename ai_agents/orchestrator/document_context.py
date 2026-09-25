"""Prompt-injection defence for retrieved document chunks
(hybrid-document-rag-pipeline.md §4.1).

Three layers, weakest first:
1. Heuristic pre-scan -- a cheap signature sieve (the user-input injection
   patterns plus document-specific ones: role spoofing, tag break-out, tool
   hijacking). Flagged chunks are dropped. Not a guarantee.
2. XML sandboxing -- every surviving chunk is wrapped in
   <untrusted_document_context>, with its text and attributes XML-escaped, so
   no document can close the tag early and "escape" into the prompt. The
   spec's wrapping alone would let a chunk containing
   "</untrusted_document_context>" do exactly that.
3. The orchestrator's system prompt (graph.py) declares tagged text inert.
"""

from __future__ import annotations

import logging
import re
from html import escape

from orchestrator.security import _INJECTION_PATTERNS

logger = logging.getLogger("fleet.security")

_DOCUMENT_INJECTION_PATTERNS = [
    *_INJECTION_PATTERNS,
    re.compile(r"</?\s*untrusted_document_context", re.IGNORECASE),
    re.compile(r"^\s*(system|assistant|developer)\s*:", re.IGNORECASE | re.MULTILINE),
    re.compile(r"\b(new|updated|override|overriding)\s+(system\s+)?instructions?\b", re.IGNORECASE),
    re.compile(r"\b(call|invoke|use|run)\s+the\s+\w+\s+tool\b", re.IGNORECASE),
    re.compile(r"\bdo\s+not\s+(tell|inform|show)\s+the\s+user\b", re.IGNORECASE),
]

NULL_RESULT = (
    "search_documents: no document passage cleared the relevance threshold (null result). "
    "Tell the user the uploaded documents don't cover this; do not answer from general knowledge as if it were documented."
)


def looks_like_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in _DOCUMENT_INJECTION_PATTERNS)


def format_document_observation(results: list[dict]) -> str:
    """Scratchpad observation for a search_documents call."""
    safe = [r for r in results if not looks_like_injection(r.get("text", ""))]
    dropped = len(results) - len(safe)
    if dropped:
        logger.warning("search_documents: dropped %d chunk(s) matching injection signatures", dropped)
    if not safe:
        note = f" ({dropped} passage(s) were withheld by the injection filter.)" if dropped else ""
        return NULL_RESULT + note

    blocks = [
        '<untrusted_document_context source="{src}" type="{typ}" chunk="{idx}" relevance="{rel}">\n{body}\n</untrusted_document_context>'.format(
            src=escape(str(r.get("filename", "")), quote=True),
            typ=escape(str(r.get("document_type", "")), quote=True),
            idx=int(r.get("chunk_index", 0)),
            rel=round(float(r.get("relevance", 0.0)), 3),
            body=escape(str(r.get("text", "")), quote=False),
        )
        for r in safe
    ]
    header = f"search_documents returned {len(safe)} passage(s)"
    if dropped:
        header += f"; {dropped} more withheld by the injection filter"
    return header + ". Cite the source filename when you use them.\n" + "\n".join(blocks)
