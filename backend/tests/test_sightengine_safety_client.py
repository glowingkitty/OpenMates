# backend/tests/test_sightengine_safety_client.py
#
# Unit tests for the Sightengine response parser of the image safety pipeline
# (backend/shared/providers/sightengine/client.py), the fallback classifier
# when Jev fails. Docs: docs/architecture/image-safety-pipeline.md ("Jev first").
#
# The response bodies mirror the live API shapes: `gore` answers {"prob": p},
# `weapon` answers {"classes": {"firearm": p, "knife": p, ...}}, and
# `offensive` carries no weapon score.
#
# Run: python -m pytest backend/tests/test_sightengine_safety_client.py -v

import pytest

try:
    from backend.shared.providers.sightengine.client import (
        SAFETY_MODELS,
        SightengineSafetyClient,
    )
except ImportError as exc:  # pragma: no cover - backend dependencies missing locally
    pytest.skip(f"backend dependencies unavailable: {exc}", allow_module_level=True)


def _response(*, gore: float = 0.001, firearm: float = 0.001, knife: float = 0.001) -> dict:
    return {
        "status": "success",
        "nudity": {"sexual_activity": 0.001, "sexual_display": 0.001, "erotica": 0.001,
                   "sextoy": 0.001, "suggestive": 0.001},
        "offensive": {"prob": 0.001, "nazi": 0.001, "middle_finger": 0.001},
        "gore": {"prob": gore},
        "weapon": {
            "classes": {"firearm": firearm, "firearm_gesture": 0.001, "firearm_toy": 0.001, "knife": knife},
            "firearm_action": {"aiming_threat": 0.001, "not_worn": 0.99},
        },
        "type": {"ai_generated": 0.01},
    }


def _findings(data: dict, stage: str = "input"):
    findings = SightengineSafetyClient._parse_response(data)
    SightengineSafetyClient._apply_thresholds(findings, stage=stage)
    return findings


# Contract: the weapon model is part of every safety request, so weapon scores exist at all.
# contract-test: supporting surface=rest_api assertions=safety-strikes.screening-rejects
def test_weapon_model_is_requested():
    assert "weapon" in SAFETY_MODELS.split(",")
    assert "gore" in SAFETY_MODELS.split(",")


# Contract: a photo of a wound (gore.prob 0.99) is blocked as violent content, not recorded as 0.
@pytest.mark.parametrize("stage", ["input", "output"])
# contract-test: supporting surface=rest_api assertions=safety-strikes.screening-rejects
def test_gore_probability_blocks(stage):
    findings = _findings(_response(gore=0.99), stage)

    assert findings.gore == pytest.approx(0.99)
    assert findings.hard_block is True
    assert findings.category_hint == "S4_violent_recontextualization"
    assert findings.to_audit_dict()["scores"]["gore"] == 0.99


# Contract: a rifle or knife is read from weapon.classes and is a soft signal only, never a hard block.
@pytest.mark.parametrize("firearm,knife,expected", [(0.99, 0.001, 0.99), (0.001, 0.87, 0.87)])
# contract-test: supporting surface=rest_api assertions=safety-strikes.screening-rejects
def test_weapon_classes_are_read_without_hard_block(firearm, knife, expected):
    findings = _findings(_response(firearm=firearm, knife=knife))

    assert findings.weapon == pytest.approx(expected)
    assert findings.hard_block is False


# Contract: a clean image stays clean; low scores never block.
# contract-test: supporting surface=rest_api assertions=safety-strikes.screening-rejects
def test_clean_image_passes():
    findings = _findings(_response())

    assert findings.hard_block is False
    assert findings.gore == pytest.approx(0.001)
    assert findings.weapon == pytest.approx(0.001)
