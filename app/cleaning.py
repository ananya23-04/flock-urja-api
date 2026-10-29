"""Pure functions that turn the portal's messy values into clean models."""
import math
import statistics
from datetime import datetime, timedelta, timezone

from app.models import (
    Anomaly, Hierarchy, InstallType, Location, Meter, Node, Phase, Reading, Status, Transformer,
)

# The portal never states a timezone. The network is in Jaipur, so we assume India Standard Time.
IST = timezone(timedelta(hours=5, minutes=30))
TIMEZONE_ASSUMED = "Asia/Kolkata (+05:30)"
LEVELS = ("zone", "circle", "division", "subdivision", "substation", "feeder", "dt")

_STATUS = {"installed": Status.installed, "faulty": Status.faulty, "decommissioned": Status.decommissioned}
_PHASE = {"single": Phase.single, "three": Phase.three}
_INSTALL = {"whole current": InstallType.whole_current, "ct operated": InstallType.ct_operated}


def num(value) -> float | None:
    """The portal sends numbers as strings; empty or junk values become None."""
    if value is None or value == "":
        return None
    try:
        f = float(str(value).strip())
    except ValueError:
        return None
    return f if math.isfinite(f) else None


def _node(raw) -> Node:
    raw = raw or {}
    return Node(code=(raw.get("code") or None), name=(raw.get("name") or None))


def normalize_transformer(raw: dict) -> Transformer:
    cap = num(raw.get("capacityKva"))
    return Transformer(
        code=str(raw["code"]), name=str(raw.get("name", "")),
        feeder_code=raw.get("feederCode") or None,
        capacity_kva=cap,
    )


def normalize_meter(raw: dict, masters: dict[str, Transformer] | None = None) -> Meter:
    flags: list[str] = []
    h = raw.get("hierarchy") or {}
    hierarchy = Hierarchy(**{lvl: _node(h.get(lvl)) for lvl in LEVELS})

    for lvl in LEVELS:
        node = getattr(hierarchy, lvl)
        if node.code is None:
            flags.append(f"hierarchy_code_missing:{lvl}")
        if node.name is None:
            flags.append(f"hierarchy_name_missing:{lvl}")

    dt_code = str(raw.get("dtCode") or hierarchy.dt.code or "")
    if masters is not None:
        master = masters.get(dt_code)
        if master is None:
            flags.append("dt_not_in_master_list")
        else:
            if hierarchy.dt.name and hierarchy.dt.name != master.name:
                flags.append("dt_name_conflict")
            if hierarchy.feeder.code and master.feeder_code and hierarchy.feeder.code != master.feeder_code:
                flags.append("feeder_conflict")

    geo = raw.get("geo") or {}
    lat, lng = num(geo.get("lat")), num(geo.get("lng"))
    location = None
    if lat is None or lng is None:
        flags.append("location_missing")
    elif not (-90 <= lat <= 90 and -180 <= lng <= 180):
        flags.append("location_invalid")
    else:
        location = Location(latitude=lat, longitude=lng)

    status = _STATUS.get(str(raw.get("installStatus", "")).strip().lower(), Status.unknown)
    phase = _PHASE.get(str(raw.get("phaseType", "")).strip().lower(), Phase.unknown)
    install = _INSTALL.get(str(raw.get("installType", "")).strip().lower(), InstallType.unknown)
    for label, value in (("status", status), ("phase", phase), ("install_type", install)):
        if value.value == "unknown":
            flags.append(f"unknown_{label}")

    return Meter(
        meter_id=str(raw["meterId"]), serial_no=str(raw.get("serialNo", "")), make=str(raw.get("make", "")),
        phase=phase, status=status, install_type=install, build=raw.get("build") or None,
        transformer_code=dt_code, location=location, hierarchy=hierarchy, data_quality=flags,
    )


def parse_readings(rows: list[dict]) -> tuple[list[Reading], list[Anomaly], int | None]:
    """Parse the portal's energy rows: ISO timestamps, numbers, and per-interval usage."""
    anomalies: list[Anomaly] = []
    parsed = []
    for row in rows:
        try:
            ts = datetime.strptime(str(row["timestamp"]), "%d/%m/%Y %H:%M").replace(tzinfo=IST)
        except (KeyError, ValueError):
            anomalies.append(Anomaly(type="unparseable_timestamp", detail=str(row.get("timestamp"))))
            continue
        parsed.append((ts, num(row.get("kwh")), num(row.get("kvah")), num(row.get("voltR"))))
    parsed.sort(key=lambda p: p[0])

    gaps = [(b[0] - a[0]).total_seconds() / 60 for a, b in zip(parsed, parsed[1:])]
    resolution = int(round(statistics.median(gaps))) if gaps else None

    readings: list[Reading] = []
    prev = None
    for ts, kwh, kvah, volt in parsed:
        d_kwh = d_kvah = None
        if prev is not None:
            if prev[0] == ts:
                anomalies.append(Anomaly(type="duplicate_timestamp", at=ts, detail="Same timestamp appears twice"))
            if kwh is not None and prev[1] is not None:
                d_kwh = round(kwh - prev[1], 4)
                if d_kwh < 0:
                    anomalies.append(Anomaly(type="counter_decrease", at=ts, detail=f"kWh register fell by {-d_kwh}"))
            if kvah is not None and prev[2] is not None:
                d_kvah = round(kvah - prev[2], 4)
            if resolution and (ts - prev[0]).total_seconds() / 60 > 1.5 * resolution:
                anomalies.append(Anomaly(type="gap", at=ts, detail=f"{int((ts - prev[0]).total_seconds() // 60)} min since previous reading"))
        readings.append(Reading(timestamp=ts, kwh=kwh, kvah=kvah, voltage_r=volt, interval_kwh=d_kwh, interval_kvah=d_kvah))
        prev = (ts, kwh, kvah)
    return readings, anomalies, resolution


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
