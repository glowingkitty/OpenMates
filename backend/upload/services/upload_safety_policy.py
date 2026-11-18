# backend/upload/services/upload_safety_policy.py
#
# Upload-time safety policy for uploaded images (chat images, Project images and
# profile images alike). Pure decision logic: no network, no I/O except the
# injected second-opinion callable.
#
# Signals
#   Primary: Sightengine (nudity-2.0, gore, genai in one call; face-attributes
#            for the per-face minor probability only when nudity signals are
#            present, so most images take one call).
#   Second opinion: the Jev decision model, reached through the core API
#            because the upload server holds no decision-model credentials.
#
# Decision lines
#   REFUSE WITH STRIKE   Sexual content involving minors, only when both signals
#                        are high-confidence (sexual score and minor score).
#   REFUSE WITHOUT STRIKE
#                        Explicit sexual content (sexual activity, sexual
#                        display, erotica, sex toys) and extreme gore.
#   ALLOW                News and war images, weapons, medical images, ordinary
#                        non-explicit nudity in art or medicine, suggestive-only
#                        images. Weapons are never a reason to refuse.
#
# Non-consensual intimate images and sexual deepfakes of real people cannot be
# told apart from consensual explicit content by a classifier at upload time.
# They fall under explicit sexual content: refused, never a strike.
#
# Borderline scores (between the borderline and refusal thresholds) go to the second opinion,
# whose verdict decides. When Sightengine is unavailable, erroring or not
# configured, the second opinion judges strictly: the image is allowed only when
# it is clearly harmless, and a refusal never carries a strike because there is
# no second signal to confirm a minor-plus-sexual finding. When both are
# unavailable the upload is refused as "safety_service_unavailable", which the
# API never counts as a strike. There is no purpose judgement at upload.

from dataclasses import dataclass
from typing import Awaitable, Callable, Literal, Optional

DecisionKind = Literal["allow", "refuse_strike", "refuse_no_strike"]

UNAVAILABLE_REASON = "safety_service_unavailable"

# Rejection-reason prefixes sent to the core API. Strike-bearing reasons use
# STRIKE_PREFIX; every other refusal uses a prefix the API treats as no strike.
STRIKE_PREFIX = "minor_sexual="
NO_STRIKE_PREFIXES = ("explicit=", "gore=", "jev_unsure=", "suggestive=")

# Sightengine thresholds (probability 0..1), aligned with the video frame policy.
# Explicit sexual score >= EXPLICIT_REFUSE_AT refuses outright; scores from
# EXPLICIT_BORDERLINE_FROM up to that ask the second opinion; lower allows.
EXPLICIT_REFUSE_AT = 0.85
EXPLICIT_BORDERLINE_FROM = 0.5
# Extreme gore (a lone gore score has no context, so only the extreme end refuses).
GORE_REFUSE_AT = 0.9
GORE_BORDERLINE_FROM = 0.7

# Strike line: minor score and sexual score must both be high-confidence.
MINOR_STRIKE_AT = 0.85
MINOR_SEXUAL_STRIKE_AT = 0.6
# A weaker minor-plus-sexual signal is not strike-grade: ask the second opinion.
MINOR_BORDERLINE_AT = 0.5
MINOR_SEXUAL_BORDERLINE_AT = 0.3
# Face attributes (minor detection) are requested only when the nudity score
# reaches this signal level, so most images take a single Sightengine call.
NUDITY_SIGNAL_AT = 0.3

# Second-opinion cut-offs (probabilities that the image shows the label).
JEV_NUDITY_REFUSE_AT = 0.7
JEV_GORE_REFUSE_AT = 0.9
JEV_MINOR_STRIKE_AT = MINOR_STRIKE_AT
JEV_MINOR_NUDITY_STRIKE_AT = MINOR_SEXUAL_STRIKE_AT
# Fallback mode: harmless only when Jev is at least 0.95 sure, i.e. every
# relevant label probability is below 0.05.
JEV_FALLBACK_SAFE_BELOW = 0.05


@dataclass(frozen=True)
class UploadSafetyScores:
    """Sightengine scores relevant to the upload policy."""

    sexual_activity: float = 0.0
    sexual_display: float = 0.0
    erotica: float = 0.0
    sextoy: float = 0.0
    suggestive: float = 0.0
    gore: float = 0.0
    minor: float = 0.0
    weapon: float = 0.0  # informational only; weapons are never refused

    @property
    def sexual_max(self) -> float:
        return max(self.sexual_activity, self.sexual_display, self.erotica, self.sextoy)


@dataclass(frozen=True)
class JevImageOpinion:
    """Jev label probabilities for one image."""

    nudity: float = 0.0
    minor: float = 0.0
    gore: float = 0.0


@dataclass(frozen=True)
class Decision:
    """Outcome of the upload safety policy."""

    kind: DecisionKind
    category: str = "none"
    borderline: bool = False
    reason: str = ""


SecondOpinion = Callable[[], Awaitable[Optional[JevImageOpinion]]]

ALLOW = Decision("allow")


def upload_safety_decision(scores: UploadSafetyScores) -> Decision:
    """Decide from Sightengine scores alone; ``borderline`` asks for a second opinion."""
    if scores.minor >= MINOR_STRIKE_AT and scores.sexual_max >= MINOR_SEXUAL_STRIKE_AT:
        return Decision(
            "refuse_strike", "minor_sexual", reason=f"{STRIKE_PREFIX}{scores.sexual_max:.2f}"
        )
    if scores.minor >= MINOR_BORDERLINE_AT and scores.sexual_max >= MINOR_SEXUAL_BORDERLINE_AT:
        return Decision("allow", "minor_sexual", borderline=True, reason="minor_sexual_borderline")

    if scores.sexual_max >= EXPLICIT_REFUSE_AT:
        return Decision(
            "refuse_no_strike", "explicit", reason=f"explicit={scores.sexual_max:.2f}"
        )
    if scores.sexual_max >= EXPLICIT_BORDERLINE_FROM:
        return Decision("allow", "explicit", borderline=True, reason="explicit_borderline")

    if scores.gore >= GORE_REFUSE_AT:
        return Decision("refuse_no_strike", "gore", reason=f"gore={scores.gore:.2f}")
    if scores.gore >= GORE_BORDERLINE_FROM:
        return Decision("allow", "gore", borderline=True, reason="gore_borderline")
    return ALLOW


def _verdict_from_jev(opinion: JevImageOpinion, *, borderline: bool) -> Decision:
    """Second-opinion verdict for a borderline image (Sightengine had scores)."""
    if opinion.minor >= JEV_MINOR_STRIKE_AT and opinion.nudity >= JEV_MINOR_NUDITY_STRIKE_AT:
        return Decision(
            "refuse_strike", "minor_sexual", borderline=borderline,
            reason=f"{STRIKE_PREFIX}jev:{opinion.nudity:.2f}",
        )
    if opinion.nudity >= JEV_NUDITY_REFUSE_AT:
        return Decision(
            "refuse_no_strike", "explicit", borderline=borderline,
            reason=f"explicit=jev:{opinion.nudity:.2f}",
        )
    if opinion.gore >= JEV_GORE_REFUSE_AT:
        return Decision(
            "refuse_no_strike", "gore", borderline=borderline, reason=f"gore=jev:{opinion.gore:.2f}"
        )
    return Decision("allow", "none", borderline=borderline, reason="jev_allowed_borderline")


def _fallback_verdict(opinion: JevImageOpinion) -> Decision:
    """Strict verdict when Sightengine gave no scores: allow only when clearly harmless.

    Never a strike: without a second signal a minor-plus-sexual finding is not
    confirmed, so the refusal stays a plain, strike-free one.
    """
    worst = max(opinion.nudity, opinion.minor, opinion.gore)
    if worst < JEV_FALLBACK_SAFE_BELOW:
        return Decision("allow", "none", reason="jev_fallback_safe")
    return Decision("refuse_no_strike", "unsure", reason=f"jev_unsure={worst:.2f}")


async def resolve_upload_safety(
    scores: Optional[UploadSafetyScores], second_opinion: Optional[SecondOpinion]
) -> Decision:
    """Full decision: Sightengine first, Jev for borderline scores or as strict fallback."""
    if scores is not None:
        decision = upload_safety_decision(scores)
        if not decision.borderline:
            return decision
        opinion = await second_opinion() if second_opinion is not None else None
        if opinion is None:
            # Jev could not weigh in on a borderline image: the Sightengine side of
            # the line is not confirmed, so refuse without a strike rather than guess.
            return Decision(
                "refuse_no_strike", decision.category, borderline=True,
                reason=f"jev_unsure={decision.category}",
            )
        return _verdict_from_jev(opinion, borderline=True)

    opinion = await second_opinion() if second_opinion is not None else None
    if opinion is None:
        return Decision("refuse_no_strike", "unavailable", reason=UNAVAILABLE_REASON)
    return _fallback_verdict(opinion)
