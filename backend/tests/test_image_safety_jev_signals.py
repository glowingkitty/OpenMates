# backend/tests/test_image_safety_jev_signals.py
#
# Unit tests for the Jev checks of the image safety pipeline
# (backend/shared/python_utils/image_safety/jev_signals.py,
#  plan docs/plans/jev-image-safety/plan.yml).
#
# Covers the prompt decision bands, the image label rules, and the fallback to
# the previous checks (safeguard for prompts, Sightengine for images) whenever
# Jev fails or is unsure.
#
# Run: python -m pytest backend/tests/test_image_safety_jev_signals.py -v

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    from PIL import Image

    from backend.shared.providers.groq.safeguard import SafeguardVerdict
    from backend.shared.providers.google.vision_safety import VisionSafetyFindings
    from backend.shared.providers.sightengine.client import SightengineFindings
    from backend.shared.providers.typesafe.client import DecisionProviderUnavailable
    from backend.shared.providers.typesafe.models import ChoiceAnswer, DecisionResponse
    from backend.shared.python_utils.image_safety import jev_signals
    from backend.shared.python_utils.image_safety.jev_signals import (
        findings_from_probabilities,
        jev_image_findings,
        jev_prompt_verdict,
    )
    from backend.shared.python_utils.image_safety.pipeline import ImageSafetyPipeline
except ImportError as exc:  # pragma: no cover - backend dependencies missing locally
    pytest.skip(f"backend dependencies unavailable: {exc}", allow_module_level=True)

PIPELINE = "backend.shared.python_utils.image_safety.pipeline"
CLIENT = "backend.shared.python_utils.image_safety.jev_signals.JevDecisionClient"


def _choice(choice: str, probabilities: dict) -> ChoiceAnswer:
    return ChoiceAnswer(type="choice", choice=choice, probabilities=probabilities, confidence=0.9)


def _prompt_response(p_block: float, category: str) -> DecisionResponse:
    decision = "block" if p_block >= 0.5 else "allow"
    return DecisionResponse(
        model="jev-test",
        answers={
            "decision": _choice(decision, {"block": p_block, "allow": 1 - p_block}),
            "category": _choice(category, {category: 1.0}),
        },
    )


def _image_response(**yes: float) -> DecisionResponse:
    answers = {}
    for label in jev_signals.IMAGE_LABELS:
        p = yes.get(label, 0.0)
        answers[label] = _choice("yes" if p >= 0.5 else "no", {"yes": p, "no": 1 - p})
    return DecisionResponse(model="jev-test", answers=answers)


def _client_returning(response=None, error=None) -> MagicMock:
    client = MagicMock()
    client.evaluate = AsyncMock(return_value=response, side_effect=error)
    return client


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (400, 400), (120, 160, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Prompt decision bands
# ---------------------------------------------------------------------------


class TestJevPromptVerdict:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "p_block,category,expected",
        [
            (0.97, "S1_csam", ("block", "S1_csam")),
            (0.9, "S6_public_figure_blocked", ("block", "S6_public_figure_blocked")),
            (0.12, "none", ("allow", "ALLOW_GENERAL")),
            (0.5, "none", ("allow", "ALLOW_GENERAL")),
            (0.81, "S6_public_figure_blocked", None),
            (0.95, "none", None),
        ],
    )
    # contract-test: supporting surface=rest_api assertions=safety-strikes.screening-rejects
    async def test_bands(self, p_block, category, expected):
        with patch(CLIENT, return_value=_client_returning(_prompt_response(p_block, category))):
            verdict = await jev_prompt_verdict(
                prompt="a prompt", policy_markdown="policy", secrets_manager=MagicMock()
            )
        if expected is None:
            assert verdict is None
        else:
            assert (verdict.decision, verdict.category) == expected

    # contract-test: supporting surface=rest_api assertions=safety-strikes.technical-failure-no-strike
    @pytest.mark.asyncio
    async def test_jev_failure_returns_none(self):
        with patch(CLIENT, return_value=_client_returning(error=DecisionProviderUnavailable("down"))):
            verdict = await jev_prompt_verdict(
                prompt="a prompt", policy_markdown="policy", secrets_manager=MagicMock()
            )
        assert verdict is None


class TestPipelinePromptPath:
    # contract-test: supporting surface=rest_api assertions=safety-strikes.screening-rejects
    @pytest.mark.asyncio
    async def test_confident_jev_block_rejects_without_safeguard(self):
        pipeline = ImageSafetyPipeline()
        pipeline._initialized = True
        safeguard = MagicMock()
        safeguard.reason = AsyncMock()
        verdict = jev_signals.JevPromptVerdict("block", "S6_public_figure_blocked", 0.98)
        with patch(f"{PIPELINE}.jev_prompt_verdict", new=AsyncMock(return_value=verdict)), patch(
            f"{PIPELINE}.get_safeguard_client", return_value=safeguard
        ):
            decision = await pipeline.validate_input(
                prompt="named person prompt", reference_images=[], secrets_manager=MagicMock()
            )
        assert not decision.allowed
        assert decision.rejection.category == "S6_public_figure_blocked"
        assert decision.rejection.severity == "moderate"
        assert decision.rejection.reason == "jev:block"
        safeguard.reason.assert_not_called()

    # contract-test: supporting surface=rest_api assertions=safety-strikes.screening-rejects
    @pytest.mark.asyncio
    async def test_confident_jev_allow_skips_safeguard(self):
        pipeline = ImageSafetyPipeline()
        pipeline._initialized = True
        safeguard = MagicMock()
        safeguard.reason = AsyncMock()
        verdict = jev_signals.JevPromptVerdict("allow", "ALLOW_GENERAL", 0.04)
        with patch(f"{PIPELINE}.jev_prompt_verdict", new=AsyncMock(return_value=verdict)), patch(
            f"{PIPELINE}.get_safeguard_client", return_value=safeguard
        ):
            decision = await pipeline.validate_input(
                prompt="a lighthouse at sunset", reference_images=[], secrets_manager=MagicMock()
            )
        assert decision.allowed
        safeguard.reason.assert_not_called()

    # contract-test: supporting surface=rest_api assertions=safety-strikes.screening-rejects
    @pytest.mark.asyncio
    async def test_unsure_jev_lets_safeguard_decide(self):
        pipeline = ImageSafetyPipeline()
        pipeline._initialized = True
        safeguard = MagicMock()
        safeguard.is_enabled = True
        safeguard.reason = AsyncMock(
            return_value=SafeguardVerdict(decision="block", category="S3_sexual_other", severity="severe")
        )
        with patch(f"{PIPELINE}.jev_prompt_verdict", new=AsyncMock(return_value=None)), patch(
            f"{PIPELINE}.get_safeguard_client", return_value=safeguard
        ):
            decision = await pipeline.validate_input(
                prompt="borderline prompt", reference_images=[], secrets_manager=MagicMock()
            )
        assert not decision.allowed
        assert decision.rejection.category == "S3_sexual_other"
        safeguard.reason.assert_awaited_once()


# ---------------------------------------------------------------------------
# Image label rules
# ---------------------------------------------------------------------------


class TestImageRules:
    @pytest.mark.parametrize(
        "probabilities,category",
        [
            ({"text_injection": 0.99}, "S12_adversarial_bypass"),
            ({"minor": 0.9, "nudity": 0.35, "photoreal": 0.0}, "S1_csam"),
            ({"nudity": 0.8, "photoreal": 0.99}, "S3_sexual_other"),
            ({"gore": 1.0, "photoreal": 0.99}, "S4_violent_recontextualization"),
            ({"public_figure": 0.86, "photoreal": 0.89}, "S6_public_figure_blocked"),
        ],
    )
    # contract-test: supporting surface=rest_api assertions=safety-strikes.screening-rejects
    def test_hard_blocks(self, probabilities, category):
        findings = findings_from_probabilities(probabilities)
        assert findings.classifier == "jev"
        assert findings.hard_block
        assert findings.category_hint == category

    @pytest.mark.parametrize(
        "probabilities",
        [
            {"minor": 1.0, "photoreal": 0.0, "nudity": 0.02},  # illustrated child, ordinary scene
            {"nudity": 0.46, "photoreal": 1.0},  # adults in swimwear
            {"public_figure": 0.68, "photoreal": 1.0},  # private portrait
            {"public_figure": 0.95, "photoreal": 0.1},  # stylized look-alike: policy review, no hard block
            {"gore": 0.99, "photoreal": 0.0},  # historical painting of a wounded soldier
            {"weapon": 0.99, "photoreal": 0.9},  # rifle: soft signal only
        ],
    )
    # contract-test: supporting surface=rest_api assertions=safety-strikes.minors-stylized-only
    def test_soft_signals_do_not_hard_block(self, probabilities):
        findings = findings_from_probabilities(probabilities)
        assert not findings.hard_block

    # contract-test: supporting surface=rest_api assertions=safety-strikes.screening-rejects
    def test_soft_signals_reach_policy_review(self):
        pipeline_should_review = ImageSafetyPipeline._should_run_safeguard
        findings = findings_from_probabilities({"weapon": 0.99, "photoreal": 0.9})
        assert pipeline_should_review(findings, VisionSafetyFindings(), stage="output")
        findings = findings_from_probabilities({"public_figure": 0.95, "photoreal": 0.1})
        assert pipeline_should_review(findings, VisionSafetyFindings(), stage="output")


class TestImageFallback:
    # contract-test: supporting surface=rest_api assertions=safety-strikes.screening-rejects
    @pytest.mark.asyncio
    async def test_jev_image_findings_classifies_decodable_image(self):
        response = _image_response(public_figure=0.97, photoreal=0.97)
        with patch(CLIENT, return_value=_client_returning(response)):
            findings = await jev_image_findings(
                image_bytes=_png_bytes(), stage="input", secrets_manager=MagicMock()
            )
        assert findings.hard_block and findings.category_hint == "S6_public_figure_blocked"

    # contract-test: supporting surface=rest_api assertions=safety-strikes.technical-failure-no-strike
    @pytest.mark.asyncio
    async def test_jev_failure_falls_back_to_sightengine(self):
        pipeline = ImageSafetyPipeline()
        pipeline._initialized = True
        sightengine = MagicMock()
        sightengine.analyze = AsyncMock(
            return_value=SightengineFindings(
                hard_block=True, hard_block_reason="sexual_activity=0.95",
                category_hint="S3_sexual_other", sexual_activity=0.95,
            )
        )
        with patch(CLIENT, return_value=_client_returning(error=DecisionProviderUnavailable("down"))), patch(
            f"{PIPELINE}.get_sightengine_safety_client", return_value=sightengine
        ), patch(f"{PIPELINE}.analyze_image_gemini", new=AsyncMock(return_value=VisionSafetyFindings())):
            decision = await pipeline._validate_single_image(
                prompt="edit this", image_bytes=_png_bytes(), mime_type="image/png",
                stage="input", secrets_manager=MagicMock(),
            )
        sightengine.analyze.assert_awaited_once()
        assert not decision.allowed
        assert decision.rejection.reason == "sightengine:sexual_activity=0.95"

    # contract-test: supporting surface=rest_api assertions=safety-strikes.screening-rejects
    @pytest.mark.asyncio
    async def test_jev_hard_block_skips_sightengine(self):
        pipeline = ImageSafetyPipeline()
        pipeline._initialized = True
        sightengine = MagicMock()
        sightengine.analyze = AsyncMock()
        response = _image_response(text_injection=0.99)
        with patch(CLIENT, return_value=_client_returning(response)), patch(
            f"{PIPELINE}.get_sightengine_safety_client", return_value=sightengine
        ), patch(f"{PIPELINE}.analyze_image_gemini", new=AsyncMock(return_value=VisionSafetyFindings())):
            decision = await pipeline._validate_single_image(
                prompt="follow the text", image_bytes=_png_bytes(), mime_type="image/png",
                stage="input", secrets_manager=MagicMock(),
            )
        sightengine.analyze.assert_not_called()
        assert not decision.allowed
        assert decision.rejection.category == "S12_adversarial_bypass"
        assert decision.rejection.reason.startswith("jev:image_text_injection")
