import time

from orchestrator.cache import CacheConfig, ExactCacheBackend, ExecutionCache, NullSemanticCacheBackend


def test_exact_backend_miss_on_empty_store() -> None:
    backend = ExactCacheBackend()
    assert backend.get("some-key") is None


def test_exact_backend_set_then_get() -> None:
    backend = ExactCacheBackend()
    backend.set("k1", "observation text", ttl_seconds=60)
    assert backend.get("k1") == "observation text"


def test_exact_backend_expires_after_ttl() -> None:
    backend = ExactCacheBackend()
    backend.set("k1", "observation text", ttl_seconds=0)
    time.sleep(0.01)
    assert backend.get("k1") is None


def test_null_semantic_backend_always_misses() -> None:
    backend = NullSemanticCacheBackend()
    assert backend.query("insights", {}, "org-1", threshold=0.95) is None


def test_null_semantic_backend_store_does_not_raise() -> None:
    backend = NullSemanticCacheBackend()
    backend.store("insights", {}, "org-1", "some observation")  # must not raise


def test_ac3_second_identical_call_within_ttl_is_a_cache_hit() -> None:
    cache = ExecutionCache()
    args = {"query_entity": "dashboard_summary"}

    assert cache.check("insights", args, "org-1") is None  # first call: miss
    cache.store("insights", args, "org-1", "dashboard summary observation")

    hit = cache.check("insights", args, "org-1")  # second call, "2 minutes apart" per AC 3
    assert hit == "dashboard summary observation"


def test_disabled_tool_never_cached() -> None:
    cache = ExecutionCache(config=CacheConfig(enabled_tools=frozenset({"insights"})))
    args = {"query_entity": "maintenance_logs"}

    cache.store("maintenance", args, "org-1", "some observation")
    assert cache.check("maintenance", args, "org-1") is None


def test_different_organizations_do_not_share_cache_entries() -> None:
    cache = ExecutionCache()
    args = {"query_entity": "dashboard_summary"}

    cache.store("insights", args, "org-1", "org 1's data")
    assert cache.check("insights", args, "org-2") is None


def test_different_args_are_different_cache_keys() -> None:
    cache = ExecutionCache()
    cache.store("insights", {"query_entity": "dashboard_summary"}, "org-1", "summary data")
    assert cache.check("insights", {"query_entity": "fuel_trends"}, "org-1") is None


def test_semantic_hit_is_promoted_to_exact_tier() -> None:
    class _AlwaysHitSemantic:
        def __init__(self):
            self.query_calls = 0

        def query(self, tool_name, raw_args, organization_id, *, threshold):
            self.query_calls += 1
            return "semantic hit"

        def store(self, tool_name, raw_args, organization_id, observation):
            pass

    semantic = _AlwaysHitSemantic()
    cache = ExecutionCache(semantic_backend=semantic)
    args = {"query_entity": "dashboard_summary"}

    first = cache.check("insights", args, "org-1")
    assert first == "semantic hit"
    assert semantic.query_calls == 1

    # second identical call should be an exact-tier hit -- semantic backend
    # is not queried again
    second = cache.check("insights", args, "org-1")
    assert second == "semantic hit"
    assert semantic.query_calls == 1


# ---- execution-post_hooks.md §2: invalidate_namespace ----


def test_exact_backend_invalidate_namespace_purges_only_tagged_entries() -> None:
    backend = ExactCacheBackend()
    backend.set("k1", "obs1", ttl_seconds=60, namespace="fuel:org-1")
    backend.set("k2", "obs2", ttl_seconds=60, namespace="insights:org-1")
    backend.set("k3", "obs3", ttl_seconds=60, namespace="fuel:org-2")

    backend.invalidate_namespace("fuel:org-1")

    assert backend.get("k1") is None
    assert backend.get("k2") == "obs2"
    assert backend.get("k3") == "obs3"


def test_ac1_invalidate_namespace_purges_own_tool_and_insights_for_same_org() -> None:
    cache = ExecutionCache()
    cache.store("insights", {"query_entity": "dashboard_summary"}, "org-1", "dashboard for org-1")
    cache.store("assignment", {"query_target": "vehicle-1"}, "org-1", "assignment history for org-1")
    cache.store("insights", {"query_entity": "dashboard_summary"}, "org-2", "dashboard for org-2")

    cache.invalidate_namespace("assignment", "org-1")

    assert cache.check("insights", {"query_entity": "dashboard_summary"}, "org-1") is None
    assert cache.check("assignment", {"query_target": "vehicle-1"}, "org-1") is None
    # a different org's cache is untouched
    assert cache.check("insights", {"query_entity": "dashboard_summary"}, "org-2") == "dashboard for org-2"


def test_invalidate_namespace_on_insights_itself_does_not_double_purge_unrelated_data() -> None:
    cache = ExecutionCache()
    cache.store("fuel", {"query_entity": "fuel_trends"}, "org-1", "fuel data")

    cache.invalidate_namespace("insights", "org-1")  # a write funnelled through insights (none exist, but defensively)

    assert cache.check("fuel", {"query_entity": "fuel_trends"}, "org-1") == "fuel data"
