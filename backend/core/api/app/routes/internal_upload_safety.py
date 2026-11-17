# backend/core/api/app/routes/internal_upload_safety.py
#
# Internal-only second opinion for uploaded images. Surface: internal (upload
# server to core API, X-Internal-Service-Token); never exposed publicly. The
# upload server holds no decision-model credentials, so it sends the image here
# and gets back Jev label probabilities for the upload safety policy
# (backend/upload/services/upload_safety_policy.py). Image bytes are neither
# logged nor stored.

import logging
from typing import Dict

from fastapi import APIRouter, HTTPException, Request

from backend.core.api.app.utils.internal_auth import VerifiedInternalRequest
from backend.shared.python_utils.image_safety.jev_signals import jev_image_findings

logger = logging.getLogger(__name__)

MAX_SECOND_OPINION_BYTES = 25 * 1024 * 1024

router = APIRouter(
    prefix="/internal", tags=["Internal Services"],
    dependencies=[VerifiedInternalRequest], include_in_schema=False,
)


@router.post("/uploads/image-second-opinion")
async def image_second_opinion(request: Request) -> Dict[str, float]:
    """Return Jev probabilities {nudity, minor, gore} for the raw image in the body."""
    image_bytes = await request.body()
    if not image_bytes or len(image_bytes) > MAX_SECOND_OPINION_BYTES:
        raise HTTPException(status_code=413, detail="Image missing or too large")
    findings = await jev_image_findings(
        image_bytes=image_bytes, stage="upload", secrets_manager=request.app.state.secrets_manager
    )
    if findings is None:
        raise HTTPException(status_code=503, detail="Second opinion unavailable")
    probabilities = findings.raw["jev_probabilities"]
    return {
        "nudity": float(probabilities["nudity"]),
        "minor": float(probabilities["minor"]),
        "gore": float(probabilities["gore"]),
    }
