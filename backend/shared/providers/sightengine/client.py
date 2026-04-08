# backend/shared/providers/sightengine/client.py
#
# Sightengine safety classifier — shared client used by the image safety pipeline.
#
# Unlike the upload service (which only runs nudity-2.0+offensive+gore+genai),
# this client runs the EXTENDED model set required for generation-stage safety:
#   nudity-2.0, face-attributes, minor, deepfake, celebrities,
#   offensive, gore, weapon, genai
#
# The extended models cover the gaps that let the upload pipeline through:
#   - minor age estimation (CSAM defense, see policy §S1)
#   - celebrity identification (public figure block, see policy §S6)
#   - deepfake score (face manipulation detection)
#   - face-attributes (count + bbox for cross-checks with the VLM)
#
# Architecture: docs/architecture/image-safety-pipeline.md §1a

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import httpx

from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

SIGHTENGINE_API_URL = "https://api.sightengine.com/1.0/check.json"
SIGHTENGINE_SECRET_PATH = "kv/data/providers/sightengine"

# Model list used for every safety pipeline call (both input and output).
# Keep as a single combined request — one round-trip covers all signals.
SAFETY_MODELS = "nudity-2.0,face-attributes,offensive,gore,genai,celebrities"

# Input-stage thresholds — see docs/architecture/image-safety-pipeline.md §1a
# "Hard-block thresholds (input)" table.
INPUT_THRESHOLDS = {
    "sexual_activity": 0.3,
    "sexual_display": 0.3,
    "erotica": 0.4,
    "sextoy": 0.3,
    "suggestive": 0.6,
    "gore": 0.5,
    "blood": 0.6,
    "weapon": 0.7,
    "deepfake_with_celebrity": 0.9,
}

# Output-stage thresholds are stricter — see §4 "Hard-block thresholds (output)".
OUTPUT_THRESHOLDS = {
    **INPUT_THRESHOLDS,
    "minor_plus_any_nudity_or_suggestive": 0.0,  # zero tolerance on output
}


@dataclass
class SightengineFindings:
    """Structured Sightengine response for the safety pipeline."""

    # Hard block decision + category for the safeguard prompt
    hard_block: bool = False
    hard_block_reason: Optional[str] = None
    category_hint: Optional[str] = None  # e.g. "S1_csam", "S6_public_figure_blocked"

    # Raw signals — passed to the safeguard reasoner for tie-breaking
    sexual_activity: float = 0.0
    sexual_display: float = 0.0
    erotica: float = 0.0
    sextoy: float = 0.0
    suggestive: float = 0.0
    weapon: float = 0.0
    gore: float = 0.0
    blood: float = 0.0

    # Face / identity signals
    face_count: int = 0
    minor_detected: bool = False
    minor_confidence: float = 0.0
    celebrity_match: bool = False
    celebrity_name: Optional[str] = None
    celebrity_confidence: float = 0.0
    deepfake_score: float = 0.0

    # AI-generated probability (informational only)
    ai_generated: float = 0.0

    # Raw JSON for audit log
    raw: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_audit_dict(self) -> Dict[str, Any]:
        """Compact representation for the safety_audit_log collection."""
        return {
            "hard_block": self.hard_block,
            "hard_block_reason": self.hard_block_reason,
            "category_hint": self.category_hint,
            "scores": {
                "sexual_activity": round(self.sexual_activity, 3),
                "sexual_display": round(self.sexual_display, 3),
                "erotica": round(self.erotica, 3),
                "sextoy": round(self.sextoy, 3),
                "suggestive": round(self.suggestive, 3),
                "weapon": round(self.weapon, 3),
                "gore": round(self.gore, 3),
                "blood": round(self.blood, 3),
                "deepfake": round(self.deepfake_score, 3),
                "ai_generated": round(self.ai_generated, 3),
            },
            "faces": {
                "count": self.face_count,
                "minor_detected": self.minor_detected,
                "minor_confidence": round(self.minor_confidence, 3),
                "celebrity_match": self.celebrity_match,
                "celebrity_name": self.celebrity_name,
                "celebrity_confidence": round(self.celebrity_confidence, 3),
            },
            "error": self.error,
        }


class SightengineSafetyClient:
    """
    Shared Sightengine client for the image safety pipeline.

    Credentials come from the Vault KV path `kv/data/providers/sightengine`
    (api_user + api_secret) via SecretsManager. The client fails CLOSED on
    errors: any API failure produces `hard_block=True` so the pipeline can
    decide whether to fall through to the safeguard reasoner or reject.
    """

    def __init__(self) -> None:
        self._api_user: Optional[str] = None
        self._api_secret: Optional[str] = None
        self._initialized = False

    async def initialize(self, secrets_manager: SecretsManager) -> None:
        """Load credentials from Vault on first use. Safe to call multiple times."""
        if self._initialized:
            return
        try:
            self._api_user = await secrets_manager.get_secret(
                secret_path=SIGHTENGINE_SECRET_PATH, secret_key="api_user"
            )
            self._api_secret = await secrets_manager.get_secret(
                secret_path=SIGHTENGINE_SECRET_PATH, secret_key="api_secret"
            )
        except Exception as e:
            logger.error(
                f"[SightengineSafety] Failed to load credentials from Vault: {e}",
                exc_info=True,
            )
        self._initialized = True
        if not (self._api_user and self._api_secret):
            logger.error(
                "[SightengineSafety] Credentials missing — safety pipeline will "
                "fail closed on every call. Set SECRET__SIGHTENGINE__API_USER / "
                "SECRET__SIGHTENGINE__API_SECRET."
            )

    @property
    def is_enabled(self) -> bool:
        return bool(self._api_user and self._api_secret)

    async def analyze(
        self,
        image_bytes: bytes,
        *,
        stage: str = "input",
        filename: str = "image.webp",
    ) -> SightengineFindings:
        """
        Run the full safety model bundle against an image.

        Args:
            image_bytes: raw image bytes (plaintext)
            stage: "input" or "output" — selects threshold table
            filename: used only for multipart Content-Disposition

        Returns:
            SightengineFindings with hard_block decision + raw signals.
            On error, returns hard_block=True with error field populated.
        """
        if not self.is_enabled:
            return SightengineFindings(
                hard_block=True,
                hard_block_reason="sightengine_not_configured",
                error="credentials missing",
            )

        log_prefix = f"[SightengineSafety] [{stage}] [{filename[:30]}]"
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    SIGHTENGINE_API_URL,
                    data={
                        "models": SAFETY_MODELS,
                        "api_user": self._api_user,
                        "api_secret": self._api_secret,
                    },
                    files={
                        "media": (filename, image_bytes, "application/octet-stream"),
                    },
                )
        except Exception as e:
            logger.error(f"{log_prefix} HTTP error: {e}", exc_info=True)
            return SightengineFindings(
                hard_block=True,
                hard_block_reason="sightengine_http_error",
                error=str(e),
            )

        if resp.status_code != 200:
            logger.error(
                f"{log_prefix} API returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
            return SightengineFindings(
                hard_block=True,
                hard_block_reason="sightengine_api_error",
                error=f"HTTP {resp.status_code}",
            )

        data = resp.json()
        if data.get("status") != "success":
            err = data.get("error", {}).get("message", "unknown")
            logger.error(f"{log_prefix} API non-success: {err}")
            return SightengineFindings(
                hard_block=True,
                hard_block_reason="sightengine_api_error",
                error=err,
            )

        findings = self._parse_response(data)
        self._apply_thresholds(findings, stage=stage)
        logger.info(
            f"{log_prefix} block={findings.hard_block} reason={findings.hard_block_reason} "
            f"sexual={findings.sexual_activity:.2f} minor={findings.minor_detected} "
            f"celeb={findings.celebrity_match} deepfake={findings.deepfake_score:.2f}"
        )
        return findings

    @staticmethod
    def _parse_response(data: Dict[str, Any]) -> SightengineFindings:
        """Parse Sightengine JSON into structured findings."""
        nudity = data.get("nudity", {}) or {}
        offensive = data.get("offensive", {}) or {}
        gore = data.get("gore", {}) or {}
        faces = data.get("faces", []) or []
        # "faces" may also appear under "face" or "face-attributes"; normalize
        if not faces and isinstance(data.get("face"), dict):
            faces = data["face"].get("list", []) or []

        findings = SightengineFindings(
            sexual_activity=float(nudity.get("sexual_activity", 0.0)),
            sexual_display=float(nudity.get("sexual_display", 0.0)),
            erotica=float(nudity.get("erotica", 0.0)),
            sextoy=float(nudity.get("sextoy", 0.0)),
            suggestive=float(nudity.get("suggestive", 0.0)),
            weapon=float(offensive.get("weapon", 0.0)),
            gore=float(gore.get("gore", 0.0)),
            blood=float(gore.get("blood", 0.0)),
            ai_generated=float((data.get("type") or {}).get("ai_generated", 0.0)),
            raw=data,
        )

        # Face + minor + celebrity + deepfake extraction.
        # Sightengine places face attributes inside each face object in `faces`.
        face_list = faces if isinstance(faces, list) else []
        findings.face_count = len(face_list)

        minor_conf = 0.0
        celeb_conf = 0.0
        deepfake = 0.0
        celeb_name: Optional[str] = None

        for face in face_list:
            if not isinstance(face, dict):
                continue
            attrs = face.get("attributes", {}) or {}
            # minor score
            minor_score = float(attrs.get("minor", 0.0) or face.get("minor", 0.0) or 0.0)
            if minor_score > minor_conf:
                minor_conf = minor_score
            # celebrity match
            celeb = face.get("celebrity", []) or []
            if isinstance(celeb, list) and celeb:
                top = celeb[0]
                cs = float(top.get("prob", 0.0))
                if cs > celeb_conf:
                    celeb_conf = cs
                    celeb_name = top.get("name")
            # deepfake
            df = float(face.get("deepfake", 0.0) or attrs.get("deepfake", 0.0) or 0.0)
            if df > deepfake:
                deepfake = df

        findings.minor_confidence = minor_conf
        findings.minor_detected = minor_conf > 0.5
        findings.celebrity_match = celeb_conf > 0.5
        findings.celebrity_confidence = celeb_conf
        findings.celebrity_name = celeb_name
        findings.deepfake_score = deepfake

        return findings

    @staticmethod
    def _apply_thresholds(f: SightengineFindings, *, stage: str) -> None:
        """Set hard_block + reason based on the stage-specific threshold table."""
        thresholds = OUTPUT_THRESHOLDS if stage == "output" else INPUT_THRESHOLDS

        # Highest-severity checks first (CSAM + minors).
        if f.minor_detected and (
            f.sexual_activity > 0.05
            or f.sexual_display > 0.05
            or f.erotica > 0.05
            or f.sextoy > 0.05
        ):
            f.hard_block = True
            f.hard_block_reason = "minor_plus_sexual_content"
            f.category_hint = "S1_csam"
            return
        if f.minor_detected and f.suggestive > 0.2:
            f.hard_block = True
            f.hard_block_reason = "minor_plus_suggestive"
            f.category_hint = "S1_csam"
            return
        if stage == "output" and f.minor_detected and (
            f.sexual_activity > 0 or f.sexual_display > 0 or f.suggestive > 0
        ):
            f.hard_block = True
            f.hard_block_reason = "minor_on_output_any_suggestion"
            f.category_hint = "S1_csam"
            return

        if f.sexual_activity > thresholds["sexual_activity"]:
            f.hard_block = True
            f.hard_block_reason = f"sexual_activity={f.sexual_activity:.2f}"
            f.category_hint = "S3_sexual_other"
            return
        if f.sexual_display > thresholds["sexual_display"]:
            f.hard_block = True
            f.hard_block_reason = f"sexual_display={f.sexual_display:.2f}"
            f.category_hint = "S3_sexual_other"
            return
        if f.erotica > thresholds["erotica"]:
            f.hard_block = True
            f.hard_block_reason = f"erotica={f.erotica:.2f}"
            f.category_hint = "S3_sexual_other"
            return
        if f.sextoy > thresholds["sextoy"]:
            f.hard_block = True
            f.hard_block_reason = f"sextoy={f.sextoy:.2f}"
            f.category_hint = "S3_sexual_other"
            return
        if f.gore > thresholds["gore"]:
            f.hard_block = True
            f.hard_block_reason = f"gore={f.gore:.2f}"
            f.category_hint = "S4_violent_recontextualization"
            return
        if f.blood > thresholds["blood"]:
            f.hard_block = True
            f.hard_block_reason = f"blood={f.blood:.2f}"
            f.category_hint = "S4_violent_recontextualization"
            return

        # Deepfake + celebrity combo — strict public figure policy
        if f.celebrity_match:
            f.hard_block = True
            f.hard_block_reason = f"celebrity={f.celebrity_name or 'unknown'}"
            f.category_hint = "S6_public_figure_blocked"
            return
        if f.deepfake_score > thresholds["deepfake_with_celebrity"]:
            f.hard_block = True
            f.hard_block_reason = f"deepfake_score={f.deepfake_score:.2f}"
            f.category_hint = "S7_identity_replacement"
            return


# Module-level singleton — one shared client per process.
_singleton: Optional[SightengineSafetyClient] = None


def get_sightengine_safety_client() -> SightengineSafetyClient:
    """Return the process-wide Sightengine safety client singleton."""
    global _singleton
    if _singleton is None:
        _singleton = SightengineSafetyClient()
    return _singleton
