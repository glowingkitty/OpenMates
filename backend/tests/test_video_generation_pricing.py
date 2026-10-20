# backend/tests/test_video_generation_pricing.py
#
# Verifies OpenMates billing math for generated video. Google bills Veo by
# generated second, not by request, so credit charging must scale with output
# duration and model/resolution-specific official prices.

from backend.apps.videos.tasks.generate_task import (
    _estimate_veo_generation_credits,
    _get_veo_duration_pricing,
)
from backend.shared.python_utils.billing_utils import calculate_total_credits, has_credit_headroom


# contract-test: supporting surface=gui.web assertions=billing.models.verified-host-prices
def test_veo_standard_charges_per_generated_second():
    _, pricing_config = _get_veo_duration_pricing("veo-3.1-generate-preview", "720p")

    assert pricing_config["per_second"]["unit_name"] == "video_second"
    assert calculate_total_credits(pricing_config=pricing_config, duration_seconds=8) == 4800


# contract-test: supporting surface=gui.web assertions=billing.models.verified-host-prices
def test_veo_fast_1080p_uses_resolution_specific_second_rate():
    _, pricing_config = _get_veo_duration_pricing("veo-3.1-fast-generate-preview", "1080p")

    assert calculate_total_credits(pricing_config=pricing_config, duration_seconds=8) == 1440


# contract-test: supporting surface=gui.web assertions=billing.models.verified-host-prices
def test_unknown_veo_pricing_falls_back_to_standard_720p_rate():
    price_usd_per_second, pricing_config = _get_veo_duration_pricing("unknown", "unknown")

    assert price_usd_per_second == 0.40
    assert calculate_total_credits(pricing_config=pricing_config, duration_seconds=4) == 2400


# contract-test: supporting surface=gui.web assertions=billing.models.active-price-consistency
def test_veo_credit_estimate_uses_per_second_pricing():
    assert _estimate_veo_generation_credits("veo-3.1-generate-preview", "720p", 8) == 4800


# contract-test: supporting surface=gui.web assertions=billing.credits.idempotent-charge
def test_veo_credit_headroom_respects_overdraft_limit():
    assert has_credit_headroom(current_credits=5300, estimated_credits=4800)
    assert has_credit_headroom(current_credits=4300, estimated_credits=4800)
    assert not has_credit_headroom(current_credits=4299, estimated_credits=4800)


# contract-test: supporting surface=gui.web assertions=video-call.video.fast-generation-default
def test_h3_promotion_expiry_and_fractional_output_duration():
    from datetime import datetime, timezone
    from backend.apps.videos.tasks.generate_task import _get_h3_duration_pricing
    promo_price, promo = _get_h3_duration_pricing(datetime(2026, 10, 31, 23, 59, tzinfo=timezone.utc))
    standard_price, standard = _get_h3_duration_pricing(datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert promo_price == 0.01625
    assert standard_price == 0.025
    assert calculate_total_credits(pricing_config=promo, duration_seconds=5.4) == 131
    assert calculate_total_credits(pricing_config=standard, duration_seconds=5.4) == 202
