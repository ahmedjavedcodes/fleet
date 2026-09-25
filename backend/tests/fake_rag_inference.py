"""Deterministic stand-in for Pinecone Inference: hashed bag-of-words dense
vectors, token sparse vectors, and a term-overlap "cross-encoder". Enough
signal that relevant chunks outrank irrelevant ones, with zero network."""

from __future__ import annotations

import hashlib
import math
import re

DIM = 768
_STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are", "be", "at", "by", "with",
         "what", "how", "when", "should", "does", "do", "we", "our", "must", "every", "this", "that", "it"}


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOP]


def _slot(token: str) -> int:
    return int(hashlib.md5(token.encode()).hexdigest(), 16) % DIM


class FakeRagInference:
    def __init__(self, *, rerank_fail: bool = False) -> None:
        self.calls: list[tuple[str, int]] = []
        self.rerank_fail = rerank_fail

    def embed_dense(self, texts, input_type):
        self.calls.append(("dense", len(texts)))
        vectors = []
        for text in texts:
            vec = [0.0] * DIM
            for t in tokens(text):
                vec[_slot(t)] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return vectors

    def embed_sparse(self, texts, input_type):
        self.calls.append(("sparse", len(texts)))
        out = []
        for text in texts:
            counts: dict[int, float] = {}
            for t in tokens(text):
                counts[_slot(t)] = counts.get(_slot(t), 0.0) + 1.0
            out.append({"indices": list(counts), "values": list(counts.values())})
        return out

    def rerank(self, query, documents):
        self.calls.append(("rerank", len(documents)))
        if self.rerank_fail:
            raise ConnectionError("reranker down")
        q = set(tokens(query))
        return [(i, len(q & set(tokens(d))) / len(q) if q else 0.0) for i, d in enumerate(documents)]
