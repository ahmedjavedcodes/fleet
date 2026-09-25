from agents.insights.synthesizer import correlate_costs, synthesize_fleet_health


def test_synthesize_fleet_health_empty() -> None:
    assert synthesize_fleet_health([]) == {
        "average_health_score": None, "vehicle_count": 0, "at_risk_count": 0, "vehicles": [],
    }


def test_synthesize_fleet_health_computes_average_and_at_risk() -> None:
    scores = [
        {"vehicle_id": "v1", "health_score": 80},
        {"vehicle_id": "v2", "health_score": 30},
        {"vehicle_id": "v3", "health_score": 90},
    ]
    result = synthesize_fleet_health(scores)
    assert result["vehicle_count"] == 3
    assert result["at_risk_count"] == 1
    assert result["average_health_score"] == round((80 + 30 + 90) / 3, 1)


def test_correlate_costs_empty() -> None:
    assert correlate_costs([], []) == []


def test_correlate_costs_merges_and_sorts_descending() -> None:
    fuel_by_vehicle = [
        {"vehicle_id": "v1", "total_cost": "100.00"},
        {"vehicle_id": "v2", "total_cost": "50.00"},
    ]
    maintenance_logs = [
        {"vehicle_id": "v1", "cost": "20.00"},
        {"vehicle_id": "v2", "cost": "200.00"},
        {"vehicle_id": "v3", "cost": None},
    ]
    result = correlate_costs(fuel_by_vehicle, maintenance_logs)

    by_id = {r["vehicle_id"]: r for r in result}
    assert by_id["v1"]["total_cost"] == 120.0
    assert by_id["v2"]["total_cost"] == 250.0
    assert by_id["v3"]["total_cost"] == 0.0
    assert [r["vehicle_id"] for r in result] == ["v2", "v1", "v3"]


def test_correlate_costs_handles_vehicle_present_in_only_one_source() -> None:
    result = correlate_costs([{"vehicle_id": "v1", "total_cost": "10"}], [])
    assert result == [{"vehicle_id": "v1", "fuel_cost": 10.0, "maintenance_cost": 0.0, "total_cost": 10.0}]
