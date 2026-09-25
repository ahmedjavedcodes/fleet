"""In-memory VectorStore with Pinecone's metadata-filter semantics, so memory
tests exercise real filter construction and ranking without the network.
tests/test_pinecone_live.py checks these same semantics against real Pinecone."""

from __future__ import annotations

import math
from typing import Any


def _cmp(value: Any, condition: Any) -> bool:
    if not isinstance(condition, dict):
        return value == condition
    for op, operand in condition.items():
        if op == "$eq" and not value == operand:
            return False
        if op == "$ne" and not value != operand:
            return False
        if op == "$in" and value not in operand:
            return False
        if op == "$nin" and value in operand:
            return False
        if op in ("$lt", "$lte", "$gt", "$gte"):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False
            if (op == "$lt" and not value < operand) or (op == "$lte" and not value <= operand) or \
               (op == "$gt" and not value > operand) or (op == "$gte" and not value >= operand):
                return False
    return True


def matches(metadata: dict[str, Any], filters: dict[str, Any] | None) -> bool:
    if not filters:
        return True
    for key, condition in filters.items():
        if key == "$and":
            if not all(matches(metadata, clause) for clause in condition):
                return False
        elif key == "$or":
            if not any(matches(metadata, clause) for clause in condition):
                return False
        elif key not in metadata:
            # Pinecone: a missing field never satisfies $eq/$in/$lt..., but does satisfy $ne/$nin.
            if not (isinstance(condition, dict) and set(condition) <= {"$ne", "$nin"}):
                return False
        elif not _cmp(metadata[key], condition):
            return False
    return True


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _sparse_dot(a: dict | None, b: dict | None) -> float:
    if not a or not b:
        return 0.0
    weights = dict(zip(b["indices"], b["values"]))
    return sum(v * weights.get(i, 0.0) for i, v in zip(a["indices"], a["values"]))


class FakeVectorStore:
    """metric="cosine" mirrors fleet-memory; metric="dotproduct" mirrors
    fleet-documents, where a hybrid query scores dense_dot + sparse_dot."""

    def __init__(self, metric: str = "cosine") -> None:
        self.metric = metric
        self.namespaces: dict[str, dict[str, dict[str, Any]]] = {}
        self.calls: list[tuple[str, Any]] = []
        self.fail_next: int = 0  # simulate outages: the next N calls raise

    def _maybe_fail(self, op: str) -> None:
        self.calls.append((op, None))
        if self.fail_next:
            self.fail_next -= 1
            raise ConnectionError(f"simulated Pinecone outage during {op}")

    def records(self, namespace: str) -> dict[str, dict[str, Any]]:
        return self.namespaces.setdefault(namespace, {})

    def query(self, vector, top_k, filters, namespace, *, sparse_vector=None):
        self._maybe_fail("query")
        if sparse_vector is not None and self.metric != "dotproduct":
            raise ValueError("sparse queries require a dotproduct index")  # real Pinecone rejects these too

        def score(rec):
            if self.metric == "dotproduct":
                return _dot(vector, rec["values"]) + _sparse_dot(sparse_vector, rec.get("sparse_values"))
            return _cosine(vector, rec["values"])

        scored = [
            {"id": vid, "score": score(rec), "metadata": dict(rec["metadata"])}
            for vid, rec in self.records(namespace).items()
            if matches(rec["metadata"], filters)
        ]
        return sorted(scored, key=lambda m: m["score"], reverse=True)[:top_k]

    def upsert(self, vectors, namespace):
        self._maybe_fail("upsert")
        for item in vectors:
            self.records(namespace)[item["id"]] = {
                "values": list(item["values"]),
                "sparse_values": item.get("sparse_values"),
                "metadata": dict(item["metadata"]),
            }

    def update_metadata(self, filters, set_metadata, namespace):
        self._maybe_fail("update_metadata")
        for rec in self.records(namespace).values():
            if matches(rec["metadata"], filters):
                rec["metadata"].update(set_metadata)

    def delete(self, filters, namespace):
        self._maybe_fail("delete")
        store = self.records(namespace)
        for vid in [v for v, rec in store.items() if matches(rec["metadata"], filters)]:
            del store[vid]

    def fetch(self, ids, organization_id, namespace):
        self._maybe_fail("fetch")
        store = self.records(namespace)
        return {vid: list(store[vid]["values"]) for vid in ids if vid in store}
