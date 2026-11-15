"""Gemini cached-token logging, cache_read billing and cache-stable prompt order."""
import json
import logging
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from backend.apps.ai.llm_providers import google_client
from backend.apps.ai.processing.model_usage_tracker import build_model_usage_breakdown
from backend.shared.python_utils.billing_utils import snapshot_model_tariff
from backend.shared.python_utils.model_pricing import resolve_model_tariff

ROOT = Path(__file__).resolve().parents[2]


def _model():
    data = yaml.safe_load((ROOT / "backend/providers/google.yml").read_text())
    return next(m for m in data["models"] if m["id"] == "gemini-3.8-flash")


# contract-test: supporting surface=rest_api assertions=billing.models.verified-host-prices
def test_usage_log_includes_cached_content_token_count(caplog):
    usage = SimpleNamespace(
        prompt_token_count=10000, candidates_token_count=50, total_token_count=10050,
        thoughts_token_count=7, cached_content_token_count=8192,
        system_prompt_tokens=None, user_input_tokens=300,
    )
    timing = SimpleNamespace(task_id="t1", host="google_ai_studio", model_id="gemini-3.8-flash")
    with caplog.at_level(logging.INFO):
        google_client._log_google_stream_usage(timing, usage)
    line = next(r.getMessage() for r in caplog.records if "Google stream usage" in r.getMessage())
    counters = json.loads(line.split("counters=", 1)[1])
    assert counters["cached_content_token_count"] == 8192
    assert all(v is None or isinstance(v, int) for v in counters.values())


# contract-test: supporting surface=rest_api assertions=billing.models.verified-host-prices
@pytest.mark.parametrize("host", ["google_ai_studio", "google"])
def test_cached_gemini_tokens_bill_at_cache_read_rate_not_input_rate(host):
    model = _model()
    usage = google_client._google_usage_metadata(
        SimpleNamespace(prompt_token_count=10000, candidates_token_count=100, total_token_count=10100,
                        cached_content_token_count=8000, thoughts_token_count=None),
        {}, host,
    )
    assert usage.cache_read_input_tokens == 8000
    tariff = resolve_model_tariff(model, on_date=date(2026, 11, 15))
    bucket = {
        "model_id": "google/gemini-3.8-flash", "inference_host": host,
        "usage_source": "provider_reported", "tariff_snapshot": snapshot_model_tariff(tariff),
        "input_tokens": usage.prompt_token_count,
        "uncached_input_tokens": usage.prompt_token_count - usage.cache_read_input_tokens,
        "cache_read_input_tokens": usage.cache_read_input_tokens,
        "output_tokens": usage.candidates_token_count,
    }
    entry = build_model_usage_breakdown([bucket], lambda *_a: tariff)["entries"][0]
    rates = tariff["pricing"]["tokens"]
    credits = entry["category_credits"]
    assert float(credits["cache_read"]) == pytest.approx(8000 / rates["cache_read"]["per_credit_unit"])
    assert float(credits["input"]) == pytest.approx(2000 / rates["input"]["per_credit_unit"])


# contract-test: supporting surface=rest_api assertions=billing.models.verified-host-prices
def test_system_prompt_clock_is_minute_granular_and_last():
    source = (ROOT / "backend/apps/ai/processing/main_processor.py").read_text()
    assert '"%Y-%m-%d %H:%M:%S' not in source.split("clock_instruction", 1)[1][:1500]
    assert "prompt_parts.append(clock_instruction)" not in source
    tail = source.index("prompt_parts.extend(volatile_prompt_tail)")
    join = source.index('full_system_prompt = "\\n\\n".join(filter(None, prompt_parts))', tail)
    assert join - tail < 120
    # No catalog/mate/app block is appended after the volatile tail at first assembly.
    assert re.search(r"volatile_prompt_tail: list\[str\] = \[clock_instruction\]", source)
