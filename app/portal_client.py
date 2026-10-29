"""Client for the Urja Meter Ops portal (login, request signing, error handling)."""
import hashlib
import hmac
import os
import time
from urllib.parse import urlencode

import httpx

BASE_URL = "https://urja-ops.flockenergy.tech"


class PortalError(Exception):
    """Base class for everything that can go wrong talking to the portal."""


class AuthError(PortalError):
    """Login failed, or the session could not be re-established."""


class SignatureError(PortalError):
    """The portal keeps rejecting our request signature."""


class NotFoundError(PortalError):
    """The portal says the thing we asked for does not exist (404)."""


class PortalUnavailable(PortalError):
    """Network problem or an unexpected server error."""


def sign(method: str, path: str, query: str, secret: str, timestamp: int | None = None):
    """Return (timestamp, signature) the way the portal's own front-end builds them."""
    ts = str(int(time.time()) if timestamp is None else timestamp)
    message = "\n".join([method, path, query, ts])
    signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return ts, signature


class PortalClient:
    def __init__(self, email: str, password: str, base_url: str = BASE_URL, transport=None):
        self.email = email
        self.password = password
        self.base_url = base_url
        self.http = httpx.Client(base_url=base_url, timeout=30, transport=transport)
        self._secret: str | None = None

    @classmethod
    def from_env(cls) -> "PortalClient":
        return cls(os.environ["URJA_EMAIL"], os.environ["URJA_PASSWORD"])

    # ---- authentication -------------------------------------------------

    def login(self) -> None:
        try:
            r = self.http.post(
                "/login",
                data={"email": self.email, "password": self.password},
                headers={
                    "Accept": "application/json",
                    "Origin": self.base_url,
                    "Referer": f"{self.base_url}/login",
                    "X-Sveltekit-Action": "true",
                },
            )
        except httpx.TransportError as exc:
            raise PortalUnavailable(str(exc)) from exc
        # The portal answers HTTP 200 even for a wrong password: read the body.
        if r.json().get("type") != "redirect":
            raise AuthError("Login rejected by the portal")

    def _signing_secret(self) -> str:
        if self._secret is None:
            self._secret = self._request("/portal/keys")["data"]["signingSecret"]
        return self._secret

    @staticmethod
    def _error_code(response: httpx.Response) -> str | None:
        try:
            return response.json().get("error")
        except ValueError:
            return None

    # ---- the one place that talks to the portal -------------------------

    def _request(self, path: str, params: dict | None = None, signed: bool = False) -> dict:
        query = urlencode(params or {})
        url = f"{path}?{query}" if query else path

        relogged = False  # have we already logged in again during this call?
        resigned = False  # have we already re-signed during this call?

        while True:
            # 1) Prepare the headers (a signed request needs a fresh signature every time)
            headers = {}
            if signed:
                ts, sig = sign("GET", path, query, self._signing_secret())
                headers = {"x-timestamp": ts, "x-signature": sig}

            # 2) Send the request
            try:
                r = self.http.get(url, headers=headers)
            except httpx.TransportError as exc:
                raise PortalUnavailable(str(exc)) from exc

            # 3) Decide what to do with the answer
            if r.status_code == 401:
                code = self._error_code(r)

                if code == "unauthorized" and not relogged:
                    relogged = True
                    self.login()
                    continue

                if code == "signature_invalid" and not resigned:
                    resigned = True
                    self._secret = None
                    continue

                if code == "signature_invalid":
                    raise SignatureError(r.text)
                raise AuthError(r.text)

            if r.status_code == 404:
                raise NotFoundError(r.text)

            if r.status_code >= 400:
                raise PortalUnavailable(f"HTTP {r.status_code}")

            return r.json()

    # ---- public methods -------------------------------------------------

    def export(self) -> list[dict]:
        """All meters in one call (the portal ignores the page number)."""
        return self._request("/portal/export", {"page": 1}, signed=True)["data"]

    def transformers(self) -> list[dict]:
        """All distribution transformers (this endpoint really is paginated, 20 per page)."""
        rows: list[dict] = []
        for page in range(1, 11):  # safety cap
            body = self._request("/portal/dts", {"page": page})
            rows.extend(body["data"])
            if len(rows) >= body["total"] or not body["data"]:
                break
        return rows

    def energy(self, meter_id: str) -> list[dict]:
        return self._request(f"/portal/meters/{meter_id}/energy")["data"]
