"""Private FastAPI entry point for engineering coordination.

The initial surface deliberately exposes only liveness and readiness. Mutating
routes will be added with scoped authentication after their PostgreSQL
transactions are covered by contract tests. This service has no product route.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from backend.engineering_control_plane.api import router
from backend.engineering_control_plane.config import Settings
from backend.engineering_control_plane.database import readiness


app = FastAPI(
    title="OpenMates Engineering Control Plane",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.include_router(router)


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready")
def health_ready() -> dict[str, str | int]:
    try:
        return readiness(Settings.from_environment())
    except Exception as exc:
        raise HTTPException(status_code=503, detail="control_plane_not_ready") from exc
