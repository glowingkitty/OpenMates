"""Retired pairing protocol. PIN-upload clients must update to pair/v2."""

from fastapi import APIRouter, HTTPException, Request

from backend.core.api.app.routes.auth_routes.auth_pair_v2 import router as v2_router

router = APIRouter()
router.include_router(v2_router)


@router.get("/pair/{legacy_path:path}")
@router.post("/pair/{legacy_path:path}")
@router.delete("/pair/{legacy_path:path}")
async def retired_pair_protocol(request: Request, legacy_path: str):
    # Deliberately do not parse a legacy request body: it may contain a PIN.
    raise HTTPException(status_code=426, detail="Pairing protocol update required")
