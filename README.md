# Urja Meter API

A clean, documented REST API in front of the legacy **Urja Meter Ops** web portal (which has no API of its own).
Another engineer or program can read meter details, locations, consumption and the network hierarchy
without ever touching the portal.

* How the portal works (what I found, and its quirks): [PROTOCOL.md](PROTOCOL.md)
* OpenAPI 3.1 description of *this* API: [openapi.json](openapi.json). When the service is running it is also at `/openapi.json`, with an interactive page at **`/docs`**.
* Reflection answers: [REFLECTION.md](REFLECTION.md)

## What it does
| Endpoint | Purpose |
|---|---|
| `GET /meters` | List/filter: `status`, `phase`, `install_type`, `make`, `transformer`, `q` (id or serial), `has_issues`, `limit`, `offset` |
| `GET /meters/{id}` | One meter: nameplate, location, full hierarchy, data-quality flags |
| `GET /meters/{id}/consumption` | Readings with ISO timestamps, per-interval usage, resolution and anomalies; optional `from` / `to` |
| `GET /meters/near?lat=&lng=&radius_km=` | Meters near a point, nearest first |
| `GET /transformers`, `/transformers/{code}` | Transformers with capacity and meter count |
| `GET /hierarchy?depth=` | Zone > circle > division > subdivision > substation > feeder > DT tree with meter counts |
| `GET /quality` | Summary of data-quality problems found in the portal's data |
| `GET /health` | Cache status (loaded, stale, age, last refresh error) |

## Install and run
Requires Python 3.10+. Credentials are the ones supplied with the assignment; they are read from environment
variables and are never stored in the repo.

```powershell
# Windows PowerShell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
$env:URJA_EMAIL = "<email from the assignment>"
$env:URJA_PASSWORD = "<password from the assignment>"
python -m uvicorn app.main:app
```
```bash
# macOS / Linux
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export URJA_EMAIL="<email>" URJA_PASSWORD="<password>"
python -m uvicorn app.main:app
```
Then open http://127.0.0.1:8000/docs. The first request takes a moment because it logs in and loads the export.

Optional setting: `CACHE_TTL_SECONDS` (default 600).

Tests (no network or credentials needed): `pip install -r requirements-dev.txt` then `python -m pytest -q`.
Regenerate the spec: `python -m scripts.export_openapi`.

## Sample request
```
curl.exe "http://127.0.0.1:8000/meters?status=faulty&phase=three&limit=1"
```
(PowerShell: use `curl.exe` or `Invoke-RestMethod`; on bash use `curl`.) Response:
```json
{
  "items": [
    {
      "meter_id": "J100005",
      "serial_no": "HP63682",
      "make": "Allied",
      "phase": "three",
      "status": "faulty",
      "install_type": "whole_current",
      "build": "legacy",
      "transformer_code": "DT-006",
      "location": {
        "latitude": 26.84670538836401,
        "longitude": 75.86828425070057
      },
      "hierarchy": {
        "zone": {
          "code": "Z-03",
          "name": "Jaipur Zone 3"
        },
        "circle": {
          "code": "C-06",
          "name": "Circle 6"
        },
        "division": {
          "code": "D-06",
          "name": "Division 6"
        },
        "subdivision": {
          "code": "SD-06",
          "name": "Subdivision 6"
        },
        "substation": {
          "code": "SS-06",
          "name": "Substation 6"
        },
        "feeder": {
          "code": "F-006",
          "name": "Feeder 6"
        },
        "dt": {
          "code": "DT-006",
          "name": "Jhotwara DT 6"
        }
      },
      "data_quality": []
    }
  ],
  "total": 35,
  "limit": 1,
  "offset": 0
}
```
Consumption (first readings of J100000, `GET /meters/J100000/consumption`):
```json
{"meter_id":"J100000","timezone_assumed":"Asia/Kolkata (+05:30)","resolution_minutes":30,"count":337,
 "readings":[
  {"timestamp":"2026-06-23T23:30:00+05:30","kwh":48438.74,"kvah":52313.84,"voltage_r":226.0,"interval_kwh":null,"interval_kvah":null},
  {"timestamp":"2026-06-24T00:00:00+05:30","kwh":48439.16,"kvah":52314.29,"voltage_r":229.0,"interval_kwh":0.42,"interval_kvah":0.45}],
 "anomalies":[]}
```

## How it is structured
```
app/portal_client.py  login, request signing, retry rules, typed errors        (talks to the portal)
app/cleaning.py       pure functions: normalise meters/transformers, parse readings, haversine
app/models.py         response models (also the source of openapi.json)
app/service.py        cache (TTL, stale-on-error), filters, near, quality, hierarchy
app/main.py           FastAPI routes and error mapping
tests/                19 tests (signature vector, cleaning rules, API behaviour, stale cache, 503 mapping)
```
Dependencies point one way (`main` > `service` > `cleaning`/`portal_client`), so the portal-specific code can be
replaced without touching the API.

## Assumptions
* **Timezone**: the portal never states one; the network is in Jaipur, so timestamps are read as IST (+05:30) and returned as ISO 8601 with that offset (`timezone_assumed` says so in every consumption response).
* **`kwh` / `kvah` are cumulative registers** (they only increase), so "usage" is the difference between consecutive readings (`interval_kwh`).
* The export returning 403 rows with `total: 403` is taken as the complete meter population.
* `/portal/dts` is the master list for transformer names; a meter whose embedded DT name disagrees is flagged, not renamed.
* An empty string in the portal's hierarchy means "missing", not "no value".
* The readings are a fixed snapshot (23-30 June 2026), so a 10-minute cache loses nothing.

## Design decisions and trade-offs
| Decision | Why | Cost |
|---|---|---|
| Load the **bulk export once** and answer list/detail/near/hierarchy from memory | One signed request replaces 21 list pages + 403 detail/geo calls | Whole dataset in RAM; see scale notes |
| Fetch **energy per meter on demand**, cache each (LRU of 256, same TTL) | It is the only per-meter call and the largest payload | First request per meter is slower |
| **Flag, don't fix** bad data (`data_quality`, `/quality`) | Silent repairs hide problems from the data owners | Consumers must handle `null` codes |
| `/hierarchy` identifies nodes **by position in the tree**; a missing code/name is filled from other records only when the name-code pairing is unambiguous | Codes repeat under different parents (see PROTOCOL.md 5.10), so code-only keys would merge unrelated branches | Repair rule is a heuristic, applied only in this view |
| **Sign every request freshly**; on `unauthorized` log in again once; on `signature_invalid` drop the cached secret and retry once | The portal rejects stale timestamps and expires sessions after 1 hour; the two 401s need different fixes | A persistent failure surfaces as an error after one retry |
| **Stale-while-error**: if a refresh fails, keep serving old data, mark `/health` as `degraded`, retry in at most 30 s | A flaky legacy system should not take the API down | Clients may see data up to TTL + outage old |
| Upstream failures become **502/503** with `{error, message}` | The caller must be able to tell "your request is wrong" from "the portal is down" | |
| Synchronous code (FastAPI runs it in a thread pool) | The portal client is simple and blocking; load is low | Not built for very high concurrency |

## Extensions covered
* **Network hierarchy**: `/hierarchy`, built from the export, with the messy data handled as above.
* **Local index / query layer**: filters across attributes and `/meters/near` (haversine), answering things the portal cannot.
* **Freshness / caching**: TTL cache, stale-while-error, `/health`.
* **Robustness**: session expiry, signature errors, retries with limits, typed errors, tests for stale data and portal-down.
* **Bulk path**: the signed export (PROTOCOL.md section 4).

### Where the in-memory approach starts to struggle
Measured on my laptop by repeating the real 403 records (rough, not a proper benchmark):

| Meters | Load + clean | Memory | Filtered list | `near` query |
|---|---|---|---|---|
| 403 | 0.07 s | 2.6 MB | 0.2 ms | 0.8 ms |
| 10,000 | 1.7 s | 63 MB | 59 ms | 17 ms |
| 100,000 | 17.8 s | 632 MB | 525 ms | 210 ms |

Queries are linear scans, so latency grows with the number of meters. I would expect trouble somewhere between
10,000 and 100,000 meters (slow startup, hundreds of MB, hundreds of ms per query). The portal's own export would also
likely break first, since it returns everything in one unpaginated response. At that scale I would move the data to
SQLite or Postgres (with PostGIS or a spatial index for `near`), sync it incrementally, and serve queries from the database.

## What I intentionally skipped
* **A web client** (map, charts): the API and the write-up were the priority; the API already exposes what a map and a consumption chart would need.
* **Authentication on this API**: it is a local take-home service; in production it needs auth and rate limiting.
* **Persistence**: the cache is in memory and per process.
* **Writing anything to the portal**: it is treated as strictly read-only.
* **Guessing the energy data for all 403 meters up front**: that would be 403 requests; energy is loaded on demand.
* **Repairing the source data**: blank codes and the DT-name conflict are reported, not corrected.

## What I would improve with more time
* Record real portal responses as fixtures and test the client against them (current tests use hand-made data and a fake portal client).
* Measure the signature's timestamp tolerance, and check energy for all meters in a background job, so `/quality` can also report odd readings (the three daily-resolution meters).
* A background refresh instead of refreshing inside a request; a shared cache (SQLite/Redis) for multiple workers.
* An async portal client; metrics and structured logging.
* Aggregations (daily totals, load profile) and the small web client.

## AI assistance (disclosure)
I used an AI assistant (Claude) during this task for guidance: explaining concepts, reviewing my findings, and drafting
and testing parts of the code and documentation. The exploration of the portal (endpoints, login, signing recipe,
data quirks) was done by me in the browser and from Python scripts, and I reviewed and can explain the code.
