"""Compare paid workflow authors with the deployed validator and retry loop.

Run in the dev API container with Vault-backed provider credentials. Instructions
and synthetic existing graphs are shared across arms; Jev runs once per case.
No workflow, account, wallet or schedule is changed. Strict Cerebras and streaming
Groq and Mercury JSON transport reuse the actual Gemini parser, compiler and correction loop.
Usage includes reasoning and retries; reports are private and mode 0600.
The first HTTP 429 saves a partial report and stops all remaining arms/cases.
Usage: python -m backend.scripts.benchmark_workflow_authoring_models --allow-paid-dev-inference
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import json
import logging
import math
import os
import re
from pathlib import Path
import time
from typing import Any

import httpx

from backend.core.api.app.services import workflow_registry_planner as planner_module
from backend.core.api.app.services.workflow_authoring_preselection import WorkflowAuthoringPreselector, WorkflowPreselection
from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry
from backend.core.api.app.services.workflow_gemini_authoring import (
    WorkflowGeminiAuthor,
)
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.typesafe.client import JevDecisionClient
from backend.scripts.workflow_authoring_model_cases import CORPUS_VERSION, cases, evaluate

ARMS = {
    'gemini': ('google', 'gemini-3.8-flash', (0.75, 3.75)),
    'cerebras-oss': ('cerebras', 'gpt-oss-120b', (0.35, 0.75)),
    'cerebras-qwen': ('cerebras', 'qwen-3.8-27b', (0.99, 1.49)),
    'groq-oss': ('groq', 'openai/gpt-oss-120b', (0.15, 0.60)),
    'groq-qwen': ('groq', 'qwen/qwen3.8-27b', (0.80, 4.00)),
}
ARMS.update({name + '-full': settings for name, settings in list(ARMS.items()) if name != 'gemini'})
# Per-million USD: published promotional rates; retain regular rates separately.
ARMS.update({
    'mercury-instant': ('inception_labs', 'mercury-3', (0.10, 0.35)),
    'mercury-low': ('inception_labs', 'mercury-3', (0.10, 0.35)),
    'mercury-openrouter-none': ('openrouter', 'inception/mercury-3', (0.10, 0.35)),
    'mercury-openrouter-low': ('openrouter', 'inception/mercury-3', (0.10, 0.35)),
})
MERCURY_REGULAR_PRICES = (0.20, 0.70)
ENDPOINTS = {
    'cerebras': 'https://api.cerebras.ai/v1/chat/completions',
    'groq': 'https://api.groq.com/openai/v1/chat/completions',
    'inception_labs': 'https://api.inceptionlabs.ai/v1/chat/completions',
    'openrouter': 'https://openrouter.ai/api/v1/chat/completions',
}


class BenchmarkAvailabilityStop(RuntimeError):
    """End this benchmark before the planner retries a rate-limited provider."""


def mark_availability_stop(report: dict, row: dict, transport: str) -> None:
    """Retain the attempted row and count unexecuted work separately from quality."""
    row.update(availability_status='rate_limited', quality_evaluated=False)
    report.update(partial=True, stop_reason='http_429', availability_stop={
        'transport': transport, 'arm': row['arm'], 'case': row['case'],
        'repeat': row['repeat'], 'http_status': 429,
    }, skipped_results=report['planned_results'] - len(report['results']))
    print(json.dumps({'availability_stop': report['availability_stop'], 'partial': True,
                      'skipped_results': report['skipped_results']}), flush=True)


def gateway_payload(payload: dict, effort: str) -> dict:
    """Pin benchmark-only gateway requests to Inception; never alter product routing.

    OpenRouter documents effort none/low at:
    https://openrouter.ai/docs/guides/best-practices/reasoning-tokens
    Gateway timing includes gateway transit and is not direct API timing.
    """
    body = deepcopy(payload)
    body['model'] = 'inception/mercury-3'
    body['max_tokens'] = body.pop('max_completion_tokens')
    body.pop('reasoning_effort', None)
    body['reasoning'] = {'effort': effort}
    body['provider'] = {'only': ['inception'], 'allow_fallbacks': False,
                        'require_parameters': True, 'data_collection': 'deny'}
    return body


def arm_reasoning(arm: str, default: str = 'low') -> str:
    if arm.startswith('mercury-openrouter-'):
        return arm.removeprefix('mercury-openrouter-')
    return arm.removeprefix('mercury-') if arm.startswith('mercury-') else default


async def selected_provider_keys(manager, arms):
    """Read only transport credentials required by selected benchmark arms."""
    providers = sorted({ARMS[arm][0] for arm in arms} - {'google'})
    keys = {}
    for provider in providers:
        key = await manager.get_secret(
            secret_path='kv/data/providers/' + provider, secret_key='api_key')
        if not key:
            raise ValueError('Selected benchmark provider credential unavailable: ' + provider)
        keys[provider] = key
    return keys


class BridgeSecrets:
    """The Google-shaped parser envelope needs no actual Google credential."""
    async def get_secret(self, **kwargs):
        return 'evaluation-transport-placeholder'



def cerebras_schema(schema: dict) -> dict:
    """Expand the header discriminator into closed full-schema alternatives.

    Google accepts partial object constraints within anyOf. Cerebras requires
    each object alternative to be closed. No nullable fields or semantic node
    constraints change; the original schema is still validated by the adapter.
    """
    result = deepcopy(schema)
    header = result['properties']['workflows']['items']['anyOf'][0]['properties']['header']
    props = header['properties']
    variants = []
    for alternative in header.pop('anyOf'):
        variant = deepcopy(header)
        variant['properties'] = deepcopy(props)
        variant['properties']['operation'] = alternative['properties']['operation']
        variant['required'] = list(dict.fromkeys(header['required'] + alternative['required']))
        variants.append(variant)
    result['properties']['workflows']['items']['anyOf'][0]['properties']['header'] = {'anyOf': variants}
    return result


def strict_full_schema(schema: dict) -> dict:
    """Use required nullable optionals for portable strict full responses.

    Null means an absent optional transport field. Strip those null fields before
    applying the original schema and compiler. Never alter JSON inside *_json
    strings, where actual null values may be part of a skill's legitimate input.
    """
    def convert(item):
        if isinstance(item, list):
            return [convert(value) for value in item]
        if not isinstance(item, dict):
            return item
        result = {key: convert(value) for key, value in item.items()
                  if key not in {'minimum','maximum','minItems','maxItems','minLength','maxLength'}}
        if result.get('type') == 'object':
            required = set(item.get('required', []))
            properties = result.get('properties', {})
            def nullable(value):
                variants = value['anyOf'] if set(value) == {'anyOf'} else [value]
                return {'anyOf': [*variants, {'type': 'null'}]}
            result['properties'] = {key: value if key in required else nullable(value)
                                    for key, value in properties.items()}
            result['required'] = list(properties)
            result['additionalProperties'] = False
        return result
    return convert(cerebras_schema(schema))


def omit_null_optionals(item):
    if isinstance(item, dict):
        return {key: omit_null_optionals(value) for key, value in item.items() if value is not None}
    if isinstance(item, list):
        return [omit_null_optionals(value) for value in item]
    return item


def guided_schema(schema: dict) -> dict:
    """Constrain each flat node kind to fields the production compiler accepts."""
    result = deepcopy(schema)
    workflow = result['properties']['workflows']['items']['anyOf'][0]
    node = workflow['properties']['nodes']['items']
    common = {'kind', 'id', 'parent_check_id', 'branch'}
    fields = {'app': {'capability', 'input_json'}, 'ask_ai': {'prompt_json'},
              'check': {'mode', 'predicate_json', 'question_json', 'selected_inputs_json'},
              'send': {'title', 'message_json', 'blocks_json'}, 'end': set()}
    variants = []
    for kind, extra in fields.items():
        variant = deepcopy(node)
        variant['properties'] = {key: value for key, value in variant['properties'].items()
                                 if key in common | extra}
        variant['properties']['kind'] = {'type': 'string', 'enum': [kind]}
        variants.append(variant)
    workflow['properties']['nodes']['items'] = {'anyOf': variants}
    return result


GUIDANCE = '''\nNode examples and exact distinctions (replace IDs/values with the request):
Ask AI is a builtin node kind, not kind app. It has NO capability, input_json, question_json, selected_inputs_json, message_json or blocks_json.
{"kind":"ask_ai","id":"summarize","prompt_json":"[{\\"text\\":\\"Summarize these results for a founder: \\"},{\\"ref\\":{\\"step\\":\\"search\\",\\"field\\":\\"results\\"}}]"}
AI Check uses question_json segments and selected_inputs_json bare step/field objects, WITHOUT ref wrappers:
{"kind":"check","id":"relevant","mode":"ai","question_json":"[{\\"text\\":\\"Does any result matter to a small European startup?\\"}]","selected_inputs_json":"[{\\"step\\":\\"search\\",\\"field\\":\\"results\\"}]"}
Send chat example: {"kind":"send","id":"deliver","title":"Summary","message_json":"[{\\"ref\\":{\\"step\\":\\"summarize\\",\\"field\\":\\"answer\\"}}]"}
Weather result references must use field results (not summary/forecast_day). For multiple cities, include each forecast's results as a ref segment in prompt_json.
A schedule-only edit uses the exact owned workflow_id copied verbatim and nodes:[], preserving the original graph. Never retype or abbreviate target IDs.
Every weekday means a weekly schedule with monday,tuesday,wednesday,thursday,friday.\n'''


def validated_usage(provider: str, usage: Any) -> dict:
    """Keep exact provider integers; missing/invalid counters never become zeros."""
    if not isinstance(usage, dict):
        return {'usage_complete': False, 'usage_counters_valid': False,
                'input_tokens': None, 'output_tokens': None,
                'thinking_tokens': None, 'cached_input_tokens': None}
    def counter(value):
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0
    if provider == 'google':
        input_tokens = usage.get('promptTokenCount')
        authored = usage.get('candidatesTokenCount')
        reasoning = usage.get('thoughtsTokenCount', 0)
        output_tokens = authored + reasoning if counter(authored) and counter(reasoning) else None
        cached = usage.get('cachedContentTokenCount')
        total = usage.get('totalTokenCount')
    else:
        input_tokens, output_tokens = usage.get('prompt_tokens'), usage.get('completion_tokens')
        reasoning_details, cache_details = usage.get('completion_tokens_details'), usage.get('prompt_tokens_details')
        if reasoning_details is not None and not isinstance(reasoning_details, dict):
            return validated_usage(provider, None)
        if cache_details is not None and not isinstance(cache_details, dict):
            return validated_usage(provider, None)
        reasoning = (reasoning_details or {}).get('reasoning_tokens')
        cached = (cache_details or {}).get('cached_tokens')
        total = usage.get('total_tokens')
    valid = counter(input_tokens) and counter(output_tokens)
    valid = valid and all(value is None or (counter(value) and value <= ceiling)
                          for value, ceiling in ((reasoning, output_tokens), (cached, input_tokens)))
    valid = valid and (total is None or (counter(total) and total == input_tokens + output_tokens))
    return {'usage_complete': valid, 'usage_counters_valid': valid,
            'input_tokens': input_tokens, 'output_tokens': output_tokens,
            'thinking_tokens': reasoning, 'cached_input_tokens': cached}


class ConvertedStream(httpx.AsyncByteStream):
    """Map SSE envelopes only; preserve content fragments and parser behavior."""
    def __init__(self, response: httpx.Response, started: float, stats: dict):
        self.response, self.started, self.stats = response, started, stats

    async def __aiter__(self):
        async for line in self.response.aiter_lines():
            if not line.startswith('data:'):
                continue
            data = line[5:].strip()
            if data == '[DONE]':
                self.stats['done_seen'] = True
                continue
            if not data:
                continue
            event = json.loads(data)
            self.stats.setdefault('raw_native_events', []).append(event)
            for identity in ('provider', 'model'):
                if event.get(identity):
                    self.stats['observed_' + identity] = event[identity]
            if event.get('error'):
                yield b'data: {"error":{"status":"provider_stream_error"}}\n\n'
                continue
            mapped: dict[str, Any] = {}
            usage = event.get('usage') or (event.get('x_groq') or {}).get('usage')
            if usage:
                self.stats['usage'] = usage
                counters = validated_usage('openai', usage)
                self.stats['usage_counters_valid'] = counters['usage_counters_valid']
                if counters['usage_complete']:
                    reasoning = counters['thinking_tokens'] or 0
                    mapped['usageMetadata'] = {'promptTokenCount': counters['input_tokens'],
                                              'candidatesTokenCount': counters['output_tokens'] - reasoning,
                                              'thoughtsTokenCount': reasoning}
            candidates = []
            for choice in event.get('choices') or []:
                content = (choice.get('delta') or {}).get('content')
                if content:
                    self.stats['raw_answer'] = (self.stats.get('raw_answer', '') + content)[:131072]
                if content and self.stats.get('first_content_ms') is None:
                    self.stats['first_content_ms'] = round((time.perf_counter() - self.started) * 1000, 1)
                candidate = {'content': {'parts': [{'text': content}]} if content else {'parts': []}}
                if choice.get('finish_reason'):
                    self.stats['finish_reason'] = choice['finish_reason']
                    candidate['finishReason'] = 'STOP' if choice['finish_reason'] == 'stop' else 'MAX_TOKENS'
                candidates.append(candidate)
            if candidates:
                mapped['candidates'] = candidates
            if mapped:
                yield ('data: ' + json.dumps(mapped) + '\n\n').encode()

    async def aclose(self):
        await self.response.aclose()


class GoogleRecordingStream(httpx.AsyncByteStream):
    """Observe authored text and usage without changing native Google events."""
    def __init__(self, response, started, stats):
        self.response, self.started, self.stats = response, started, stats

    async def __aiter__(self):
        async for line in self.response.aiter_lines():
            if line.startswith('data:'):
                event = json.loads(line[5:].strip())
                self.stats.setdefault('raw_native_events', []).append(event)
                for candidate in event.get('candidates') or []:
                    if candidate.get('finishReason'):
                        self.stats['finish_reason'] = candidate['finishReason']
                if event.get('modelVersion') or event.get('model'):
                    self.stats['observed_model'] = event.get('modelVersion') or event.get('model')
                if event.get('usageMetadata'):
                    self.stats['usage'] = event['usageMetadata']
                text = ''.join(part.get('text', '') for candidate in event.get('candidates', [])
                               for part in (candidate.get('content') or {}).get('parts', [])
                               if not part.get('thought'))
                if text and self.stats['first_content_ms'] is None:
                    self.stats['first_content_ms'] = round((time.perf_counter() - self.started) * 1000, 1)
            yield (line + '\n').encode()

    async def aclose(self):
        await self.response.aclose()


class GoogleRecordingTransport(httpx.AsyncBaseTransport):
    """Pass through native request bytes, recording content TTFT per attempt."""
    def __init__(self, client):
        self.client, self.attempts = client, []

    async def handle_async_request(self, request):
        started = time.perf_counter()
        stats = {'first_content_ms': None, 'usage': None}
        self.attempts.append(stats)
        response = await self.client.send(request, stream=True)
        stats['http_status'] = response.status_code
        if response.status_code == 429:
            await response.aclose()
            raise BenchmarkAvailabilityStop('http_429')
        headers = {key: value for key, value in response.headers.items()
                   if key.lower() not in {'content-encoding', 'content-length'}}
        return httpx.Response(response.status_code, headers=headers,
                              stream=GoogleRecordingStream(response, started, stats))


class OpenAITransport(httpx.AsyncBaseTransport):
    """An evaluation-only bridge around the production structured author."""
    def __init__(self, client, provider, model, key, reasoning='low', full=False, profile='native'):
        self.client, self.provider, self.model, self.key = client, provider, model, key
        self.reasoning = reasoning
        self.full = full
        self.profile = profile
        self.attempts: list[dict] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        schema = body['generationConfig']['responseJsonSchema']
        system = body['systemInstruction']['parts'][0]['text']
        user = body['contents'][0]['parts'][0]['text']
        if self.profile == 'guided':
            schema = guided_schema(schema)
            system += GUIDANCE
        if self.full:
            fmt = {'type': 'json_schema', 'json_schema': {
                'name': 'workflow_authoring', 'strict': True, 'schema': strict_full_schema(schema)}}
            system += '\nFor the strict transport, encode unused optional fields as null. The backend removes optional null fields before validation. Preserve header before nodes.'
        elif self.provider in {'inception_labs', 'openrouter'}:
            fmt = {'type': 'json_schema', 'json_schema': {
                'name': 'workflow_authoring', 'strict': True, 'schema': schema}}
        elif self.provider == 'cerebras':
            fmt = {'type': 'json_schema', 'json_schema': {
                'name': 'workflow_authoring', 'strict': True, 'schema': cerebras_schema(schema)}}
        else:
            fmt = {'type': 'json_object'}
            system += '\nTransport JSON schema (every complete record is validated): ' + json.dumps(schema, separators=(',', ':'))
        payload = {'model': self.model, 'messages': [{'role': 'system', 'content': system},
                   {'role': 'user', 'content': user}], 'stream': not self.full,
                   'response_format': fmt,
                   'max_completion_tokens': 8192,
                   'temperature': 0.5 if self.provider in {'inception_labs', 'openrouter'} else 1.0,
                   'reasoning_effort': self.reasoning}
        if self.provider == 'cerebras':
            payload['reasoning_format'] = 'parsed'
        if not self.full:
            payload['stream_options'] = {'include_usage': True}
        if self.provider == 'openrouter':
            payload = gateway_payload(payload, self.reasoning)
        endpoint = ENDPOINTS[self.provider]
        started = time.perf_counter()
        stats: dict = {'first_content_ms': None, 'usage': None}
        self.attempts.append(stats)
        response = await self.client.send(self.client.build_request('POST', endpoint,
            headers={'Authorization': 'Bearer ' + self.key}, json=payload), stream=True)
        stats['http_status'] = response.status_code
        if response.status_code != 200:
            await response.aread()
            # Retain safe structured diagnostics, not a response body or auth data.
            try:
                error = response.json().get('error') or {}
                stats['provider_error_code'] = str(error.get('code') or error.get('type') or '')[:80]
                message = str(error.get('message') or '')
                stats['provider_error_message'] = 'provider_request_rejected' if self.key in message else message[:500]
            except (ValueError, AttributeError):
                pass
            await response.aclose()
            if response.status_code == 429:
                raise BenchmarkAvailabilityStop('http_429')
            return httpx.Response(response.status_code, content=b'provider_request_rejected')
        if self.full:
            await response.aread()
            result = response.json()
            await response.aclose()
            message = (result.get('choices') or [{}])[0].get('message') or {}
            answer = message.get('content') or ''
            stats['raw_answer'] = answer[:131072]
            stats['first_content_ms'] = round((time.perf_counter() - started) * 1000, 1)
            usage = result.get('usage') or {}
            stats['usage'] = usage or None
            counters = validated_usage(self.provider, usage)
            clean = json.dumps(omit_null_optionals(json.loads(answer)), ensure_ascii=False)
            finish = (result.get('choices') or [{}])[0].get('finish_reason')
            stats['finish_reason'] = finish
            stats['observed_model'] = result.get('model')
            stats['observed_provider'] = result.get('provider')
            stats['raw_native_events'] = [result]
            mapped = {'candidates': [{'content': {'parts': [{'text': clean}]},
                                     'finishReason': 'STOP' if finish == 'stop' else 'MAX_TOKENS'}]}
            if counters['usage_complete']:
                reasoning = counters['thinking_tokens'] or 0
                mapped['usageMetadata'] = {'promptTokenCount': counters['input_tokens'],
                    'candidatesTokenCount': counters['output_tokens'] - reasoning, 'thoughtsTokenCount': reasoning}
            return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                content=('data: ' + json.dumps(mapped) + '\n\n').encode())
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                              stream=ConvertedStream(response, started, stats))


class BenchAuthor:
    def __init__(self, manager, client, arm, key, reasoning='low', profile='native'):
        self.arm, self.provider, self.model, self.prices = arm, *ARMS[arm]
        self.reasoning = arm_reasoning(arm, reasoning)
        self.bridge = None if arm == 'gemini' else OpenAITransport(client, self.provider, self.model, key, self.reasoning, full=arm.endswith('-full'), profile=profile)
        self.transport = self.bridge or GoogleRecordingTransport(client)
        self.client = httpx.AsyncClient(transport=self.transport, timeout=45)
        self.delegate = WorkflowGeminiAuthor(manager if self.bridge is None else BridgeSecrets(), self.client)

    async def generate(self, **kwargs):
        try:
            plan, metrics = await self.delegate.generate(**kwargs)
        except BaseException as exc:
            metrics = getattr(exc, 'metrics', None)
            if isinstance(metrics, dict):
                self.price(metrics)
            raise
        self.price(metrics)
        return plan, metrics

    def price(self, metrics):
        if not self.transport.attempts:
            metrics['usage_complete'] = False
            metrics['estimated_cost_usd'] = None
            return
        details = self.transport.attempts[-1]
        metrics.update(validated_usage(self.provider, details.get('usage')))
        metrics.update(transport=self.provider, observed_provider=details.get('observed_provider'),
                       observed_model=details.get('observed_model'), first_content_ms=details.get('first_content_ms'),
                       provider_http_status=details.get('http_status'))
        reported = (details.get('usage') or {}).get('cost')
        metrics['provider_reported_cost_usd'] = (reported if isinstance(reported, (int, float))
            and not isinstance(reported, bool) and math.isfinite(reported) and reported >= 0 else None)
        metrics['estimated_cost_usd'] = None
        if self.provider == 'inception_labs':
            metrics['regular_cost_usd'] = None
        if not metrics['usage_complete']:
            return
        def cost(prices):
            return round((metrics['input_tokens'] * prices[0] + metrics['output_tokens'] * prices[1]) / 1_000_000, 8)
        metrics['estimated_cost_usd'] = cost(self.prices)
        if self.provider == 'inception_labs':
            metrics['regular_cost_usd'] = cost(MERCURY_REGULAR_PRICES)

    async def close(self):
        await self.client.aclose()


class FrozenSelector:
    def __init__(self, selection): self.selection = selection
    async def select(self, *args, **kwargs):
        return self.selection


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as out:
        os.fchmod(out.fileno(), 0o600)
        json.dump(report, out, indent=2, default=str)


def provider_identity(arm: str, attempts: list[dict]) -> dict:
    """Check supplied response identities; never invent missing provider metadata."""
    provider, expected, _ = ARMS[arm]
    observed = [item['observed_model'] for item in attempts if item.get('observed_model')]
    def matches(model):
        return isinstance(model, str) and (model == expected or (provider == 'google'
            and re.fullmatch(re.escape(expected) + r'-(?:preview-)?\d[\d.-]*', model) is not None))
    wrong_model = any(not matches(model) for model in observed)
    providers = [str(item['observed_provider']) for item in attempts if item.get('observed_provider')]
    wrong_provider = provider == 'openrouter' and any(name.casefold() != 'inception' for name in providers)
    status = 'mismatch' if wrong_model or wrong_provider else 'matched' if observed else 'unreported'
    return {'expected_model': expected, 'transport': provider,
            'endpoint': ('https://generativelanguage.googleapis.com' if provider == 'google' else ENDPOINTS[provider]),
            'observed_models': observed, 'observed_providers': providers,
            'response_status': status, 'comparison_eligible': status != 'mismatch'}


async def run(args):
    logging.disable(logging.CRITICAL)
    manager = SecretsManager()
    await manager.initialize()
    report = {'revision': args.revision, 'arms': {k: ARMS[k] for k in args.arms},
              'reasoning_effort': {arm: arm_reasoning(arm, args.reasoning) for arm in args.arms},
              'mercury_prices_usd_per_million': {'promotional': (0.10, 0.35), 'regular': MERCURY_REGULAR_PRICES},
              'profile': args.profile, 'in_memory_only': True, 'selections': [], 'results': []}
    selected_cases = [c for c in cases(getattr(args, 'suite', 'baseline')) if not args.cases or c.id in args.cases]
    if not selected_cases or args.cases and len(selected_cases) != len(set(args.cases)):
        raise ValueError('Unknown or duplicate case')
    report['suite'] = getattr(args, 'suite', 'baseline')
    report['corpus_version'] = CORPUS_VERSION
    report['case_bank'] = [{'id': case.id, 'language': case.language, 'text': case.text,
        'expected_summary': case.expected_summary, 'expected_capabilities': case.expected_capability_ids,
        'expanded_contract': case.expectations} for case in selected_cases]
    report.update(partial=True, planned_results=len(selected_cases) * args.repeats * len(args.arms),
                  skipped_results=0)
    original_selector = planner_module.WorkflowAuthoringPreselector
    frozen_selections = ({item['case']: item for item in json.loads(args.selection_report.read_text())['selections']}
                         if args.selection_report else {})
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=5)) as client:
            keys = await selected_provider_keys(manager, args.arms)
            jev = JevDecisionClient(secrets_manager=manager, http_client=client, timeout_seconds=3, max_retries=0)
            selector = WorkflowAuthoringPreselector(jev_client=jev, registry=WorkflowCapabilityRegistry())
            for case_index, case in enumerate(selected_cases):
                if args.selection_report:
                    source = frozen_selections[case.id]
                    info = source['context']
                    selection = WorkflowPreselection(
                        capabilities=[selector.registry.get_capability(item['id']) for item in info['capabilities']],
                        operation=info['operation'], check_mode=info['check_mode'], chat_delivery=info['chat_delivery'],
                        scores={}, metrics=source['metrics'], workflow_count=info['workflow_count'],
                        request_clarity=info['request_clarity'], schedule_timezone=info['schedule_timezone'],
                        preserve_schedule_timezone=info['preserve_schedule_timezone'])
                else:
                    selection = await selector.select(case.text, timezone=case.timezone, selected_workflow=case.selected_workflow)
                report['selections'].append({'case': case.id, 'context': selection.context(), 'metrics': selection.metrics,
                    'missing_expected_capabilities': sorted(set(case.expected_capability_ids) - {c.id for c in selection.capabilities})})
                planner_module.WorkflowAuthoringPreselector = lambda **kw: FrozenSelector(selection)
                for repeat in range(args.repeats):
                    # Rotate model order to reduce a systematic warming/order bias.
                    offset = (case_index + repeat) % len(args.arms)
                    arms = args.arms[offset:] + args.arms[:offset]
                    for arm in arms:
                        provider = ARMS[arm][0]
                        author = BenchAuthor(manager, client, arm, keys.get(provider), args.reasoning, args.profile)
                        started = time.perf_counter()
                        header_times, node_times, corrections = [], [], []
                        def component(event):
                            if event.get('phase') == 'retrying_node':
                                corrections.append(event)
                        def checkpoint(event):
                            if event.get('accepted_node_count'):
                                node_times.append(round((time.perf_counter() - started) * 1000, 1))
                            else:
                                header_times.append(round((time.perf_counter() - started) * 1000, 1))
                        context = {'timezone': case.timezone, '_on_component': component, '_on_checkpoint': checkpoint}
                        if case.selected_workflow:
                            context['selected_workflow'] = case.selected_workflow
                        row = {'case': case.id, 'arm': arm, 'repeat': repeat, 'exact_input': case.text,
                               'expected_summary': case.expected_summary, 'intent_match': False, 'graph_valid': False}
                        try:
                            plan = await planner_module.WorkflowRegistryPlanner(secrets_manager=manager)._plan(
                                case.text, context, jev, author)
                            metrics = plan.get('_authoring_metrics', plan.get('authoring_metrics', {}))
                            if not metrics:
                                # Current planner attaches metrics under the public authoring key.
                                metrics = plan.get('metrics', {})
                            operations = plan.get('operations') if plan.get('action') in {'batch', 'partial'} else [plan]
                            issues = evaluate(case, operations or [])
                            row.update(action=plan.get('action'), reason=plan.get('reason'), semantic_issues=issues,
                                graph_valid=plan.get('action') in {'create_workflow', 'update_workflow', 'batch'},
                                intent_match=not issues and plan.get('action') != 'partial',
                                plan=plan, metrics=metrics)
                        except BenchmarkAvailabilityStop:
                            row.update(http_status=429, graph_valid=None, intent_match=None,
                                       semantic_issues=[], error_type='BenchmarkAvailabilityStop')
                        except Exception as exc:
                            row.update(error_type=type(exc).__name__, error=str(exc)[:200])
                        finally:
                            row.update(wall_ms=round((time.perf_counter() - started) * 1000, 1),
                                first_header_ms=header_times[0] if header_times else None,
                                first_node_ms=node_times[0] if node_times else None,
                                validated_node_events=len(node_times), corrections=corrections,
                                provider_attempts=author.transport.attempts,
                                provider_identity=provider_identity(arm, author.transport.attempts))
                            await author.close()
                        report['results'].append(row)
                        if any(attempt.get('http_status') == 429 for attempt in row['provider_attempts']):
                            mark_availability_stop(report, row, provider)
                            write_report(args.output, report)
                            return
                        write_report(args.output, report)
                        print(json.dumps({k: row.get(k) for k in ('case','arm','repeat','action','reason','graph_valid','intent_match','semantic_issues','wall_ms','first_header_ms','first_node_ms')}, separators=(',', ':')), flush=True)
        report['partial'] = False
    finally:
        planner_module.WorkflowAuthoringPreselector = original_selector
        await manager.aclose()
        write_report(args.output, report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-paid-dev-inference', action='store_true')
    parser.add_argument('--revision', required=True)
    parser.add_argument('--arms', nargs='+', choices=list(ARMS), default=['gemini','mercury-openrouter-none','mercury-openrouter-low'])
    parser.add_argument('--cases', nargs='+')
    parser.add_argument('--suite', choices=('baseline', 'expanded'), default='baseline',
                        help='Original eight cases, or all24 predeclared quality cases')
    parser.add_argument('--selection-report', type=Path, help='Reuse measured Jev decisions for an exactly paired author comparison')
    parser.add_argument('--repeats', type=int, default=2, choices=(1,2))
    parser.add_argument('--reasoning', choices=('none','low','medium'), default='low')
    parser.add_argument('--profile', choices=('native','guided'), default='native')
    parser.add_argument('--output', type=Path, default=Path('/tmp/workflow-authoring-models3e12.json'))
    args = parser.parse_args()
    if args.profile == 'guided' and 'gemini' in args.arms:
        parser.error('Guided profile currently evaluates the OSS transport only; use native for Gemini')
    if not args.allow_paid_dev_inference or os.getenv('CI'):
        parser.error('Explicit paid dev inference opt-in required; never run in CI')
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
