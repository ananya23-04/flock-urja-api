"""Caching and query layer between the portal client and the API."""
import os
import threading
import time
from collections import Counter, OrderedDict
from datetime import datetime

from app.cleaning import (
    IST, LEVELS, TIMEZONE_ASSUMED, haversine_km, normalize_meter, normalize_transformer, parse_readings,
)
from app.models import (
    Consumption, Health, HierarchyNode, Meter, NearbyMeter, QualitySummary, Transformer,
)
from app.portal_client import PortalClient, PortalError


class UnknownMeter(LookupError):
    pass


class UnknownTransformer(LookupError):
    pass


class MeterService:
    """Loads the portal's bulk export once, keeps it for `ttl` seconds, and answers queries from memory.

    If a refresh fails but we already hold data, the old data is served and flagged as stale.
    """

    def __init__(self, client=None, ttl: float | None = None, energy_cache_size: int = 256, clock=time.monotonic):
        self._client = client
        self.ttl = float(os.environ.get("CACHE_TTL_SECONDS", "600")) if ttl is None else ttl
        self._clock = clock
        self._lock = threading.RLock()
        self._loaded_at: float | None = None
        self._stale = False
        self._last_error: str | None = None
        self._meters: list[Meter] = []
        self._by_id: dict[str, Meter] = {}
        self._transformers: list[Transformer] = []
        self._tx_by_code: dict[str, Transformer] = {}
        self._energy: OrderedDict[str, tuple[float, list[dict]]] = OrderedDict()
        self._energy_max = energy_cache_size

    @property
    def client(self):
        if self._client is None:
            self._client = PortalClient.from_env()
        return self._client

    # ---- loading --------------------------------------------------------

    def _refresh(self) -> None:
        tx = [normalize_transformer(r) for r in self.client.transformers()]
        masters = {t.code: t for t in tx}
        meters = [normalize_meter(r, masters) for r in self.client.export()]
        counts = Counter(m.transformer_code for m in meters)
        for t in tx:
            t.meter_count = counts.get(t.code, 0)
        self._transformers, self._tx_by_code = tx, masters
        self._meters, self._by_id = meters, {m.meter_id: m for m in meters}

    def _ensure_loaded(self) -> None:
        with self._lock:
            if self._loaded_at is not None and (self._clock() - self._loaded_at) < self.ttl:
                return
            try:
                self._refresh()
                self._loaded_at, self._stale, self._last_error = self._clock(), False, None
            except PortalError as exc:
                if self._loaded_at is None:
                    raise  # nothing to fall back on
                self._stale, self._last_error = True, str(exc)
                # Serve the old data and try again in at most 30 s instead of hammering the portal.
                self._loaded_at = self._clock() - self.ttl + min(30.0, self.ttl)

    # ---- meters ---------------------------------------------------------

    def list_meters(self, *, status=None, make=None, phase=None, install_type=None, transformer=None,
                    q=None, has_issues=None, limit=50, offset=0) -> tuple[list[Meter], int]:
        self._ensure_loaded()
        out = []
        needle = q.lower() if q else None
        for m in self._meters:
            if status and m.status != status: continue
            if phase and m.phase != phase: continue
            if install_type and m.install_type != install_type: continue
            if make and m.make.lower() != make.lower(): continue
            if transformer and m.transformer_code.upper() != transformer.upper(): continue
            if needle and needle not in m.meter_id.lower() and needle not in m.serial_no.lower(): continue
            if has_issues is not None and bool(m.data_quality) != has_issues: continue
            out.append(m)
        return out[offset:offset + limit], len(out)

    def get_meter(self, meter_id: str) -> Meter:
        self._ensure_loaded()
        meter = self._by_id.get(meter_id.strip().upper())
        if meter is None:
            raise UnknownMeter(meter_id)
        return meter

    def near(self, lat: float, lng: float, radius_km: float, limit: int) -> list[NearbyMeter]:
        self._ensure_loaded()
        hits = []
        for m in self._meters:  # linear scan: fine for thousands of meters (see README for limits)
            if m.location is None:
                continue
            d = haversine_km(lat, lng, m.location.latitude, m.location.longitude)
            if d <= radius_km:
                hits.append(NearbyMeter(meter=m, distance_km=round(d, 3)))
        hits.sort(key=lambda h: h.distance_km)
        return hits[:limit]

    # ---- consumption ----------------------------------------------------

    def _energy_raw(self, meter_id: str) -> list[dict]:
        with self._lock:
            hit = self._energy.get(meter_id)
            if hit and (self._clock() - hit[0]) < self.ttl:
                self._energy.move_to_end(meter_id)
                return hit[1]
        try:
            rows = self.client.energy(meter_id)
        except PortalError:
            if hit:
                return hit[1]  # stale is better than nothing
            raise
        with self._lock:
            self._energy[meter_id] = (self._clock(), rows)
            self._energy.move_to_end(meter_id)
            while len(self._energy) > self._energy_max:
                self._energy.popitem(last=False)
        return rows

    def consumption(self, meter_id: str, start: datetime | None = None, end: datetime | None = None) -> Consumption:
        meter = self.get_meter(meter_id)
        readings, anomalies, resolution = parse_readings(self._energy_raw(meter.meter_id))

        def aware(dt):
            return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=IST)

        start, end = aware(start), aware(end)
        if start:
            readings = [r for r in readings if r.timestamp >= start]
            anomalies = [a for a in anomalies if a.at is None or a.at >= start]
        if end:
            readings = [r for r in readings if r.timestamp <= end]
            anomalies = [a for a in anomalies if a.at is None or a.at <= end]
        return Consumption(meter_id=meter.meter_id, timezone_assumed=TIMEZONE_ASSUMED,
                           resolution_minutes=resolution, count=len(readings),
                           readings=readings, anomalies=anomalies)

    # ---- transformers, quality, hierarchy -------------------------------

    def transformers(self) -> list[Transformer]:
        self._ensure_loaded()
        return self._transformers

    def get_transformer(self, code: str) -> Transformer:
        self._ensure_loaded()
        t = self._tx_by_code.get(code.strip().upper())
        if t is None:
            raise UnknownTransformer(code)
        return t

    def quality(self) -> QualitySummary:
        self._ensure_loaded()
        counts: Counter = Counter()
        examples: dict[str, list[str]] = {}
        for m in self._meters:
            for flag in m.data_quality:
                counts[flag] += 1
                examples.setdefault(flag, [])
                if len(examples[flag]) < 5:
                    examples[flag].append(m.meter_id)
        return QualitySummary(
            meters_total=len(self._meters),
            meters_with_issues=sum(1 for m in self._meters if m.data_quality),
            issue_counts=dict(sorted(counts.items())), examples=examples,
            notes=["Flags describe the portal's data; nothing was silently repaired.",
                   "Energy anomalies (gaps, odd resolution) are reported per meter by /meters/{id}/consumption."],
        )

    def hierarchy(self, depth: int = 7) -> list[HierarchyNode]:
        """Nested network tree. Node identity = position in the tree (the same code can legitimately
        appear under different parents). A missing code or name is filled in from other records
        only when the name<->code pairing is unambiguous."""
        self._ensure_loaded()
        code_names: dict[str, dict[str, Counter]] = {l: {} for l in LEVELS}
        name_codes: dict[str, dict[str, set]] = {l: {} for l in LEVELS}
        for m in self._meters:
            for lvl in LEVELS:
                n = getattr(m.hierarchy, lvl)
                if n.code and n.name:
                    code_names[lvl].setdefault(n.code, Counter())[n.name] += 1
                    name_codes[lvl].setdefault(n.name, set()).add(n.code)

        def resolve(lvl, n):
            code, name = n.code, n.name
            if code is None and name and len(name_codes[lvl].get(name, ())) == 1:
                code = next(iter(name_codes[lvl][name]))
            if name is None and code and code in code_names[lvl]:
                name = code_names[lvl][code].most_common(1)[0][0]
            return code, name

        root: dict = {}
        for m in self._meters:
            level_map = root
            for lvl in LEVELS[:depth]:
                code, name = resolve(lvl, getattr(m.hierarchy, lvl))
                key = code or name or "(unknown)"
                node = level_map.setdefault(key, {"level": lvl, "code": code, "name": name, "n": 0, "kids": {}})
                node["code"] = node["code"] or code
                node["name"] = node["name"] or name
                node["n"] += 1
                level_map = node["kids"]

        def build(level_map):
            return [HierarchyNode(level=v["level"], code=v["code"], name=v["name"], meter_count=v["n"],
                                  children=build(v["kids"])) for _, v in sorted(level_map.items())]
        return build(root)

    # ---- health ---------------------------------------------------------

    def health(self) -> Health:
        age = None if self._loaded_at is None else round(self._clock() - self._loaded_at, 1)
        return Health(status="degraded" if self._stale else "ok", loaded=self._loaded_at is not None,
                      stale=self._stale, meters_cached=len(self._meters),
                      transformers_cached=len(self._transformers), data_age_seconds=age,
                      last_refresh_error=self._last_error)
