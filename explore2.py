"""Second exploration script: edge cases. Prints only safe information."""
import getpass
import hashlib
import hmac
import os
import time

import httpx

BASE = "https://urja-ops.flockenergy.tech"
EMAIL = os.environ.get("URJA_EMAIL") or input("Portal email: ")
PASSWORD = os.environ.get("URJA_PASSWORD") or getpass.getpass("Portal password: ")


def sign(method, path, query, secret):
    ts = str(int(time.time()))
    message = "\n".join([method, path, query, ts])
    return ts, hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def step(title):
    print(f"\n=== {title} ===")


def brief(r, n=150):
    return f"status {r.status_code} | {r.text[:n]!r}"


client = httpx.Client(base_url=BASE, timeout=30)
r = client.post(
    "/login",
    data={"email": EMAIL, "password": PASSWORD},
    headers={"Accept": "application/json", "Origin": BASE,
             "Referer": f"{BASE}/login", "X-Sveltekit-Action": "true"},
)
if '"redirect"' not in r.text:
    raise SystemExit("Login failed - check the email and password")

secret = client.get("/portal/keys").json()["data"]["signingSecret"]


def export(page):
    q = f"page={page}"
    ts, sig = sign("GET", "/portal/export", q, secret)
    return client.get(f"/portal/export?{q}", headers={"x-timestamp": ts, "x-signature": sig})


step("A) Is export page 2 identical to page 1?")
p1, p2 = export(1).json()["data"], export(2).json()["data"]
print("identical:", p1 == p2, "| rows:", len(p1), len(p2))
meters = p1

step("B) Energy readings: different kinds of meters")
by_kind = {}
for m in meters:
    by_kind.setdefault((m["build"], m["installStatus"]), m["meterId"])
picks = list(by_kind.values()) + ["J100400", "J100401", "J100402"]
for mid in picks:
    time.sleep(0.2)
    r = client.get(f"/portal/meters/{mid}/energy")
    try:
        rows = r.json()["data"]
        m = next(x for x in meters if x["meterId"] == mid)
        print(mid, m["build"], m["installStatus"], "| status", r.status_code,
              "| readings", len(rows),
              "| keys", sorted(rows[0].keys()) if rows else None,
              "| first", rows[0]["timestamp"] if rows else None,
              "| last", rows[-1]["timestamp"] if rows else None)
    except Exception as exc:
        print(mid, "| status", r.status_code, "| could not parse:", r.text[:100], exc)

step("C) A meter that does not exist")
for path in ("/portal/meters/J999999/geo", "/portal/meters/J999999/energy"):
    print(path, "->", brief(client.get(path)))

step("D) Search behaviour (serial L&84997 belongs to J100003)")


def show(label, r):
    try:
        b = r.json()
        ids = [x["meterId"] for x in b.get("data", [])][:3]
        print(f"{label}: status {r.status_code} | total {b.get('total')} | rows {len(b.get('data', []))} | first ids {ids}")
    except Exception:
        print(f"{label}: {brief(r)}")


show("encoded & (httpx params)", client.get("/portal/meters/search", params={"q": "L&84997", "page": 1}))
show("raw unencoded &         ", client.get("/portal/meters/search?q=L&84997&page=1"))
show("lowercase j100003       ", client.get("/portal/meters/search", params={"q": "j100003", "page": 1}))
show("partial J1000           ", client.get("/portal/meters/search", params={"q": "J1000", "page": 1}))
show("page 22 (past the end)  ", client.get("/portal/meters/search", params={"q": "", "page": 22}))
show("page 0                  ", client.get("/portal/meters/search", params={"q": "", "page": 0}))

print("\nDone.")