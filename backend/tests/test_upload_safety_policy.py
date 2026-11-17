# backend/tests/test_upload_safety_policy.py
#
# Branch coverage for the upload image safety policy with synthetic score dicts.
# The second opinion is stubbed at the module boundary (the SecondOpinion callable).
#
# Execution:
#   python3 -m pytest backend/tests/test_upload_safety_policy.py -q

import pytest

from backend.upload.services.upload_safety_policy import (
    JevImageOpinion,
    UploadSafetyScores,
    resolve_upload_safety,
    upload_safety_decision,
)


def _stub(opinion):
    calls = []

    async def second_opinion():
        calls.append(1)
        return opinion

    second_opinion.calls = calls
    return second_opinion


# contract-test: direct surface=rest_api assertions=safety-strikes.upload-agreed-lines
def test_weapons_are_allowed():
    assert upload_safety_decision(UploadSafetyScores(weapon=0.99)).kind == "allow"
    assert not upload_safety_decision(UploadSafetyScores(weapon=0.99)).borderline


# contract-test: direct surface=rest_api assertions=safety-strikes.upload-agreed-lines
def test_war_news_image_allowed():
    decision = upload_safety_decision(UploadSafetyScores(gore=0.1, weapon=0.9))
    assert decision.kind == "allow" and not decision.borderline


# contract-test: direct surface=rest_api assertions=safety-strikes.upload-agreed-lines
def test_medical_art_nudity_and_suggestive_allowed():
    scores = UploadSafetyScores(sexual_display=0.1, erotica=0.1, suggestive=0.95)
    decision = upload_safety_decision(scores)
    assert decision.kind == "allow" and not decision.borderline


# contract-test: direct surface=rest_api assertions=safety-strikes.upload-agreed-lines
def test_explicit_refused_without_strike():
    decision = upload_safety_decision(UploadSafetyScores(sexual_activity=0.95))
    assert decision.kind == "refuse_no_strike"
    assert decision.reason.startswith("explicit=")


# contract-test: direct surface=rest_api assertions=safety-strikes.upload-agreed-lines
def test_extreme_gore_refused_without_strike():
    decision = upload_safety_decision(UploadSafetyScores(gore=0.97))
    assert decision.kind == "refuse_no_strike"
    assert decision.reason.startswith("gore=")


# contract-test: direct surface=rest_api assertions=safety-strikes.upload-agreed-lines
def test_minor_sexual_high_confidence_is_strike():
    decision = upload_safety_decision(UploadSafetyScores(sexual_display=0.7, minor=0.9))
    assert decision.kind == "refuse_strike"
    assert decision.reason.startswith("minor_sexual=")


# contract-test: direct surface=rest_api assertions=safety-strikes.upload-agreed-lines
def test_minor_with_only_explicit_adult_scores_no_strike():
    decision = upload_safety_decision(UploadSafetyScores(sexual_activity=0.95, minor=0.1))
    assert decision.kind == "refuse_no_strike"


@pytest.mark.parametrize(
    "scores",
    [
        UploadSafetyScores(sexual_activity=0.6),
        UploadSafetyScores(gore=0.78),
        UploadSafetyScores(sexual_display=0.4, minor=0.6),
        UploadSafetyScores(sexual_display=0.5, minor=0.9),
    ],
)
# contract-test: direct surface=rest_api assertions=safety-strikes.upload-agreed-lines
def test_borderline_flagged(scores):
    assert upload_safety_decision(scores).borderline


# contract-test: direct surface=rest_api assertions=safety-strikes.upload-agreed-lines
@pytest.mark.anyio
async def test_borderline_goes_to_jev_and_jev_allows():
    stub = _stub(JevImageOpinion(nudity=0.1, minor=0.0, gore=0.0))
    decision = await resolve_upload_safety(UploadSafetyScores(sexual_activity=0.6), stub)
    assert stub.calls and decision.kind == "allow" and decision.borderline


# contract-test: direct surface=rest_api assertions=safety-strikes.upload-agreed-lines
@pytest.mark.anyio
async def test_borderline_jev_refuses_explicit_without_strike():
    stub = _stub(JevImageOpinion(nudity=0.9, minor=0.0, gore=0.0))
    decision = await resolve_upload_safety(UploadSafetyScores(sexual_activity=0.6), stub)
    assert decision.kind == "refuse_no_strike" and decision.category == "explicit"


# contract-test: direct surface=rest_api assertions=safety-strikes.upload-agreed-lines
@pytest.mark.anyio
async def test_borderline_jev_confirms_minor_sexual_strike():
    stub = _stub(JevImageOpinion(nudity=0.9, minor=0.9, gore=0.0))
    decision = await resolve_upload_safety(UploadSafetyScores(sexual_display=0.4, minor=0.6), stub)
    assert decision.kind == "refuse_strike"


# contract-test: direct surface=rest_api assertions=safety-strikes.upload-agreed-lines
@pytest.mark.anyio
async def test_borderline_with_jev_down_refuses_without_strike():
    decision = await resolve_upload_safety(UploadSafetyScores(gore=0.78), _stub(None))
    assert decision.kind == "refuse_no_strike" and decision.reason.startswith("jev_unsure=")


# contract-test: direct surface=rest_api assertions=safety-strikes.upload-agreed-lines
@pytest.mark.anyio
async def test_clear_decision_does_not_call_jev():
    stub = _stub(JevImageOpinion())
    await resolve_upload_safety(UploadSafetyScores(sexual_activity=0.95), stub)
    await resolve_upload_safety(UploadSafetyScores(), stub)
    assert not stub.calls


# contract-test: direct surface=rest_api assertions=safety-strikes.upload-agreed-lines
@pytest.mark.anyio
async def test_sightengine_down_jev_strict_allows_only_clearly_harmless():
    safe = await resolve_upload_safety(None, _stub(JevImageOpinion(nudity=0.01, minor=0.0, gore=0.02)))
    assert safe.kind == "allow"
    unsure = await resolve_upload_safety(None, _stub(JevImageOpinion(nudity=0.1)))
    assert unsure.kind == "refuse_no_strike" and unsure.reason.startswith("jev_unsure=")


# contract-test: direct surface=rest_api assertions=safety-strikes.upload-agreed-lines
@pytest.mark.anyio
async def test_fallback_never_strikes_even_for_minor_sexual():
    decision = await resolve_upload_safety(None, _stub(JevImageOpinion(nudity=0.99, minor=0.99)))
    assert decision.kind == "refuse_no_strike"


# contract-test: direct surface=rest_api assertions=safety-strikes.upload-agreed-lines
@pytest.mark.anyio
async def test_both_down_is_unavailable_without_strike():
    decision = await resolve_upload_safety(None, _stub(None))
    assert decision.kind == "refuse_no_strike" and decision.reason == "safety_service_unavailable"
    assert (await resolve_upload_safety(None, None)).reason == "safety_service_unavailable"
