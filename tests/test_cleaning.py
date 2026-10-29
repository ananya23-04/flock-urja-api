from app.cleaning import haversine_km, normalize_meter, parse_readings
from tests.conftest import RAW_METERS


def test_blank_code_is_none_and_flagged():
    m = normalize_meter(RAW_METERS[3])
    assert m.hierarchy.circle.code is None and m.hierarchy.circle.name == "Circle 6"
    assert "hierarchy_code_missing:circle" in m.data_quality


def test_status_and_types_are_normalised():
    m = normalize_meter(RAW_METERS[2])
    assert m.status.value == "decommissioned" and m.install_type.value == "whole_current"


def test_unknown_status_does_not_crash():
    raw = dict(RAW_METERS[0], installStatus="Burnt")
    assert normalize_meter(raw).status.value == "unknown"


def test_readings_have_iso_timestamps_and_intervals():
    rows = [{"timestamp": "24/06/2026 00:00", "kwh": "100", "kvah": "1", "voltR": "230"},
            {"timestamp": "24/06/2026 00:30", "kwh": "100.42", "kvah": "2", "voltR": "x"}]
    readings, anomalies, res = parse_readings(rows)
    assert readings[0].timestamp.isoformat() == "2026-06-24T00:00:00+05:30"
    assert readings[1].interval_kwh == 0.42 and readings[1].voltage_r is None
    assert res == 30 and anomalies == []


def test_counter_decrease_and_gap_are_reported():
    rows = [{"timestamp": "24/06/2026 00:00", "kwh": "100"}, {"timestamp": "24/06/2026 00:30", "kwh": "101"},
            {"timestamp": "24/06/2026 01:00", "kwh": "50"}, {"timestamp": "24/06/2026 03:00", "kwh": "51"}]
    _, anomalies, _ = parse_readings(rows)
    assert {a.type for a in anomalies} == {"counter_decrease", "gap"}


def test_haversine_is_sane():
    assert haversine_km(26.9, 75.8, 26.9, 75.8) == 0
    assert 110 < haversine_km(26.0, 75.0, 27.0, 75.0) < 112  # one degree of latitude
