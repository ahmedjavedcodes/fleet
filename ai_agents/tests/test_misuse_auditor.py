from agents.accountability.misuse_auditor import audit_trips_for_off_hours


def test_trip_within_hours_not_flagged() -> None:
    trips = [{"id": "t1", "start_time": "2026-01-01T09:00:00", "end_time": "2026-01-01T10:00:00"}]
    assert audit_trips_for_off_hours(trips) == []


def test_trip_starting_before_window_flagged() -> None:
    trips = [{"id": "t1", "start_time": "2026-01-01T03:00:00", "end_time": "2026-01-01T05:00:00"}]
    flagged = audit_trips_for_off_hours(trips)
    assert len(flagged) == 1
    assert "started" in flagged[0]["reason"]


def test_trip_ending_after_window_flagged() -> None:
    trips = [{"id": "t1", "start_time": "2026-01-01T20:00:00", "end_time": "2026-01-01T23:30:00"}]
    flagged = audit_trips_for_off_hours(trips)
    assert len(flagged) == 1
    assert "ended" in flagged[0]["reason"]


def test_custom_window() -> None:
    trips = [{"id": "t1", "start_time": "2026-01-01T07:00:00", "end_time": "2026-01-01T08:00:00"}]
    assert audit_trips_for_off_hours(trips, start_hour=9, end_hour=17) != []
    assert audit_trips_for_off_hours(trips, start_hour=6, end_hour=22) == []


def test_unparseable_timestamps_not_flagged() -> None:
    trips = [{"id": "t1", "start_time": None, "end_time": "not-a-date"}]
    assert audit_trips_for_off_hours(trips) == []
