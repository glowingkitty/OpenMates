# backend/upload/services/jev_second_opinion.py
#
# Second-opinion client for the upload safety policy. The upload server holds no
# decision-model credentials, so the image goes to the core API's internal
# endpoint (/internal/uploads/image-second-opinion), which asks the Jev decision
# model. Returns None when the opinion is unavailable; the policy then refuses
# without a strike.

import logging
from typing import Optional

import httpx

from backend.upload.services.upload_safety_policy import JevImageOpinion, SecondOpinion

logger = logging.getLogger(__name__)

SECOND_OPINION_PATH = "/internal/uploads/image-second-opinion"
SECOND_OPINION_TIMEOUT_SECONDS = 40.0


def make_second_opinion(core_api_url: str, internal_token: str, image_bytes: bytes) -> SecondOpinion:
    """Bind one image to a callable that fetches the Jev opinion through the core API."""

    async def second_opinion() -> Optional[JevImageOpinion]:
        if not core_api_url or not internal_token:
            logger.warning("[Upload ContentSafety] Core API not configured; no second opinion")
            return None
        try:
            async with httpx.AsyncClient(timeout=SECOND_OPINION_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    f"{core_api_url}{SECOND_OPINION_PATH}",
                    content=image_bytes,
                    headers={
                        "X-Internal-Service-Token": internal_token,
                        "Content-Type": "application/octet-stream",
                    },
                )
            if resp.status_code != 200:
                logger.warning(f"[Upload ContentSafety] Second opinion HTTP {resp.status_code}")
                return None
            body = resp.json()
            return JevImageOpinion(
                nudity=float(body["nudity"]), minor=float(body["minor"]), gore=float(body["gore"])
            )
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            logger.warning(f"[Upload ContentSafety] Second opinion failed ({type(exc).__name__})")
            return None

    return second_opinion
