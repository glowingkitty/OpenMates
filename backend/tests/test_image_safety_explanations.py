# backend/tests/test_image_safety_explanations.py
#
# A refused image request explains itself: a category-level reason in the
# user's language and, where one fits, the allowed alternative. Hard limits
# (child sexual abuse, intimate images of real people, safety-rule bypass) get
# a short, firm reason with no alternative. Nothing names the check, classifier,
# score or threshold that fired. Minors: photorealistic depictions are refused,
# clearly stylized non-sexual depictions are allowed.
#
# Run: python -m pytest backend/tests/test_image_safety_explanations.py -v

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.apps.images.tasks import generate_task
from backend.shared.providers.google.vision_safety import (
    VisionSafetyFindings,
    _derive_flags,
)
from backend.shared.providers.sightengine.client import (
    SightengineFindings,
    SightengineSafetyClient,
)
from backend.shared.python_utils.image_safety.explanations import (
    HARD_LIMIT_CATEGORIES,
    localized_rejection_payload,
)
from backend.shared.python_utils.image_safety.messages import CATEGORY_MAP
from backend.shared.python_utils.image_safety.pipeline import SafetyRejection

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCALES = REPO_ROOT / "frontend/packages/ui/src/i18n/locales"
POLICY = REPO_ROOT / "docs/architecture/image-safety-policy.md"
LANGUAGES = [
    "en", "de", "zh", "es", "fr", "pt", "ru", "ja", "ko", "it", "tr",
    "vi", "id", "pl", "nl", "ar", "hi", "th", "cs", "sv", "he",
]
POLICY_CATEGORIES = sorted(c for c in CATEGORY_MAP if c.startswith("S"))
MEDIA_GATE_CATEGORIES = [
    "G1_scam_or_fraud",
    "G2_spam_or_slop",
    "G3_public_figure_voice_or_persona",
    "G4_deceptive_synthetic_media",
]
# Words that would reveal how the decision was made.
SIGNAL_WORDS = (
    "sightengine", "gemini", "groq", "safeguard", "classifier", "score",
    "threshold", "minor_on_output", "hard_block", "vlm",
)
GERMAN_MINOR_REASON = (
    "Realistische Bilder von Minderjährigen werden nicht erstellt, und bei Fotos "
    "von Minderjährigen sind nur Änderungen an Hintergrund, Licht oder Farbe "
    "möglich, weil solche Bilder missbraucht werden könnten, zum Beispiel für "
    "gefälschte Profile, die sich als minderjährig ausgeben."
)


# contract-test: supporting surface=rest_api assertions=images-generate.safety.rejection-explained,images-generate.safety.hard-limits-firm
class TestReasonsAndAlternatives:
    @pytest.mark.parametrize("category", POLICY_CATEGORIES + MEDIA_GATE_CATEGORIES)
    @pytest.mark.parametrize("language", ["en", "de", "fr", "ja"])
    def test_every_category_has_a_localized_reason(self, category, language):
        payload = localized_rejection_payload(category, language)
        assert payload["reason"].strip()
        assert payload["do_not_retry"] is True
        if language != "en":
            assert payload["reason"] != localized_rejection_payload(category, "en")["reason"]
        text = " ".join(
            str(payload.get(k, "")) for k in ("reason", "alternative", "user_facing_message")
        ).lower()
        for word in SIGNAL_WORDS:
            assert word not in text, (category, language, word)

    @pytest.mark.parametrize("category", sorted(HARD_LIMIT_CATEGORIES))
    def test_hard_limits_are_firm_without_alternative(self, category):
        payload = localized_rejection_payload(category, "en")
        assert payload["hard_limit"] is True
        assert "alternative" not in payload
        assert payload["user_facing_message"] == payload["reason"]
        assert "hard safety limit" in payload["instructions_to_llm"]
        assert "suggest" in payload["instructions_to_llm"]
        assert "Do not retry" in payload["instructions_to_llm"]

    def test_hard_limits_are_exactly_csam_ncii_and_bypass(self):
        assert HARD_LIMIT_CATEGORIES == {"S1_csam", "S2_ncii", "S12_adversarial_bypass"}

    def test_photoreal_minor_reason_explains_misuse_and_offers_stylized(self):
        payload = localized_rejection_payload("S5_minor_restricted_edit", "en")
        assert "fake profiles" in payload["reason"]
        assert "3D" in payload["alternative"]
        assert payload["user_facing_message"] == f"{payload['reason']} {payload['alternative']}"
        assert payload["hard_limit"] is False
        assert localized_rejection_payload("S5_minor_restricted_edit", "de")["reason"] == GERMAN_MINOR_REASON

    def test_llm_explains_and_offers_alternative_instead_of_relaying(self):
        instructions = localized_rejection_payload("S6_public_figure_blocked", "en")["instructions_to_llm"]
        assert "Explain the reason" in instructions
        assert "alternative" in instructions
        assert "Do not retry" in instructions
        assert "images-generate" in instructions
        assert "verbatim" not in instructions
        assert "speculate" not in instructions

    def test_unknown_category_gets_generic_reason_and_alternative(self):
        payload = localized_rejection_payload("does_not_exist", "en")
        assert payload["category"] == "does_not_exist"
        assert payload["alternative"]
        assert payload["hard_limit"] is False

    def test_unknown_language_falls_back_to_english(self):
        assert (
            localized_rejection_payload("S3_sexual_other", "xx")["reason"]
            == localized_rejection_payload("S3_sexual_other", "en")["reason"]
        )

    def test_every_language_is_built_into_the_locales(self):
        for lang in LANGUAGES:
            data = json.loads((LOCALES / f"{lang}.json").read_text())
            assert data["image_safety"]["reason_minor"]["text"].strip(), lang
            assert data["image_safety"]["alternative_minor"]["text"].strip(), lang


def _rejection(category: str) -> SafetyRejection:
    return SafetyRejection(
        category=category,
        severity="severe",
        reason="sightengine:minor_on_output_any_suggestion",
        user_facing_message="English placeholder",
        tool_response=localized_rejection_payload(category, "en"),
        stage="input",
    )


# contract-test: supporting surface=rest_api assertions=images-generate.safety.rejection-explained
class TestRejectionHandlerLocalizes:
    @pytest.mark.asyncio
    async def test_reason_is_in_the_users_language_and_cached(self):
        strike_counter = MagicMock()
        strike_counter.record_strike = AsyncMock(
            return_value=SimpleNamespace(
                recorded=True, debounced=False, new_count=1, ban_triggered=False
            )
        )
        cache = MagicMock()
        cache.get_user_by_id = AsyncMock(return_value={"language": "de"})
        task = SimpleNamespace(_cache_service=cache, _directus_service=MagicMock())
        with patch.object(
            generate_task, "get_strike_counter", return_value=strike_counter
        ), patch.object(
            generate_task, "write_audit_entry", new=AsyncMock()
        ), patch.object(
            generate_task, "_cache_safety_rejection", new=AsyncMock()
        ) as cache_rejection:
            response = await generate_task._handle_safety_rejection(
                task,
                _rejection("S5_minor_restricted_edit"),
                user_id="user-1",
                prompt="portrait photo of a 14-year-old boy",
                assistant_response_id="resp-1",
                source_embed_id=None,
                output_embed_id=None,
                provider=None,
                model="test-model",
                log_prefix="[test]",
            )

        assert response["reason"] == GERMAN_MINOR_REASON
        assert response["alternative"].startswith("Eine klar stilisierte Version")
        assert "minor_on_output" not in json.dumps(response)
        assert cache_rejection.await_args.args[3] == response


# contract-test: supporting surface=rest_api assertions=images-generate.safety.minors-stylized-only
class TestMinorsPolicy:
    def test_policy_blocks_photoreal_and_allows_stylized_minors(self):
        policy = POLICY.read_text()
        assert "Any photorealistic or realistic-photo depiction of a minor" in policy
        assert "Clearly stylized, non-photorealistic depictions of a minor" in policy
        assert "3D cartoon-style portrait of a 12-year-old girl reading a book" in policy
        assert "is `S1_csam`, never `S5`, whatever the art style" in policy

    def test_policy_counts_one_strike_per_violation(self):
        policy = POLICY.read_text()
        assert "Every rejected request counts as exactly one strike" in policy
        assert "instant ban" not in policy
        assert "strike weight = 2" not in policy


def _output_scan(**scores) -> SightengineFindings:
    findings = SightengineFindings(minor_detected=True, **scores)
    SightengineSafetyClient._apply_thresholds(findings, stage="output")
    return findings


# contract-test: supporting surface=rest_api assertions=images-generate.safety.minors-stylized-only
class TestOutputMinorNoiseFloor:
    def test_stylized_child_with_noise_level_scores_passes(self):
        findings = _output_scan(suggestive=0.03, sexual_display=0.004, sexual_activity=0.002)
        assert not findings.hard_block

    @pytest.mark.parametrize(
        "scores",
        [
            {"suggestive": 0.15},
            {"sexual_display": 0.02},
            {"sexual_activity": 0.02},
            {"suggestive": 0.25},
            {"sexual_display": 0.06},
        ],
    )
    def test_minor_with_sexual_or_suggestive_signal_is_blocked(self, scores):
        findings = _output_scan(**scores)
        assert findings.hard_block
        assert findings.category_hint == "S1_csam"


# contract-test: supporting surface=rest_api assertions=images-generate.safety.minors-stylized-only
class TestVisionMinorFlags:
    def test_clothed_stylized_teen_is_not_hard_blocked(self):
        findings = VisionSafetyFindings(
            photorealistic=False,
            people=[{"approximate_age": "teen", "clothing_state": "clothed"}],
        )
        _derive_flags(findings)
        assert findings.minor_present
        assert not findings.hard_block

    def test_partially_clothed_minor_is_csam_in_any_style(self):
        findings = VisionSafetyFindings(
            photorealistic=False,
            people=[{"approximate_age": "child", "clothing_state": "partial"}],
        )
        _derive_flags(findings)
        assert findings.hard_block
        assert findings.category_hint == "S1_csam"
