"""One-off exploration script for the Urja Meter Ops portal.
Prints only safe information (no cookies, no secrets)."""
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
    sig = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return ts, sig


def export_page(client, secret, page):
    query = f"page={page}"
    ts, sig = sign("GET", "/portal/export", query, secret)
    return client.get(
        f"/portal/export?{query}",
        headers={"x-timestamp": ts, "x-signature": sig},
    )


def step(title):
    print(f"\n=== {title} ===")


client = httpx.Client(base_url=BASE, timeout=30)

step("1) Login")
r = client.post(
    "/login",
    data={"email": EMAIL, "password": PASSWORD},
    headers={
        "Accept": "application/json",
        "Origin": BASE,
        "Referer": f"{BASE}/login",
        "X-Sveltekit-Action": "true",
    },
)
print("status:", r.status_code)
print("body:", r.text[:200])
print("cookie names:", list(client.cookies.keys()))

step("2) Is the signing secret the same every time?")
s1 = client.get("/portal/keys").json()["data"]["signingSecret"]
s2 = client.get("/portal/keys").json()["data"]["signingSecret"]
print("same both times:", s1 == s2, "| length:", len(s1))
secret = s1

step("3) Export page 1 (does it contain everything?)")
r = export_page(client, secret, 1)
print("status:", r.status_code)
body = r.json()
print("top-level keys:", list(body.keys()))
print("rows in data:", len(body["data"]), "| total:", body.get("total"))
print({k: v for k, v in body.items() if k != "data"})

step("4) Export page 2")
r = export_page(client, secret, 2)
print("status:", r.status_code)
try:
    b2 = r.json()
    print("rows in data:", len(b2.get("data", [])), "| keys:", list(b2.keys()))
except Exception:
    print("body:", r.text[:200])

step("5) Wrong signature")
r = client.get(
    "/portal/export?page=1",
    headers={"x-timestamp": str(int(time.time())), "x-signature": "0" * 64},
)
print("status:", r.status_code, "| body:", r.text[:200])

step("6) Old timestamp (10 minutes ago, correctly signed)")
old = str(int(time.time()) - 600)
msg = "\n".join(["GET", "/portal/export", "page=1", old])
sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
r = client.get("/portal/export?page=1", headers={"x-timestamp": old, "x-signature": sig})
print("status:", r.status_code, "| body:", r.text[:200])

step("7) Request WITHOUT logging in")
anon = httpx.Client(base_url=BASE, timeout=30)
r = anon.get("/portal/meters/search", params={"q": "", "page": 1})
print("status:", r.status_code, "| content-type:", r.headers.get("content-type"))
print("body start:", r.text[:150].replace("\n", " "))

step("8) Meter detail endpoints vs export")
geo = client.get("/portal/meters/J100000/geo").json()
energy = client.get("/portal/meters/J100000/energy").json()
first = body["data"][0]
print("geo endpoint:", geo)
print("export geo:  ", first["geo"])
print("energy readings:", len(energy["data"]))
print("first reading:", energy["data"][0])
print("last reading: ", energy["data"][-1])

print("\nDone.")
if '"failure"' in r.text or not client.cookies:
    raise SystemExit("Login failed - check the email and password")