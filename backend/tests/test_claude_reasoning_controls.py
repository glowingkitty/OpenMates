# contract-test-file: infrastructure
"""Native Claude effort wire shapes and private thinking/tool continuation."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx
import pytest
import yaml
from botocore.session import Session
from botocore.validate import validate_parameters

from backend.apps.ai.llm_providers import anthropic_client, anthropic_direct_api, anthropic_reasoning, bedrock_client
from backend.apps.ai.llm_providers.bedrock_shared import ParsedBedrockToolCall, BedrockUsageMetadata, convert_messages_to_converse_format
from backend.apps.ai.utils.model_reasoning import resolve_reasoning_parameters


def _catalog():
    return yaml.safe_load((Path(__file__).parents[1] / 'providers/anthropic.yml').read_text())


@pytest.fixture(autouse=True)
def catalog(monkeypatch):
    monkeypatch.setattr(anthropic_reasoning.config_manager, 'get_provider_config', lambda *_: _catalog())


def _model(model_id):
    return next(model for model in _catalog()['models'] if model['id'] == model_id)


@pytest.mark.parametrize('model_id', ['claude-fable-5-1', 'claude-opus-5-5', 'claude-sonnet-5-5',
    'claude-haiku-5-5', 'claude-fable-5', 'claude-opus-5', 'claude-sonnet-5',
    'claude-sonnet-4-6', 'claude-opus-4-6', 'claude-opus-4-7', 'claude-opus-4-8', 'claude-opus-4-5-20251101'])
def test_declared_routes_native_level_mapping(model_id):
    model = _model(model_id)
    for server in model['servers']:
        for level in ['LOW', 'MEDIUM', 'HIGH', 'EXTRA_HIGH']:
            native = resolve_reasoning_parameters(model, server['id'], level)
            assert native
            body = anthropic_reasoning.claude_reasoning_body(server['model_id'], server['id'], native['reasoning_effort'])
            assert body['output_config']['effort'] == native['reasoning_effort']
            assert bool(body.get('thinking')) == server['reasoning_control']['adaptive_thinking']


def test_unsupported_models_and_hosts_preserve_defaults():
    model = _model('claude-haiku-4-5-20251001')
    for server in model['servers']:
        assert resolve_reasoning_parameters(model, server['id'], 'HIGH') == {}
        assert anthropic_reasoning.claude_reasoning_body(server['model_id'], server['id'], 'high') == {}
    assert anthropic_reasoning.claude_reasoning_body('claude-opus-5-5', 'aws_bedrock', 'high') == {}
    assert anthropic_reasoning.claude_reasoning_body('claude-opus-5-5', 'anthropic', None) == {}


@pytest.mark.parametrize('effort', [None, 'low', 'medium', 'high', 'xhigh'])
def test_anthropic_sdk_actual_wire(monkeypatch, effort):
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={'id': 'msg_test', 'type': 'message', 'role': 'assistant',
            'model': 'claude-opus-5-5', 'content': [{'type': 'text', 'text': 'ok'}],
            'stop_reason': 'end_turn', 'stop_sequence': None, 'usage': {'input_tokens': 1, 'output_tokens': 1}})
    client = anthropic.Anthropic(api_key='placeholder', http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(anthropic_client, '_anthropic_client_initialized', True)
    monkeypatch.setattr(anthropic_client, '_anthropic_direct_client', client)
    response = asyncio.run(anthropic_client.invoke_anthropic_chat_completions(
        'test', 'claude-opus-5-5', [{'role': 'user', 'content': 'hi'}], reasoning_effort=effort))
    assert response.success
    if effort:
        assert captured[0]['output_config'] == {'effort': effort}
        assert captured[0]['thinking'] == {'type': 'adaptive'}
    else:
        assert 'output_config' not in captured[0] and 'thinking' not in captured[0]
    client.close()


def test_native_cache_fields_merge_without_overwriting_effort(monkeypatch):
    captured = []
    async def process(*args, **kwargs):
        captured.append(args[2])
        return SimpleNamespace(success=True, tool_calls_made=None)
    monkeypatch.setattr(anthropic_direct_api, 'validate_native_cache_context', lambda *_: ([], [], set()))
    monkeypatch.setattr(anthropic_direct_api, '_prepare_messages_for_anthropic', lambda *a, **k: ([], [{'role': 'user', 'content': 'hi'}]))
    monkeypatch.setattr(anthropic_direct_api, '_process_direct_api_response', process)
    asyncio.run(anthropic_direct_api.invoke_direct_api('test', 'claude-opus-5-5', [], object(),
        native_cache_context={}, reasoning_effort='low'))
    assert captured[0]['extra_body'] == {'output_config': {'effort': 'low'},
        'thinking': {'type': 'adaptive'}, 'cache_control': {'type': 'ephemeral'}}


@pytest.mark.parametrize('effort', [None, 'low', 'medium', 'high', 'max'])
def test_bedrock_sdk_wire_and_signed_tool_replay(monkeypatch, effort):
    requests = []
    reasoning = {'reasoningContent': {'reasoningText': {'text': 'private', 'signature': 'signed'}}}
    def converse(**kwargs):
        requests.append(kwargs)
        shape = Session().get_service_model('bedrock-runtime').operation_model('Converse').input_shape
        validate_parameters(kwargs, shape)
        return {'output': {'message': {'role': 'assistant', 'content': [reasoning,
            {'toolUse': {'toolUseId': 'call1', 'name': 'check', 'input': {}}}]}},
            'stopReason': 'tool_use', 'usage': {'inputTokens': 1, 'outputTokens': 1, 'totalTokens': 2}}
    monkeypatch.setattr(bedrock_client, '_bedrock_runtime_client', SimpleNamespace(converse=converse))
    response = asyncio.run(bedrock_client.invoke_aws_bedrock_chat_completions(
        'test', 'eu.anthropic.claude-opus-4-6-v1', [{'role': 'user', 'content': 'hi'}], reasoning_effort=effort))
    assert response.success
    if effort:
        assert requests[0]['additionalModelRequestFields'] == {'thinking': {'type': 'adaptive'}, 'output_config': {'effort': effort}}
        assert 'temperature' not in requests[0]['inferenceConfig']
    else:
        assert 'additionalModelRequestFields' not in requests[0]
        assert requests[0]['inferenceConfig']['temperature'] == 0.7
    call = response.tool_calls_made[0]
    history = [{'role': 'assistant', 'tool_calls': [{'id': call.tool_call_id,
        'function': {'name': call.function_name, 'arguments': call.function_arguments_raw},
        'provider_transport_state': call.provider_transport_state}]}]
    _, replay = convert_messages_to_converse_format(history)
    assert replay[0]['content'][0] == reasoning
    assert replay[0]['content'][1]['toolUse']['toolUseId'] == 'call1'


@pytest.mark.parametrize('provider', ['anthropic', 'bedrock'])
def test_required_tool_contract_with_adaptive_reasoning(monkeypatch, provider):
    captured = []
    async def no_tool(*args, **kwargs):
        captured.append(args[2])
        return SimpleNamespace(success=True, tool_calls_made=None, direct_message_content='unsolicited')
    tools = [{'type': 'function', 'function': {'name': 'check', 'parameters': {'type': 'object', 'properties': {}}}}]
    if provider == 'anthropic':
        monkeypatch.setattr(anthropic_direct_api, '_process_direct_api_response', no_tool)
        response = asyncio.run(anthropic_direct_api.invoke_direct_api('test', 'claude-opus-5-5',
            [{'role': 'user', 'content': 'hi'}], object(), tools=tools, tool_choice='required', reasoning_effort='high'))
        assert captured[0]['tool_choice'] == {'type': 'auto'}
    else:
        monkeypatch.setattr(bedrock_client, '_bedrock_runtime_client', object())
        monkeypatch.setattr(bedrock_client, '_process_converse_response', no_tool)
        response = asyncio.run(bedrock_client.invoke_aws_bedrock_chat_completions('test', 'eu.anthropic.claude-opus-4-6-v1',
            [{'role': 'user', 'content': 'hi'}], tools=tools, tool_choice='required', reasoning_effort='high'))
        assert captured[0]['toolConfig']['toolChoice'] == {'auto': {}}
    assert not response.success and response.direct_message_content is None


def test_bedrock_stream_thinking_is_private_and_replayed(monkeypatch):
    events = [{'contentBlockDelta': {'contentBlockIndex': 0, 'delta': {'reasoningContent': {'text': 'private'}}}},
        {'contentBlockDelta': {'contentBlockIndex': 0, 'delta': {'reasoningContent': {'signature': 'signed'}}}},
        {'contentBlockStop': {'contentBlockIndex': 0}},
        {'contentBlockStart': {'contentBlockIndex': 1, 'start': {'toolUse': {'toolUseId': 'call1', 'name': 'check'}}}},
        {'contentBlockDelta': {'contentBlockIndex': 1, 'delta': {'toolUse': {'input': '{}'}}}},
        {'contentBlockStop': {'contentBlockIndex': 1}},
        {'metadata': {'usage': {'inputTokens': 1, 'outputTokens': 1, 'totalTokens': 2}}}]
    monkeypatch.setattr(bedrock_client, '_bedrock_runtime_client', SimpleNamespace(converse_stream=lambda **_: {'stream': events}))
    async def run():
        stream = await bedrock_client.invoke_aws_bedrock_chat_completions('test', 'eu.anthropic.claude-opus-4-6-v1',
            [{'role': 'user', 'content': 'hi'}], stream=True, reasoning_effort='high')
        return [item async for item in stream]
    chunks = asyncio.run(run())
    assert not any(isinstance(item, str) for item in chunks)
    call = next(item for item in chunks if isinstance(item, ParsedBedrockToolCall))
    assert call.provider_transport_state == {'bedrock_reasoning': [
        {'reasoningContent': {'reasoningText': {'text': 'private', 'signature': 'signed'}}}]}
    assert any(isinstance(item, BedrockUsageMetadata) for item in chunks)


@pytest.mark.parametrize('level,expected', [('LOW', 'low'), ('MEDIUM', 'medium'), ('HIGH', 'high'), ('EXTRA_HIGH', 'high')])
def test_bedrock_gpt_oss_uses_openai_parameter_without_claude_thinking(monkeypatch, level, expected):
    root = Path(__file__).parents[1]
    catalogs = {name: yaml.safe_load((root / f'providers/{name}.yml').read_text()) for name in ['openai', 'anthropic']}
    monkeypatch.setattr(bedrock_client.config_manager, 'get_provider_config', lambda name: catalogs[name])
    model = next(item for item in catalogs['openai']['models'] if item['id'] == 'gpt-oss-120b')
    server = next(item for item in model['servers'] if item['id'] == 'aws_bedrock')
    captured = []
    def converse(**kwargs):
        captured.append(kwargs)
        validate_parameters(kwargs, Session().get_service_model('bedrock-runtime').operation_model('Converse').input_shape)
        return {'output': {'message': {'content': [{'text': 'ok'}]}}, 'usage': {'inputTokens': 1, 'outputTokens': 1, 'totalTokens': 2}}
    monkeypatch.setattr(bedrock_client, '_bedrock_runtime_client', SimpleNamespace(converse=converse))
    response = asyncio.run(bedrock_client.invoke_aws_bedrock_chat_completions('test', server['model_id'],
        [{'role': 'user', 'content': 'hi'}], **resolve_reasoning_parameters(model, 'aws_bedrock', level)))
    assert response.success
    assert captured[0]['additionalModelRequestFields'] == {'reasoning_effort': expected}
    assert 'temperature' in captured[0]['inferenceConfig']


def test_bedrock_redacted_thinking_round_trips_through_json_state():
    from backend.apps.ai.llm_providers.bedrock_shared import encode_bedrock_reasoning
    original = {'reasoningContent': {'redactedContent': b'\x00\xffprivate'}}
    state = json.loads(json.dumps({'bedrock_reasoning': encode_bedrock_reasoning([original])}))
    _, messages = convert_messages_to_converse_format([{'role': 'assistant',
        'provider_transport_state': state, 'tool_calls': [{'id': 'call', 'function': {'name': 'check', 'arguments': '{}'}}]}])
    assert messages[0]['content'][0] == original


def test_main_processor_history_serialization_preserves_bedrock_signature():
    from backend.apps.ai.processing.main_processor import _format_tool_call_for_history
    from backend.apps.ai.utils.llm_utils import _transform_message_history_for_llm
    reasoning = {'reasoningContent': {'reasoningText': {'text': 'private', 'signature': 'signed'}}}
    call = ParsedBedrockToolCall(tool_call_id='call1', function_name='web-search',
        function_arguments_raw='{"query":"test"}', function_arguments_parsed={'query': 'test'},
        provider_transport_state={'bedrock_reasoning': [reasoning]})
    history = json.loads(json.dumps([
        {'role': 'assistant', 'content': '', 'tool_calls': [_format_tool_call_for_history(call)]},
        {'role': 'tool', 'tool_call_id': 'call1', 'content': 'result'},
    ]))
    transformed = _transform_message_history_for_llm(history)
    _, replay = convert_messages_to_converse_format(transformed)
    assert replay[0]['content'][0] == reasoning
    assert replay[0]['content'][1]['toolUse'] == {'toolUseId': 'call1', 'name': 'web-search', 'input': {'query': 'test'}}
    assert replay[1]['content'][0]['toolResult']['toolUseId'] == 'call1'
