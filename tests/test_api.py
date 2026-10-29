import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.service import MeterService


def test_list_filter_and_pagination(api):
    assert api.get("/meters").json()["total"] == 5
    assert api.get("/meters", params={"status": "faulty"}).json()["total"] == 1
    page = api.get("/meters", params={"limit": 2, "offset": 4}).json()
    assert len(page["items"]) == 1 and page["total"] == 5


def test_search_handles_ampersand_serial(api):
    items = api.get("/meters", params={"q": "l&84997"}).json()["items"]
    assert [m["meter_id"] for m in items] == ["J1"]


def test_unknown_meter_is_404_with_json_error(api):
    r = api.get("/meters/NOPE")
    assert r.status_code == 404 and r.json()["error"] == "meter_not_found"


def test_bad_filter_value_is_422(api):
    assert api.get("/meters", params={"status": "bogus"}).status_code == 422


def test_near_orders_by_distance_and_skips_far_meters(api):
    ids = [h["meter"]["meter_id"] for h in api.get("/meters/near", params={"lat": 26.9389, "lng": 75.8309, "radius_km": 5}).json()]
    assert ids[0] in ("J1", "J4", "J5") and "J3" not in ids


def test_consumption_window_and_cache(api, fake):
    body = api.get("/meters/J1/consumption", params={"from": "2026-06-24T00:30:00"}).json()
    assert body["count"] == 2 and body["readings"][0]["interval_kwh"] == 0.5
    api.get("/meters/J1/consumption")
    assert fake.energy_calls == 1


def test_quality_flags_are_reported(api):
    q = api.get("/quality").json()
    assert q["issue_counts"]["dt_name_conflict"] == 1
    assert q["examples"]["hierarchy_code_missing:circle"] == ["J4"]


def test_hierarchy_keeps_same_code_under_different_parents(api):
    zone = api.get("/hierarchy").json()[0]
    divisions = {d["code"] for d in zone["children"][0]["children"]}
    assert divisions == {"D-01", "D-02"}   # SD-01 exists under both; they must not be merged


def test_blank_circle_code_is_filled_in_for_tree_only_when_unambiguous(api):
    circles = [c["code"] for c in api.get("/hierarchy").json()[0]["children"]]
    assert "C-01" in circles


def test_serves_stale_data_when_refresh_fails(service, fake, clock):
    c = TestClient(create_app(service))
    assert c.get("/meters").json()["total"] == 5
    clock.now += 601            # cache expired
    fake.fail = True
    assert c.get("/meters").json()["total"] == 5          # old data still served
    h = c.get("/health").json()
    assert h["stale"] and h["status"] == "degraded" and "portal down" in h["last_refresh_error"]


def test_portal_down_with_empty_cache_is_503(fake):
    fake.fail = True
    c = TestClient(create_app(MeterService(client=fake)))
    r = c.get("/meters")
    assert r.status_code == 503 and r.json()["error"] == "upstream_unavailable"
