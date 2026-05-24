# backend/shared/python_utils/media_generation_safety/pipeline.py
#
# Deterministic prompt-level safety gate for AI-generated media.
# This catches high-confidence abuse patterns before images, videos, or music
# providers are called. It is intentionally conservative and transparent: the
# policy is rule-based, testable, and complements provider/native safeguards.

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional


MAX_IMAGE_REQUESTS_PER_CALL = 5
MAX_VIDEO_REQUESTS_PER_CALL = 1
MAX_MUSIC_REQUESTS_PER_CALL = 5

_FAMOUS_PERSON_CONTEXT_RE = re.compile(
    r"\b(?:in|imitat(?:e|ing)|clone|copy|mimic|sound(?:s)?\s+like|"
    r"voice\s+of|style\s+of|persona\s+of|as\s+if\s+(?:it\s+were\s+)?(?:by|from)|"
    r"narrat(?:e|ion)\s+(?:by|like)|sing(?:ing)?\s+like|deepfake)\b",
    re.IGNORECASE,
)
_NAMED_PERSON_HINT_RE = re.compile(
    r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b"
)
_PUBLIC_ROLE_RE = re.compile(
    r"\b(?:politician|president|prime\s+minister|minister|senator|governor|"
    r"celebrity|actor|actress|singer|rapper|musician|artist|comedian|"
    r"famous|well-known|journalist|news\s+anchor|youtuber|influencer|streamer|ceo|founder|"
    r"professor|scientist|science\s+educators?|educators?|doctor|therapist|"
    r"religious\s+leader|historical\s+figure)\b",
    re.IGNORECASE,
)
_VOICE_OR_PERSONA_RE = re.compile(
    r"\b(?:voice|vocal|vocals|narrator|narration|speech|spoken|accent|cadence|"
    r"delivery|persona|likeness|face|appearance|cameo|testimonial|endorsement)\b",
    re.IGNORECASE,
)
_NAMED_PERSON_MEDIA_USE_RE = re.compile(
    r"\b(?:portrait|photo|image|video|clip|footage|song|track|jingle|ad|advert|"
    r"endorsement|testimonial|speech|announcement|interview|cameo)\s+(?:of|by|from|with)\s+"
    r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b|"
    r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\s+"
    r"(?:endors(?:e|ing|ement)|testimonial|sing(?:s|ing)?|narrat(?:e|es|ing)|"
    r"says|announces|promotes|portrait|photo|image|video|clip|footage|song|track|"
    r"walking|speaking|dancing|performing)\b",
)
_MONONYM_VOICE_OR_PERSONA_RE = re.compile(
    r"\b[A-Z][a-z]{2,}(?:'s|’s)?\s+(?:voice|vocal|vocals|likeness|persona|"
    r"face|appearance|endorsement|testimonial|cadence|delivery)\b",
)
_SCAM_RE = re.compile(
    r"\b(?:phishing|fake\s+login|credential\s+(?:harvest|harvesting)|seed\s+phrase|wallet\s+drain|"
    r"pump\s+and\s+dump|rug\s+pull|guaranteed\s+(?:profit|returns?)|get\s+rich\s+quick|"
    r"fake\s+(?:testimonial|review|endorsement|invoice|receipt|certificate|id|passport|"
    r"driver'?s\s+license|medical\s+record|bank\s+statement)|counterfeit|impersonat(?:e|ion))\b",
    re.IGNORECASE,
)
_SPAM_RE = re.compile(
    r"\b(?:spam|content\s+farm|seo\s+farm|mass\s+(?:produce|generate|post|upload)|"
    r"(?:50|100|500|1000)\s+(?:ads|videos|images|posts|thumbnails|jingles|songs|variations)|"
    r"go\s+viral|bypass\s+(?:moderation|detection|watermark)|remove\s+(?:watermark|ai\s+label))\b",
    re.IGNORECASE,
)
_DECEPTIVE_MEDIA_RE = re.compile(
    r"\b(?:realistic\s+footage\s+of|make\s+it\s+look\s+real|leaked\s+(?:audio|video)|"
    r"breaking\s+news\s+clip|security\s+camera\s+footage|bodycam\s+footage|"
    r"confession\s+video|public\s+apology|official\s+announcement)\b",
    re.IGNORECASE,
)

_USEFUL_CONTEXT_RE = re.compile(
    r"\b(?:prototype|mockup|draft|concept|educational|lesson|explainer|accessibility|"
    r"internal|personal|study|research|presentation|storyboard|design|brand\s+guide|"
    r"product\s+demo|documentation|tutorial|portfolio)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MediaGenerationDecision:
    allowed: bool
    category: Optional[str] = None
    severity: str = "none"
    user_facing_message: Optional[str] = None
    reason: Optional[str] = None

    def to_rejection_payload(self) -> dict[str, object]:
        return {
            "error": "media_generation_safety_rejection",
            "category": self.category or "unknown",
            "severity": self.severity,
            "user_facing_message": self.user_facing_message
            or "This media request couldn't be generated.",
            "instructions_to_llm": (
                "Do not retry this request or reformulate it in the same response. "
                "Briefly relay the user_facing_message and offer to help with an "
                "original, non-deceptive alternative."
            ),
            "do_not_retry": True,
        }


class MediaGenerationSafetyRejection(ValueError):
    """Raised when a generated-media request is blocked before provider use."""

    def __init__(self, decision: MediaGenerationDecision) -> None:
        super().__init__(decision.user_facing_message or "Media generation rejected")
        self.decision = decision


def _join_text(parts: Iterable[Optional[object]]) -> str:
    return "\n".join(str(part) for part in parts if part is not None and str(part).strip())


def _request_limit_for_media(media_type: str) -> int:
    if media_type == "video":
        return MAX_VIDEO_REQUESTS_PER_CALL
    if media_type == "music":
        return MAX_MUSIC_REQUESTS_PER_CALL
    return MAX_IMAGE_REQUESTS_PER_CALL


def validate_media_generation_request(
    *,
    media_type: str,
    prompt: str,
    request_count: int = 1,
    mode: Optional[str] = None,
    style: Optional[str] = None,
    lyrics: Optional[str] = None,
    negative_prompt: Optional[str] = None,
) -> MediaGenerationDecision:
    """Return a deterministic allow/block decision for generated-media prompts."""
    normalized_media_type = media_type.lower().strip()
    max_requests = _request_limit_for_media(normalized_media_type)
    if request_count > max_requests:
        return MediaGenerationDecision(
            allowed=False,
            category="G0_batch_limit",
            severity="moderate",
            user_facing_message=(
                f"Please generate at most {max_requests} {normalized_media_type} "
                "request(s) at a time."
            ),
            reason="request_count_exceeds_limit",
        )

    text = _join_text([prompt, mode, style, lyrics, negative_prompt])
    if not text.strip():
        return MediaGenerationDecision(allowed=True)

    if _SCAM_RE.search(text):
        return MediaGenerationDecision(
            allowed=False,
            category="G1_scam_or_fraud",
            severity="severe",
            user_facing_message=(
                "I can't help create deceptive, fraudulent, or scam-related media."
            ),
            reason="scam_or_fraud_pattern",
        )

    if _SPAM_RE.search(text) and not _USEFUL_CONTEXT_RE.search(text):
        return MediaGenerationDecision(
            allowed=False,
            category="G2_spam_or_slop",
            severity="moderate",
            user_facing_message=(
                "I can't help mass-produce low-value spam or evade AI-content detection."
            ),
            reason="spam_or_detection_evasion_pattern",
        )

    has_voice_or_persona = bool(_VOICE_OR_PERSONA_RE.search(text))
    has_public_role = bool(_PUBLIC_ROLE_RE.search(text))
    has_named_person = bool(_NAMED_PERSON_HINT_RE.search(text))
    has_imitation_context = bool(_FAMOUS_PERSON_CONTEXT_RE.search(text))
    has_named_person_media_use = bool(_NAMED_PERSON_MEDIA_USE_RE.search(text))
    has_mononym_voice_or_persona = bool(_MONONYM_VOICE_OR_PERSONA_RE.search(text))
    if has_named_person_media_use or has_mononym_voice_or_persona or (has_named_person and has_voice_or_persona):
        return MediaGenerationDecision(
            allowed=False,
            category="G3_public_figure_voice_or_persona",
            severity="severe",
            user_facing_message=(
                "I can't generate media that imitates a real public figure's voice, "
                "likeness, persona, or endorsement. I can help create an original "
                "voice or style instead."
            ),
            reason="named_person_synthetic_media_pattern",
        )

    if has_imitation_context and (has_voice_or_persona or has_public_role or has_named_person):
        return MediaGenerationDecision(
            allowed=False,
            category="G3_public_figure_voice_or_persona",
            severity="severe",
            user_facing_message=(
                "I can't generate media that imitates a real public figure's voice, "
                "likeness, persona, or endorsement. I can help create an original "
                "voice or style instead."
            ),
            reason="public_figure_or_voice_imitation_pattern",
        )

    if normalized_media_type in {"video", "music"} and _DECEPTIVE_MEDIA_RE.search(text):
        return MediaGenerationDecision(
            allowed=False,
            category="G4_deceptive_synthetic_media",
            severity="severe",
            user_facing_message=(
                "I can't help create synthetic media intended to look like real footage, "
                "a real statement, or an official endorsement."
            ),
            reason="deceptive_synthetic_media_pattern",
        )

    return MediaGenerationDecision(allowed=True)
