import asyncio

from orchestrator.webhooks import AlertDispatcher, _find_low_stock_parts


def test_find_low_stock_parts_scans_nested_updated_parts_list() -> None:
    raw_result = {"updated_parts": [
        {"part_id": "p1", "qty_on_hand": 2, "reorder_threshold": 5},
        {"part_id": "p2", "qty_on_hand": 10, "reorder_threshold": 5},
    ]}
    hits = _find_low_stock_parts(raw_result)
    assert len(hits) == 1
    assert hits[0]["part_id"] == "p1"


def test_find_low_stock_parts_at_threshold_counts_as_low() -> None:
    raw_result = {"updated_parts": [{"part_id": "p1", "qty_on_hand": 5, "reorder_threshold": 5}]}
    assert len(_find_low_stock_parts(raw_result)) == 1


def test_maintenance_rule_fires_on_restock_write() -> None:
    dispatcher = AlertDispatcher()
    raw_result = {"updated_parts": [{"part_id": "p1", "qty_on_hand": 1, "reorder_threshold": 5}]}

    fired = dispatcher.evaluate_and_queue("maintenance", raw_result, "org-1")

    assert len(fired) == 1
    assert fired[0].rule == "low_stock"
    assert fired[0].organization_id == "org-1"
    assert dispatcher.alerts == fired


def test_maintenance_rule_fires_on_mechanic_report_low_stock_alerts() -> None:
    # maintenance_onboard shape: LowStockAlert only carries a boolean flag,
    # not raw quantities -- see backend/app/schemas/maintenance.py.
    dispatcher = AlertDispatcher()
    raw_result = {"mechanic_report": {"low_stock_alerts": [
        {"part_id": "p1", "low_stock_alert": True},
        {"part_id": "p2", "low_stock_alert": False},
    ]}}

    fired = dispatcher.evaluate_and_queue("maintenance", raw_result, "org-1")

    assert len(fired) == 1
    assert fired[0].payload["part_id"] == "p1"


def test_maintenance_rule_does_not_fire_when_stock_is_healthy() -> None:
    dispatcher = AlertDispatcher()
    raw_result = {"updated_parts": [{"part_id": "p1", "qty_on_hand": 50, "reorder_threshold": 5}]}
    assert dispatcher.evaluate_and_queue("maintenance", raw_result, "org-1") == []


def test_accountability_rule_fires_on_critical_severity() -> None:
    dispatcher = AlertDispatcher()
    raw_result = {"created_record": {"id": "i1", "severity": "critical"}}

    fired = dispatcher.evaluate_and_queue("accountability", raw_result, "org-1")

    assert len(fired) == 1
    assert fired[0].rule == "critical_incident"


def test_accountability_rule_fires_on_severe_severity() -> None:
    dispatcher = AlertDispatcher()
    raw_result = {"created_record": {"id": "i1", "severity": "severe"}}
    assert len(dispatcher.evaluate_and_queue("accountability", raw_result, "org-1")) == 1


def test_accountability_rule_does_not_fire_on_minor_severity() -> None:
    dispatcher = AlertDispatcher()
    raw_result = {"created_record": {"id": "i1", "severity": "minor"}}
    assert dispatcher.evaluate_and_queue("accountability", raw_result, "org-1") == []


def test_unrelated_agent_never_fires() -> None:
    dispatcher = AlertDispatcher()
    assert dispatcher.evaluate_and_queue("insights", {"query_result": {"total_vehicles": 10}}, "org-1") == []


def test_evaluate_and_queue_never_raises_on_malformed_raw_result() -> None:
    dispatcher = AlertDispatcher()
    # created_record is a string, not a dict -- .get() would blow up if unguarded
    assert dispatcher.evaluate_and_queue("accountability", {"created_record": "not-a-dict"}, "org-1") == []


def test_ac2_alert_dropped_into_queue_when_attached() -> None:
    dispatcher = AlertDispatcher()
    queue: asyncio.Queue = asyncio.Queue()
    dispatcher.attach_queue(queue)

    dispatcher.evaluate_and_queue("accountability", {"created_record": {"severity": "critical"}}, "org-1")

    assert queue.qsize() == 1


def test_run_worker_drains_queue_via_sink() -> None:
    received = []

    async def _sink(alert):
        received.append(alert)

    async def _main():
        dispatcher = AlertDispatcher(sink=_sink)
        queue: asyncio.Queue = asyncio.Queue()
        dispatcher.attach_queue(queue)
        dispatcher.evaluate_and_queue("accountability", {"created_record": {"severity": "critical"}}, "org-1")

        worker = asyncio.create_task(dispatcher.run_worker(queue))
        await queue.join()
        worker.cancel()

    asyncio.run(_main())
    assert len(received) == 1


def test_sink_failure_does_not_propagate() -> None:
    async def _bad_sink(alert):
        raise RuntimeError("webhook endpoint is down")

    async def _main():
        dispatcher = AlertDispatcher(sink=_bad_sink)
        from orchestrator.webhooks import Alert

        await dispatcher._safe_sink(Alert(organization_id="org-1", agent_name="accountability", rule="x", payload={}))

    asyncio.run(_main())  # must not raise
