"""GLM's logical catalog identity, Mistral transport, and reported cache billing."""

# contract-test-file: infrastructure

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import yaml

from backend.apps.ai.llm_providers import mistral_client
from backend.apps.ai.processing.model_usage_tracker import build_model_usage_breakdown
from backend.apps.ai.utils import llm_utils
from backend.shared.python_schemas.llm_usage import normalize_provider_usage
from backend.shared.python_utils.billing_utils import calculate_cache_aware_supplier_cost, snapshot_model_tariff


def _catalog():
    return yaml.safe_load((Path(__file__).parents[1] / 'providers/zai.yml').read_text())


def _model():
    return next(model for model in _catalog()['models'] if model['id'] == 'zai-glm-5.3')


def _use_catalog(monkeypatch):
    monkeypatch.setattr(llm_utils.config_manager, 'get_provider_config', lambda provider: _catalog() if provider == 'zai' else None)
    monkeypatch.setattr(llm_utils.config_manager, 'get_model_pricing', lambda provider, model: _model() if (provider, model) == ('zai', 'zai-glm-5.3') else None)


def test_glm_default_host_uses_mistral_api_id_and_verified_rates(monkeypatch):
    _use_catalog(monkeypatch)
    assert llm_utils.resolve_default_server_from_provider_config('zai/zai-glm-5.3') == ('mistral', 'mistral/zai-glm-5-3')
    assert llm_utils.resolve_fallback_servers_from_provider_config('zai/zai-glm-5.3') == []
    model = _model()
    assert model['capability_level'] == 'high'
    assert model['input_types'] == ['text']
    assert model['reasoning_effort'] == 'high'
    assert model['cache_pricing']['eligible_hosts'] == ['mistral']
    snapshot_model_tariff(model)
    for category, cost_key, rate in [
        ('input', 'input_per_million_token', 1.4),
        ('cache_read', 'cached_input_per_million_token', 0.14),
        ('output', 'output_per_million_token', 4.4),
    ]:
        assert model['costs'][cost_key]['price'] == rate
        customer = 1000 / model['pricing']['tokens'][category]['per_credit_unit']
        assert 3 <= customer / rate < 3.05


@pytest.mark.parametrize('effort', ['low', 'high', 'max'])
def test_glm_reasoning_uses_logical_catalog_and_supported_values(monkeypatch, effort):
    lookups = []

    def lookup(provider, model):
        lookups.append((provider, model))
        return {'reasoning_effort': effort}

    monkeypatch.setattr(mistral_client.config_manager, 'get_model_pricing', lookup)
    assert mistral_client._get_mistral_reasoning_effort('zai-glm-5-3', 'zai/zai-glm-5.3') == effort
    assert lookups == [('zai', 'zai-glm-5.3')]


def test_glm_rejects_unsupported_none_reasoning(monkeypatch):
    monkeypatch.setattr(mistral_client.config_manager, 'get_model_pricing', lambda *_: {'reasoning_effort': 'none'})
    with pytest.raises(ValueError, match='Invalid Mistral reasoning_effort'):
        mistral_client._get_mistral_reasoning_effort('zai-glm-5-3', 'zai/zai-glm-5.3')


def test_preprocessing_mistral_fallback_uses_its_own_catalog_not_primary(monkeypatch):
    calls = []

    async def primary(**kwargs):
        return mistral_client.UnifiedMistralResponse(
            task_id='test', model_id=kwargs['model_id'], success=False, error_message='Request timeout',
        )

    async def fallback(**kwargs):
        calls.append(kwargs['catalog_model_id'])
        assert mistral_client._get_mistral_reasoning_effort(kwargs['model_id'], kwargs['catalog_model_id']) == 'none'
        return mistral_client.UnifiedMistralResponse(
            task_id='test', model_id=kwargs['model_id'], success=True,
            tool_calls_made=[mistral_client.ParsedMistralToolCall(
                tool_call_id='test-call', function_name='classify',
                function_arguments_raw='{"score":1}', function_arguments_parsed={'score': 1},
            )],
        )

    class CacheWithoutClient:
        @property
        async def client(self):
            return None

    monkeypatch.setattr(llm_utils, 'CacheService', CacheWithoutClient)
    monkeypatch.setattr(llm_utils, 'resolve_default_server_from_provider_config', lambda _: (None, None))
    monkeypatch.setattr(llm_utils, '_get_provider_client', lambda provider: fallback if provider == 'mistral' else primary)
    monkeypatch.setattr(mistral_client.config_manager, 'get_model_pricing', lambda provider, _: {'reasoning_effort': 'none' if provider == 'mistral' else 'medium'})
    result = asyncio.run(llm_utils.call_preprocessing_llm(
        task_id='test', model_id='google/primary',
        message_history=[{'role': 'user', 'content': 'Classify this.'}],
        tool_definition={'type': 'function', 'function': {'name': 'classify', 'parameters': {'type': 'object', 'properties': {}}}},
        fallback_models=['mistral/mistral-small-latest'],
    ))
    assert result.arguments == {'score': 1}
    assert calls == ['mistral/mistral-small-latest']


@pytest.mark.parametrize('cached_tokens', [512, 0, None])
def test_main_stream_forwards_glm_reasoning_and_cache_key_and_preserves_billing_identity(monkeypatch, cached_tokens):
    _use_catalog(monkeypatch)
    payloads = []

    def handle(request):
        payloads.append(json.loads(request.content))
        usage = {'prompt_tokens': 1000, 'completion_tokens': 32, 'total_tokens': 1032}
        if cached_tokens is not None:
            usage['prompt_tokens_details'] = {'cached_tokens': cached_tokens}
        events = [
            {'id': 'glm-test-response', 'choices': [{'delta': {'content': [{'type': 'text', 'text': '391'}]}, 'finish_reason': 'stop'}]},
            {'choices': [], 'usage': usage},
        ]
        return httpx.Response(200, text=''.join(f'data: {json.dumps(event)}\n\n' for event in events) + 'data: [DONE]\n\n')

    original_client = httpx.AsyncClient
    monkeypatch.setattr(mistral_client, 'MISTRAL_API_KEY', 'test-placeholder')
    monkeypatch.setattr(mistral_client.httpx, 'AsyncClient', lambda **kwargs: original_client(**kwargs, transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(llm_utils, '_get_provider_client', lambda provider: mistral_client.invoke_mistral_chat_completions if provider == 'mistral' else None)

    async def run():
        return [chunk async for chunk in llm_utils.call_main_llm_stream(
            task_id='glm-test', model_id='zai/zai-glm-5.3', system_prompt='Answer briefly.',
            message_history=[{'role': 'user', 'content': 'What is 17 times 23?'}],
            temperature=0.2, prompt_cache_key='opaque-test-chat', customer_cache_pricing_enabled=True,
        )]

    chunks = asyncio.run(run())
    assert '391' in chunks
    assert payloads[0]['model'] == 'zai-glm-5-3'
    assert payloads[0]['reasoning_effort'] == 'high'
    assert payloads[0]['prompt_cache_key'] == 'opaque-test-chat'
    usage = next(chunk for chunk in chunks if isinstance(chunk, mistral_client.MistralUsage))
    normalized = usage._normalized_llm_usage.to_bucket()
    assert normalized['model_id'] == 'zai/zai-glm-5.3'
    assert normalized['inference_host'] == 'mistral'
    assert normalized['provider_kind'] == 'mistral'
    assert normalized['cache_read_input_tokens'] == cached_tokens
    assert normalized['uncached_input_tokens'] == 1000 - (cached_tokens or 0)
    entry = build_model_usage_breakdown([normalized], lambda *_: _model())['entries'][0]
    assert entry['billing_mode'] == ('ordinary_input' if cached_tokens is None else 'cache_aware')
    assert float(entry['category_credits']['cache_read']) == pytest.approx((cached_tokens or 0) / 2380)
    assert float(entry['category_credits']['cache_write']) == 0


def test_cache_discount_is_not_admitted_for_another_host():
    model = _model()
    usage = mistral_client.MistralUsage(prompt_tokens=1000, completion_tokens=32, total_tokens=1032, cache_read_input_tokens=512)
    bucket = normalize_provider_usage(usage, model_id='zai/zai-glm-5.3', inference_host='mistral', tariff_snapshot=snapshot_model_tariff(model)).to_bucket()
    supplier = calculate_cache_aware_supplier_cost(usage=bucket, model_pricing_details=model, inference_host='mistral')
    assert supplier['complete']
    assert float(supplier['cost_usd']) == pytest.approx((488 * 1.4 + 512 * 0.14 + 32 * 4.4) / 1000000)
    bucket['inference_host'] = 'openrouter'
    entry = build_model_usage_breakdown([bucket], lambda *_: model)['entries'][0]
    assert entry['billing_mode'] == 'ordinary_input'
    assert float(entry['category_credits']['cache_read']) == 0
