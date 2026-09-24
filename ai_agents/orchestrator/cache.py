"""Semantic & exact cache lookup pre-hook, per execution-pre_hooks.md §4.

Runs inside execute_tool, immediately after validate_tool_args succeeds,
before runner.run -- a hit bypasses the sub-agent runner entirely. Which
calls are even eligible is decided by the CALLER (graph.py's
_is_read_only_call): this module has no opinion on what "read-only" means
for a given agent, it only stores/returns strings keyed by (tool, args, org).

Two real infrastructure gaps, resolved rather than faked:

1. Tier 1 ("a fast in-memory store (e.g., Redis)"): no Redis dependency or
   service exists anywhere in this project (checked pyproject.toml and
   docker-compose.yml). "e.g." makes Redis an example, not a requirement --
   ExactCacheBackend is a real, working in-process dict+TTL store, which IS
   a fast in-memory store. A Redis-backed backend can be swapped in later
   via the same get/set interface without touching graph.py.

2. Tier 2 (semantic match via embeddings + Pinecone/FAISS): there is no
   embedding-generation pipeline wired into this cache (agent memory's
   embedders live in memory/embeddings.py and target the backend's
   Pinecone-backed memory vault, not tool-call caching). Faking "semantic
   similarity" with a crude token-overlap heuristic would risk a false
   cache hit across two DIFFERENT vehicles/drivers, which is worse than no
   Tier 2 at all. NullSemanticCacheBackend is an honest, always-miss no-op;
   SemanticCacheBackend is a real Protocol ready for whoever wires up an
   embedding provider.

Extended per execution-post_hooks.md §2 ("Fresh Data" hook) with tag-based
invalidation: every stored entry is tagged with its own (tool_name, org_id)
namespace, and invalidate_namespace() additionally always purges the
`insights` namespace for that org, since Insights aggregates fleet-wide
data touching every other agent's writes -- matching AC 1's own example
("flushes all cached fuel AND insights queries") generalized to every
agent, not just fuel.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel


class CacheConfig(BaseModel):
    enabled_tools: frozenset[str] = frozenset({"insights", "foundation", "fuel"})
    ttl_seconds: int = 300  # 5 minutes for dashboard reads
    semantic_threshold: float = 0.95


DEFAULT_CACHE_CONFIG = CacheConfig()


def _cache_key(tool_name: str, validated_args: dict[str, Any], organization_id: str) -> str:
    payload = json.dumps({"tool": tool_name, "args": validated_args, "org": organization_id}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _namespace(tool_name: str, organization_id: str) -> str:
    return f"{tool_name}:{organization_id}"


@dataclass
class _CacheEntry:
    observation: str
    expires_at: float
    namespace: str = ""


class ExactCacheBackend:
    """In-process dict + TTL -- see module docstring point 1.

    Each entry is tagged with its (tool_name, org_id) namespace so a write
    can purge every read cached under that namespace without knowing their
    SHA-256 keys -- see invalidate_namespace, execution-post_hooks.md §2.
    """

    def __init__(self) -> None:
        self._store: dict[str, _CacheEntry] = {}

    def get(self, key: str) -> str | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.monotonic() >= entry.expires_at:
            del self._store[key]
            return None
        return entry.observation

    def set(self, key: str, observation: str, *, ttl_seconds: int, namespace: str = "") -> None:
        self._store[key] = _CacheEntry(
            observation=observation, expires_at=time.monotonic() + ttl_seconds, namespace=namespace
        )

    def invalidate_namespace(self, namespace: str) -> None:
        for key in [k for k, entry in self._store.items() if entry.namespace == namespace]:
            del self._store[key]


class SemanticCacheBackend(Protocol):
    def query(self, tool_name: str, raw_args: dict[str, Any], organization_id: str, *, threshold: float) -> str | None: ...
    def store(self, tool_name: str, raw_args: dict[str, Any], organization_id: str, observation: str) -> None: ...


class NullSemanticCacheBackend:
    """Honest no-op -- see module docstring point 2. Always a miss; never raises."""

    def query(self, tool_name: str, raw_args: dict[str, Any], organization_id: str, *, threshold: float) -> str | None:
        return None

    def store(self, tool_name: str, raw_args: dict[str, Any], organization_id: str, observation: str) -> None:
        return None


class ExecutionCache:
    """Stateful, per-orchestrator-session cache -- held on OrchestratorDeps
    the same way SubAgentRunner/FleetLiveObserver are. The spec's own
    Integration Blueprint sketches `check_cache(...)` as a bare function,
    but a bare function can't hold the TTL store across hops without a
    hidden module-level global (which would leak between unrelated
    sessions/orgs in the same process) -- a class instance, injected like
    everything else in this codebase, avoids that."""

    def __init__(
        self,
        *,
        config: CacheConfig | None = None,
        exact_backend: ExactCacheBackend | None = None,
        semantic_backend: SemanticCacheBackend | None = None,
    ) -> None:
        self.config = config or DEFAULT_CACHE_CONFIG
        self.exact = exact_backend or ExactCacheBackend()
        self.semantic = semantic_backend or NullSemanticCacheBackend()

    def check(
        self, tool_name: str, validated_args: dict[str, Any], organization_id: str, *, raw_args: dict[str, Any] | None = None
    ) -> str | None:
        if tool_name not in self.config.enabled_tools:
            return None

        key = _cache_key(tool_name, validated_args, organization_id)
        hit = self.exact.get(key)
        if hit is not None:
            return hit

        hit = self.semantic.query(tool_name, raw_args or validated_args, organization_id, threshold=self.config.semantic_threshold)
        if hit is not None:
            # Promote a semantic hit into Tier 1 too, so an identical repeat
            # of THIS exact call is a Tier-1 hit next time.
            self.exact.set(key, hit, ttl_seconds=self.config.ttl_seconds, namespace=_namespace(tool_name, organization_id))
        return hit

    def store(
        self,
        tool_name: str,
        validated_args: dict[str, Any],
        organization_id: str,
        observation: str,
        *,
        raw_args: dict[str, Any] | None = None,
    ) -> None:
        if tool_name not in self.config.enabled_tools:
            return
        key = _cache_key(tool_name, validated_args, organization_id)
        self.exact.set(key, observation, ttl_seconds=self.config.ttl_seconds, namespace=_namespace(tool_name, organization_id))
        self.semantic.store(tool_name, raw_args or validated_args, organization_id, observation)

    def invalidate_namespace(self, tool_name: str, organization_id: str) -> None:
        """Write-aware invalidation, per execution-post_hooks.md §2.

        Purges the writing tool's own namespace, plus `insights` for the
        same org -- Insights aggregates fleet-wide data touching every
        other agent's writes, matching AC 1's example ("flushes all cached
        fuel AND insights queries") generalized to every agent, not just
        fuel. A no-op if `insights` itself was never cache-enabled/queried.
        """
        self.exact.invalidate_namespace(_namespace(tool_name, organization_id))
        if tool_name != "insights":
            self.exact.invalidate_namespace(_namespace("insights", organization_id))
