import pytest
import yaml
from pathlib import Path

from backend.apps.videos.tasks.generate_billing import (
    OMNI_PRICE_USD_PER_SECOND,
    omni_clip_credits,
    omni_clip_pricing,
)
from backend.shared.python_utils.billing_utils import calculate_total_credits, has_credit_headroom

ROOT = Path(__file__).resolve().parents[2]


# contract-test: supporting surface=rest_api assertions=videos-generate.billing.metered
def test_omni_720p_charges_per_generated_second():
    price, pricing_config = omni_clip_pricing("720p")
    assert price == 0.07
    assert pricing_config["per_second"]["unit_name"] == "video_second"
    assert calculate_total_credits(pricing_config=pricing_config, duration_seconds=8) == 840
    assert omni_clip_credits("720p", 4.04) == 424


# contract-test: supporting surface=rest_api assertions=videos-generate.billing.metered
def test_omni_uses_resolution_specific_second_rate():
    assert omni_clip_credits("360p", 8) == 280
    assert omni_clip_credits("1080p", 8) == 1280
    assert omni_clip_credits("4k", 8) == 2520


# contract-test: supporting surface=gui.web assertions=videos-generate.billing.metered
def test_unknown_omni_resolution_has_no_price():
    with pytest.raises(ValueError, match="no Gemini Omni price"):
        omni_clip_pricing("480p")


# contract-test: supporting surface=gui.web assertions=videos-generate.billing.metered
def test_omni_prices_match_the_provider_catalog():
    catalog = yaml.safe_load((ROOT / "backend/providers/google.yml").read_text())
    omni = next(model for model in catalog["models"] if model["id"] == "gemini-omni-1.2-flash")
    costs = omni["costs"]["output_per_second"]
    assert OMNI_PRICE_USD_PER_SECOND == {"360p": costs["price_360p"], "720p": costs["price"],
                                         "1080p": costs["price_1080p"], "4k": costs["price_4k"]}
    assert omni["pricing"]["per_second"] == round(costs["price"] * 1.5 / 0.001)
    app = yaml.safe_load((ROOT / "backend/apps/videos/app.yml").read_text())
    skill = next(item for item in app["skills"] if item["id"] == "generate")
    assert skill["full_model_reference"] == "google/gemini-omni-1.2-flash"
    assert skill["pricing"]["per_second"] == omni["pricing"]["per_second"]


# contract-test: supporting surface=gui.web assertions=videos-generate.billing.metered
def test_omni_credit_headroom_respects_overdraft_limit():
    assert has_credit_headroom(current_credits=840, estimated_credits=840)
    assert not has_credit_headroom(current_credits=-1000, estimated_credits=840)

# contract-test: supporting surface=gui.web assertions=videos-generate.billing.metered
def test_h3_promotion_expiry_and_fractional_output_duration():
    from datetime import datetime, timezone
    from backend.apps.videos.tasks.generate_task import _get_h3_duration_pricing
    promo_price, promo = _get_h3_duration_pricing(datetime(2026, 10, 31, 23, 59, tzinfo=timezone.utc))
    standard_price, standard = _get_h3_duration_pricing(datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert promo_price == 0.01625
    assert standard_price == 0.025
    assert calculate_total_credits(pricing_config=promo, duration_seconds=5.4) == 135
    assert calculate_total_credits(pricing_config=standard, duration_seconds=5.4) == 216
