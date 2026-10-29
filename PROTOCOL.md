# PROTOCOL.md: how the Urja Meter Ops portal actually works

Everything here was found by using the portal as a normal logged-in user (browser DevTools: Network and Sources tabs)
and then re-checking from Python. Nothing was attacked or modified; the portal was only read.
Where something is an inference rather than an observation, it says so.

## 1. What the portal is
A server-rendered/hybrid **SvelteKit** web app at `https://urja-ops.flockenergy.tech`
(evidence: `/_app/immutable/...` assets, `X-Sveltekit-Page` header, `__data.json?x-sveltekit-invalidated=...` requests).
Pages: `/login`, `/meters` (list), `/meters/{id}` (detail), `/transformers`. There is an "Ops Desk" link in the nav bar
that is not clickable; I did not find a destination for it.

The pages are thin: they call a JSON API under **`/portal/...`**. That is the interface this project wraps.

## 2. Authentication and sessions
| Step | Detail |
|---|---|
| Login | `POST /login`, `application/x-www-form-urlencoded`, fields `email`, `password`. Headers the front-end sends: `Accept: application/json`, `X-Sveltekit-Action: true`. I also send `Origin` and `Referer`, as a browser would. |
| Success | HTTP 200 and body `{"type":"redirect","status":303,"location":"/meters"}` |
| Failure | **HTTP 200 as well**, body `{"type":"failure","status":401,"data":"...Invalid email or password."}`. The real result is in the body, not the status code. |
| Session | Cookie `__Secure-better-auth.session_token` (HttpOnly, Secure, SameSite=Lax, Path=/), **Max-Age=3600 (1 hour)**. The cookie name suggests the "Better Auth" library (inference). |
| Sign out | `POST /api/auth/sign-out` with an empty body; the response expires `session_token`, `session_data` and `dont_remember`. Login and sign-out live in different places (`/login` vs `/api/auth/...`). |
| No/expired session | `401 {"error":"unauthorized","message":"A valid session is required."}` (JSON, not a redirect). This is the signal to log in again. |

## 3. Endpoints (all need the session cookie)
| Endpoint | Returns |
|---|---|
| `GET /portal/meters/search?q=&page=N` | `{data:[{meterId, serialNo, make, phaseType, installStatus, dtCode}], total, page, pageSize}`; 20 per page, 403 meters, 21 pages. `q` is a case-insensitive substring match on meter id / serial. Page past the end gives `data: []` (still 200); page 0 behaves like page 1. |
| `GET /portal/meters/{id}/geo` | `{data:{latitude:"26.93…", longitude:"75.83…"}}`, **numbers as strings** |
| `GET /portal/meters/{id}/energy` | `{data:[{timestamp, kwh, kvah, voltR}]}`, **all values strings**, the whole history in one response, no paging or date parameters |
| `GET /portal/dts?page=N` | `{data:[{code, name, feederCode, capacityKva}], total}`; 20 per page, 40 transformers, 2 pages |
| `GET /portal/keys` | `{data:{signingSecret}}`, a 32-character value (see section 4) |
| `GET /portal/export?page=N` | `{data:[...all 403 meters...], total:403}`; **requires signed headers** (section 4) |
| Unknown meter | `404 {"error":"not_found","message":"Meter not found"}` on `/geo` and `/energy` |

The meter detail page also loads SvelteKit's packed `__data.json` (values stored once and referenced by position).
It carries the nameplate and a breadcrumb of the network hierarchy. I did not need it, because the export contains
the same information in plain JSON.

## 4. The bulk export and its request signature
The "Export all meters" button on `/transformers` downloads every meter in one call. It first fetches `/portal/keys`,
then calls `/portal/export?page=1` with two headers:

* `x-timestamp`: current Unix time in seconds
* `x-signature`: lowercase hex **HMAC-SHA256** of the text below, keyed with `signingSecret`

```
METHOD \n PATH \n QUERY \n TIMESTAMP        e.g.  GET\n/portal/export\npage=1\n1793237206
```

I found this in the page's JavaScript (Sources tab, search for `X-Signature`; the code is in the chunk loaded for the
transformers page). I then **re-computed the signature of a request captured in the browser and it matched exactly**.

Observed behaviour:
* Wrong signature: `401 {"error":"signature_invalid","message":"Missing or invalid request signature."}`
* A correctly signed request with a timestamp 10 minutes old is rejected with the same error, so the server enforces a
  freshness window shorter than 10 minutes (exact tolerance not measured; the error does not say which part failed).
* The secret was identical on two calls in one session, and looked identical in screenshots from two different days,
  so it appears to be a fixed value handed to every logged-in client. The signature therefore proves "this client
  knows the published recipe" more than it protects anything.
* **`page` is ignored**: `page=2` returns the same 403 rows as `page=1` (verified identical). The front-end hardcodes
  `page=1`, so the button works, but anything that looped "until all pages are read" would never finish.

### Export record shape
```json
{"meterId":"J100000","serialNo":"SE33962","make":"HPL","phaseType":"single","installStatus":"Decommissioned",
 "installType":"Whole Current","build":"legacy","dtCode":"DT-001",
 "hierarchy":{"zone":{"name":"Jaipur Zone 1","code":"Z-01"}, "circle":{...}, "division":{...}, "subdivision":{...},
              "substation":{...}, "feeder":{...}, "dt":{"name":"Malviya Nagar DT 1","code":"DT-001"}},
 "geo":{"lat":26.938961002479868,"lng":75.83095696146852}}
```
Compared with the paged list endpoint, the export adds `installType`, `build`, the full hierarchy and coordinates,
so it replaces 21 list calls + 403 `/geo` calls. Energy readings are **not** in it.

## 5. Quirks and surprises
1. **Login failure is HTTP 200.** Check the body's `type` (`redirect` vs `failure`).
2. **Two different 401s.** `unauthorized` means log in again; `signature_invalid` means re-sign. Re-logging in does not fix the second one.
3. **Numbers are strings** in `/geo` and `/energy` (`"48440"`, `"52315.2"`; trailing zeros dropped). The export's coordinates are real numbers.
4. **Timestamps are `DD/MM/YYYY HH:mm` with no timezone.**
5. **`kwh` and `kvah` are cumulative meter registers**, not usage per interval (they only rise, by about 0.42 kWh per half hour for J100000). Usage is the difference between consecutive readings.
6. **Readings are a fixed snapshot**: 23/06/2026 23:30 to 30/06/2026 23:30, every 30 minutes (337 rows), regardless of today's date. Decommissioned meters (e.g. J100000) still have a full week of readings.
7. **Three meters behave differently**: J100400, J100401, J100402 are the last three ids (J100399 is the last row on page 20, so they make up page 21; I did not open page 21 itself, but they are in the export), have `GN` serial prefixes (no other meter does), and have **8 readings, one per day at 00:00** instead of 337. Their DT (DT-007) is named "Old Malviya Nagar Xfmr" in the export while `/portal/dts` and the other DT-007 meters say "Sanganer DT 7".
8. **A raw `&` in a search query breaks it.** Serials like `L&84997` (77 of them start with `L&`) split the query string: unencoded, `q=L&84997` searched for "L" and returned 167 meters; encoded it returned the one meter. Clients must URL-encode.
9. **Messy hierarchy data (22 of 403 meters).** Some levels have a name but an empty-string code (circle 6 meters, feeder 5, substation 3) or a code but an empty name (circle 5, feeder 3).
10. **Codes are not unique across the tree.** Circle codes are unique (6) but every division (10), subdivision (14) and substation (18) code appears under more than one parent; 15 of 28 feeder codes and 12 of 40 DTs do too (54 distinct feeder paths). A tree keyed by code alone would merge unrelated branches. Identity has to be the path.
11. **Two meter generations.** `build` is `legacy` (238) or `v2` (165). Their detail pages label fields differently ("Meter ID" vs "MeterId"); the energy format is the same.
12. **Serial prefix does not match make** (e.g. `AL` serials appear on HPL, Genus and Secure meters), so it carries no meaning.
13. **Front-end oddities seen in the Network log:** requests to `dts?page=NaN` (a client-side bug, harmless), and the Export button always asking for `page=1`.
14. **Status mix:** 238 Installed, 90 Faulty, 75 Decommissioned; decommissioned meters keep their transformer and hierarchy.

## 6. Not verified
* The exact timestamp tolerance of the signature check.
* What "Ops Desk" is.
* Rate limits (I kept to a few dozen requests per experiment).
* Whether the signing secret changes over longer periods than I observed (two days).
* Energy for all 403 meters: I sampled 9 meters covering every build/status combination plus the three odd ones.
