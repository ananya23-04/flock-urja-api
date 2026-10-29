import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.portal_client import PortalUnavailable
from app.service import MeterService


def meter(mid, serial, status="Installed", dt="DT-001", feeder=("F-001", "Feeder 1"), circle=("C-01", "Circle 1"),
          dt_name="Malviya Nagar DT 1", lat=26.9389, lng=75.8309, division=("D-01", "Division 1"), build="legacy"):
    h = {"zone": ("Z-01", "Jaipur Zone 1"), "circle": circle, "division": division,
         "subdivision": ("SD-01", "Subdivision 1"), "substation": ("SS-01", "Substation 1"),
         "feeder": feeder, "dt": (dt, dt_name)}
    return {"meterId": mid, "serialNo": serial, "make": "HPL", "phaseType": "single", "installStatus": status,
            "installType": "Whole Current", "build": build, "dtCode": dt,
            "hierarchy": {k: {"code": v[0], "name": v[1]} for k, v in h.items()},
            "geo": {"lat": lat, "lng": lng}}


RAW_METERS = [
    meter("J1", "L&84997"),
    meter("J2", "SE22222", status="Faulty", lat=26.9400),
    meter("J3", "AL33333", status="Decommissioned", dt="DT-002", feeder=("F-002", "Feeder 2"),
          dt_name="Mansarovar DT 2", lat=27.5),
    meter("J4", "GN44444", circle=("", "Circle 6"), dt_name="Old Name"),        # blank code + name conflict
    meter("J5", "SE55555", division=("D-02", "Division 2")),                    # SD-01 under another division
]
RAW_TRANSFORMERS = [
    {"code": "DT-001", "name": "Malviya Nagar DT 1", "feederCode": "F-001", "capacityKva": 100},
    {"code": "DT-002", "name": "Mansarovar DT 2", "feederCode": "F-002", "capacityKva": "63"},
]
RAW_ENERGY = [
    {"timestamp": "24/06/2026 00:00", "kwh": "100", "kvah": "110", "voltR": "230"},
    {"timestamp": "24/06/2026 00:30", "kwh": "100.5", "kvah": "110.6", "voltR": "231"},
    {"timestamp": "24/06/2026 01:00", "kwh": "101", "kvah": "111.1", "voltR": "229"},
]


class FakeClient:
    def __init__(self):
        self.fail = False
        self.export_calls = 0
        self.energy_calls = 0

    def export(self):
        self.export_calls += 1
        if self.fail:
            raise PortalUnavailable("portal down")
        return RAW_METERS

    def transformers(self):
        if self.fail:
            raise PortalUnavailable("portal down")
        return RAW_TRANSFORMERS

    def energy(self, meter_id):
        self.energy_calls += 1
        return RAW_ENERGY


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def fake():
    return FakeClient()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def service(fake, clock):
    return MeterService(client=fake, ttl=600, clock=clock)


@pytest.fixture
def api(service):
    return TestClient(create_app(service))
