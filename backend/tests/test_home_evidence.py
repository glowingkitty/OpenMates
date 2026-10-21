"""Housing evidence contracts: unknowns, photo budgets, and transient failures."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.home import evidence
from backend.shared.providers.typesafe.models import ChoiceAnswer


def response(values, confidence=.95):
    return SimpleNamespace(answers={key: ChoiceAnswer(type="choice", choice=value,
        probabilities={value: 1.0}, confidence=confidence) for key, value in values.items()})


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=home-search.relevance.natural-language,home-search.filters.explicit-and-unknown
async def test_preferences_preserve_prefer_and_explicit_lists(monkeypatch):
    client = AsyncMock()
    monkeypatch.setattr(evidence, "JevDecisionClient", lambda **kwargs: client)
    criteria = "Balkon erforderlich; bevorzugt mit Garten"
    result = await evidence.resolve_home_preferences({"relevance_criteria": criteria}, secrets_manager=None)
    assert result["required_amenities"] == ["balcony"]
    assert result["preferred_amenities"] == ["garden"]
    assert result["relevance_criteria"] == criteria
    optional = await evidence.resolve_home_preferences({"relevance_criteria": "Balkon wäre schön"}, secrets_manager=None)
    assert optional["preferred_amenities"] == ["balcony"]
    explicit = await evidence.resolve_home_preferences({"required_amenities": ["terrace"], "relevance_criteria": criteria}, secrets_manager=object())
    assert explicit["required_amenities"] == ["terrace"]
    client.evaluate.assert_not_called()


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=home-search.relevance.natural-language,home-search.filters.explicit-and-unknown
async def test_preference_jev_and_low_confidence_fallback(monkeypatch):
    client = AsyncMock()
    client.evaluate.return_value = response({"balcony": "preferred"})
    monkeypatch.setattr(evidence, "JevDecisionClient", lambda **kwargs: client)
    result = await evidence.resolve_home_preferences({"relevance_criteria": "ideally a balcony"}, secrets_manager=object())
    assert result["preferred_amenities"] == ["balcony"]
    assert not result["required_amenities"]
    client.evaluate.return_value = response({"balcony": "required"}, confidence=.6)
    result = await evidence.resolve_home_preferences({"relevance_criteria": "prefer a balcony"}, secrets_manager=object())
    assert result["preferred_amenities"] == ["balcony"]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=home-search.vision.evidence-and-conflicts,home-search.enrichment.bounded-and-reusable
async def test_neutral_search_skips_all_inference(monkeypatch):
    factory = AsyncMock()
    monkeypatch.setattr(evidence, "JevDecisionClient", factory)
    listings = [{"description": "Apartment in Berlin"}]
    assert await evidence.assess_home_evidence(listings, request={}, secrets_manager=object()) == []
    factory.assert_not_called()
    assert "match_evidence" not in listings[0]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=home-search.vision.evidence-and-conflicts
async def test_description_confirms_without_photos_and_structured_fact_survives_outage(monkeypatch):
    client = AsyncMock()
    client.evaluate.return_value = response({"balcony": "present"})
    monkeypatch.setattr(evidence, "JevDecisionClient", lambda **kwargs: client)
    listing = {"description": "Die Wohnung verfügt über einen Balkon"}
    await evidence.assess_home_evidence([listing], request={"required_amenities": ["balcony"]}, secrets_manager=object())
    item = listing["match_evidence"]["amenities"]["balcony"]
    assert item["status"] == "confirmed"
    assert item["text_status"] == "present"
    assert item["visual_status"] == "unavailable"
    assert listing["visual_assessment"]["photo_count"] == 0
    explicit = {"amenities": {"balcony": True}}
    await evidence.assess_home_evidence([explicit], request={"required_amenities": ["balcony"]}, secrets_manager=None)
    assert explicit["match_evidence"]["status"] == "confirmed"


@pytest.mark.asyncio
@pytest.mark.parametrize("text,seen,expected", [("absent", "visible", "conflicting"), ("unknown", "visible", "possible"), ("unknown", "not_visible", "unknown")])
# contract-test: supporting surface=rest_api assertions=home-search.vision.evidence-and-conflicts
async def test_photo_visibility_never_proves_apartment_ownership(monkeypatch, text, seen, expected):
    client = AsyncMock()
    client.evaluate.return_value = response({"balcony": text})
    client.evaluate_with_images.return_value = response({"balcony:0": seen})
    monkeypatch.setattr(evidence, "JevDecisionClient", lambda **kwargs: client)
    download = AsyncMock(return_value=b"prepared jpeg")
    monkeypatch.setattr(evidence, "download_public_image", download)
    gallery = ["https://example.org/building.jpg"]
    listing = {"description": "Kein Balkon" if text == "absent" else "Wohnung", "image_urls": gallery}
    await evidence.assess_home_evidence([listing], request={"required_amenities": ["balcony"]}, secrets_manager=object())
    assert listing["image_urls"] is gallery
    assert listing["match_evidence"]["amenities"]["balcony"]["status"] == expected
    assert listing["visual_assessment"]["photo_count"] == 1
    assert listing["visual_assessment"]["features"]["balcony"]["photo_indices"] == ([0] if seen == "visible" else [])


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=home-search.vision.evidence-and-conflicts
async def test_failure_does_not_fake_visual_confirmation(monkeypatch):
    client = AsyncMock()
    client.evaluate.return_value = response({"balcony": "unknown"})
    client.evaluate_with_images.side_effect = RuntimeError("unavailable")
    monkeypatch.setattr(evidence, "JevDecisionClient", lambda **kwargs: client)
    monkeypatch.setattr(evidence, "download_public_image", AsyncMock(return_value=b"photo"))
    listing = {"image_url": "https://example.org/photo.jpg"}
    warnings = await evidence.assess_home_evidence([listing], request={"required_amenities": ["balcony"]}, secrets_manager=object())
    assert warnings
    assert listing["visual_assessment"]["status"] == "unavailable"
    assert listing["match_evidence"]["amenities"]["balcony"]["status"] == "unknown"


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=home-search.vision.evidence-and-conflicts,home-search.enrichment.bounded-and-reusable,home-search.images.transient-analysis
async def test_bounded_spaced_photos_all_candidates_and_no_file_writes(monkeypatch):
    client = AsyncMock()
    client.evaluate.return_value = response({"balcony": "unknown"})
    async def evaluate_images(**kwargs):
        assert len(kwargs["images"]) <= 18
        return response({key: "not_visible" for key in kwargs["questions"]})
    client.evaluate_with_images.side_effect = evaluate_images
    monkeypatch.setattr(evidence, "JevDecisionClient", lambda **kwargs: client)
    download = AsyncMock(return_value=b"prepared image")
    monkeypatch.setattr(evidence, "download_public_image", download)
    def forbid(*args, **kwargs):
        raise AssertionError("Photo assessment must not write files")
    monkeypatch.setattr("builtins.open", forbid)
    listings = [{"image_urls": [f"https://example.org/{listing}/{photo}.jpg" for photo in range(18)]} for listing in range(45)]
    await evidence.assess_home_evidence(listings, request={"required_amenities": ["balcony"]}, secrets_manager=object())
    assert download.await_count == 120
    assert client.evaluate.await_count == 40
    assert client.evaluate_with_images.await_count == 40
    assert all(len(item["image_urls"]) == 18 for item in listings)
    photos = [call.args[0] for call in download.await_args_list]
    assert "https://example.org/0/0.jpg" in photos
    assert "https://example.org/0/17.jpg" in photos
    assert listings[0]["visual_assessment"]["status"] == "partial"


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=home-search.vision.evidence-and-conflicts,home-search.enrichment.bounded-and-reusable,home-search.images.transient-analysis
async def test_global_timeout_and_cancellation_join_download_tasks(monkeypatch):
    client = AsyncMock()
    client.evaluate.return_value = response({"balcony": "present"})
    monkeypatch.setattr(evidence, "JevDecisionClient", lambda **kwargs: client)
    running = set()
    async def download(url):
        running.add(url)
        try:
            await asyncio.sleep(100)
        finally:
            running.discard(url)
    monkeypatch.setattr(evidence, "download_public_image", download)
    monkeypatch.setattr(evidence, "ASSESSMENT_SECONDS", .02)
    listing = {"image_url": "https://example.org/photo.jpg"}
    warnings = await evidence.assess_home_evidence([listing], request={"required_amenities": ["balcony"]}, secrets_manager=object())
    assert not running
    assert warnings
    assert listing["match_evidence"]["status"] == "confirmed"
    assert listing["visual_assessment"]["status"] == "unavailable"
    task = asyncio.create_task(evidence.assess_home_evidence([listing], request={"required_amenities": ["balcony"]}, secrets_manager=object()))
    await asyncio.sleep(.005)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not running


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=home-search.vision.evidence-and-conflicts,home-search.images.transient-analysis
async def test_disabled_visual_assessment_keeps_text_and_skips_images(monkeypatch):
    client = AsyncMock()
    client.evaluate.return_value = response({"balcony": "present"})
    monkeypatch.setattr(evidence, "JevDecisionClient", lambda **kwargs: client)
    download = AsyncMock()
    monkeypatch.setattr(evidence, "download_public_image", download)
    listing = {"description": "With balcony", "image_urls": ["https://example.org/1.jpg"]}
    await evidence.assess_home_evidence([listing], request={"required_amenities": ["balcony"], "visual_analysis": False}, secrets_manager=object())
    client.evaluate.assert_awaited_once()
    download.assert_not_called()
    client.evaluate_with_images.assert_not_called()
    assert listing["match_evidence"]["status"] == "confirmed"
    assert listing["visual_assessment"]["status"] == "unavailable"
    assert listing["visual_assessment"]["photo_count"] == 0
    assert listing["match_evidence"]["amenities"]["balcony"]["visual_status"] == "unavailable"


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=home-search.vision.evidence-and-conflicts
async def test_provider_conflicts_override_text_and_minimize_state(monkeypatch):
    client = AsyncMock()
    client.evaluate.return_value = response({"balcony": "present"})
    monkeypatch.setattr(evidence, "JevDecisionClient", lambda **kwargs: client)
    listing = {"amenities": {"balcony": True}, "amenity_conflicts": {"balcony": [True, False], "garden": "private unused data"}}
    await evidence.assess_home_evidence([listing], request={"required_amenities": ["balcony"]}, secrets_manager=object())
    item = listing["match_evidence"]["amenities"]["balcony"]
    assert item["status"] == "conflicting"
    assert item["source_conflict"] is True
    assert client.evaluate.await_args.kwargs["state"]["untrusted_listing"]["amenity_conflicts"] == {"balcony": True}
    await evidence.assess_home_evidence([listing], request={"required_amenities": ["balcony"]}, secrets_manager=None)
    assert listing["match_evidence"]["status"] == "conflicting"


@pytest.mark.asyncio
@pytest.mark.parametrize("advertised,text,expected", [(False, "absent", "confirmed"), (None, "absent", "confirmed"), (True, "present", "conflicting"), (None, "unknown", "unconfirmed")])
# contract-test: supporting surface=rest_api assertions=home-search.vision.evidence-and-conflicts
async def test_exclusions_require_supported_absence(monkeypatch, advertised, text, expected):
    client = AsyncMock()
    client.evaluate.return_value = response({"balcony": text})
    monkeypatch.setattr(evidence, "JevDecisionClient", lambda **kwargs: client)
    listing = {"amenities": {"balcony": advertised}}
    await evidence.assess_home_evidence([listing], request={"excluded_amenities": ["balcony"], "visual_analysis": False}, secrets_manager=object())
    assert listing["match_evidence"]["status"] == expected
    item = listing["match_evidence"]["amenities"]["balcony"]
    assert item["expectation"] == "absent"
    assert item["advertised"] is advertised
    assert item["text_status"] == text
