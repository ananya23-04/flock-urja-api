"""FastAPI application: a clean, documented API over the Urja Meter Ops portal."""
from datetime import datetime

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse

from app.models import (
    Consumption, ErrorResponse, Health, HierarchyNode, InstallType, Meter, MeterPage, NearbyMeter, Phase,
    QualitySummary, Status, Transformer,
)
from app.portal_client import AuthError, NotFoundError, PortalUnavailable, SignatureError
from app.service import MeterService, UnknownMeter, UnknownTransformer

DESCRIPTION = """
A clean REST API in front of the legacy **Urja Meter Ops** portal.

* Meter data comes from the portal's bulk export (one request), cached in memory.
* Consumption is fetched per meter on demand and cached.
* Data-quality problems in the portal are **flagged, not hidden** (see `/quality`).
* Timestamps are ISO 8601. The portal gives no timezone; India Standard Time is assumed.
"""

ERRORS = {404: {"model": ErrorResponse}, 502: {"model": ErrorResponse}, 503: {"model": ErrorResponse}}


def create_app(service: MeterService | None = None) -> FastAPI:
    app = FastAPI(title="Urja Meter API", version="1.0.0", description=DESCRIPTION)
    app.state.service = service or MeterService()

    def svc(request: Request) -> MeterService:
        return request.app.state.service

    def problem(status: int, error: str, message: str) -> JSONResponse:
        return JSONResponse(status_code=status, content={"error": error, "message": message})

    @app.exception_handler(UnknownMeter)
    async def _unknown_meter(_, exc):
        return problem(404, "meter_not_found", f"No meter with id {exc.args[0]!r}")

    @app.exception_handler(UnknownTransformer)
    async def _unknown_tx(_, exc):
        return problem(404, "transformer_not_found", f"No transformer with code {exc.args[0]!r}")

    @app.exception_handler(NotFoundError)
    async def _portal_404(_, exc):
        return problem(404, "meter_not_found", "The portal has no data for this meter")

    @app.exception_handler(AuthError)
    async def _auth(_, exc):
        return problem(502, "upstream_auth_failed", "Could not authenticate with the portal")

    @app.exception_handler(SignatureError)
    async def _sig(_, exc):
        return problem(502, "upstream_signature_rejected", "The portal rejected our request signature")

    @app.exception_handler(PortalUnavailable)
    async def _down(_, exc):
        return problem(503, "upstream_unavailable", "The portal is unreachable or returned an error")

    @app.get("/health", response_model=Health, tags=["system"], summary="Service and cache status")
    def health(s: MeterService = Depends(svc)):
        return s.health()

    @app.get("/meters", response_model=MeterPage, tags=["meters"], responses=ERRORS, summary="List and filter meters")
    def list_meters(
        status: Status | None = None, phase: Phase | None = None, install_type: InstallType | None = None,
        make: str | None = Query(None, description="Manufacturer, case-insensitive (e.g. HPL)"),
        transformer: str | None = Query(None, description="Distribution transformer code, e.g. DT-001"),
        q: str | None = Query(None, description="Substring of meter id or serial number"),
        has_issues: bool | None = Query(None, description="Only meters with (or without) data-quality flags"),
        limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), s: MeterService = Depends(svc),
    ):
        items, total = s.list_meters(status=status, phase=phase, install_type=install_type, make=make,
                                     transformer=transformer, q=q, has_issues=has_issues, limit=limit, offset=offset)
        return MeterPage(items=items, total=total, limit=limit, offset=offset)

    @app.get("/meters/near", response_model=list[NearbyMeter], tags=["meters"], responses=ERRORS,
             summary="Meters within a radius of a point")
    def near(lat: float = Query(..., ge=-90, le=90), lng: float = Query(..., ge=-180, le=180),
             radius_km: float = Query(1.0, gt=0, le=500), limit: int = Query(20, ge=1, le=500),
             s: MeterService = Depends(svc)):
        return s.near(lat, lng, radius_km, limit)

    @app.get("/meters/{meter_id}", response_model=Meter, tags=["meters"], responses=ERRORS, summary="One meter")
    def get_meter(meter_id: str, s: MeterService = Depends(svc)):
        return s.get_meter(meter_id)

    @app.get("/meters/{meter_id}/consumption", response_model=Consumption, tags=["meters"], responses=ERRORS,
             summary="Meter readings with per-interval usage")
    def consumption(meter_id: str,
                    start: datetime | None = Query(None, alias="from", description="ISO 8601; naive values are read as IST"),
                    end: datetime | None = Query(None, alias="to"), s: MeterService = Depends(svc)):
        return s.consumption(meter_id, start, end)

    @app.get("/transformers", response_model=list[Transformer], tags=["network"], responses=ERRORS,
             summary="Distribution transformers (with meter counts)")
    def transformers(s: MeterService = Depends(svc)):
        return s.transformers()

    @app.get("/transformers/{code}", response_model=Transformer, tags=["network"], responses=ERRORS)
    def transformer(code: str, s: MeterService = Depends(svc)):
        return s.get_transformer(code)

    @app.get("/hierarchy", response_model=list[HierarchyNode], tags=["network"], responses=ERRORS,
             summary="Network tree: zone > circle > division > subdivision > substation > feeder > DT")
    def hierarchy(depth: int = Query(7, ge=1, le=7), s: MeterService = Depends(svc)):
        return s.hierarchy(depth)

    @app.get("/quality", response_model=QualitySummary, tags=["system"], responses=ERRORS,
             summary="Data-quality problems found in the portal's data")
    def quality(s: MeterService = Depends(svc)):
        return s.quality()

    return app


app = create_app()
