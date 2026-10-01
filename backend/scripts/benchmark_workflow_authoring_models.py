"""Compare paid workflow authors with the deployed validator and retry loop.

Run in the dev API container with Vault-backed provider credentials. Instructions
and synthetic existing graphs are shared across arms; Jev runs once per case.
No workflow, account, wallet or schedule is changed. Strict Cerebras and streaming
Groq JSON transport reuse the actual Gemini parser, compiler and correction loop.
Usage includes reasoning and retries; reports are private and mode 0600.
Usage: python -m backend.scripts.benchmark_workflow_authoring_models --allow-paid-dev-inference
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import json
import logging
import os
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
from backend.scripts.workflow_authoring_model_cases import cases, evaluate

ARMS = {
    'gemini': ('google', 'gemini-3.8-flash', (0.75, 3.75)),
    'cerebras-oss': ('cerebras', 'gpt-oss-120b', (0.35, 0.75)),
    'cerebras-qwen': ('cerebras', 'qwen-3.8-27b', (0.99, 1.49)),
    'groq-oss': ('groq', 'openai/gpt-oss-120b', (0.15, 0.60)),
    'groq-qwen': ('groq', 'qwen/qwen3.8-27b', (0.80, 4.00)),
}
ARMS.update({name + '-full': settings for name, settings in list(ARMS.items()) if name != 'gemini'})


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


class ConvertedStream(httpx.AsyncByteStream):
    """Map SSE envelopes only; preserve content fragments and parser behavior."""
    def __init__(self, response: httpx.Response, started: float, stats: dict):
        self.response, self.started, self.stats = response, started, stats

    async def __aiter__(self):
        async for line in self.response.aiter_lines():
            if not line.startswith('data:'):
                continue
            data = line[5:].strip()
            if not data or data == '[DONE]':
                continue
            event = json.loads(data)
            if event.get('error'):
                yield b'data: {"error":{"status":"provider_stream_error"}}\n\n'
                continue
            mapped: dict[str, Any] = {}
            usage = event.get('usage') or (event.get('x_groq') or {}).get('usage')
            if usage:
                self.stats['usage'] = usage
                reasoning = int((usage.get('completion_tokens_details') or {}).get('reasoning_tokens') or 0)
                total = int(usage.get('completion_tokens') or 0)
                mapped['usageMetadata'] = {'promptTokenCount': int(usage.get('prompt_tokens') or 0),
                                          'candidatesTokenCount': max(0, total - reasoning),
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
                    candidate['finishReason'] = 'STOP' if choice['finish_reason'] == 'stop' else 'MAX_TOKENS'
                candidates.append(candidate)
            if candidates:
                mapped['candidates'] = candidates
            if mapped:
                yield ('data: ' + json.dumps(mapped) + '\n\n').encode()

    async def aclose(self):
        await self.response.aclose()


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
        elif self.provider == 'cerebras':
            fmt = {'type': 'json_schema', 'json_schema': {
                'name': 'workflow_authoring', 'strict': True, 'schema': cerebras_schema(schema)}}
        else:
            fmt = {'type': 'json_object'}
            system += '\nTransport JSON schema (every complete record is validated): ' + json.dumps(schema, separators=(',', ':'))
        payload = {'model': self.model, 'messages': [{'role': 'system', 'content': system},
                   {'role': 'user', 'content': user}], 'stream': not self.full,
                   'response_format': fmt,
                   'max_completion_tokens': 8192, 'temperature': 1.0,
                   'reasoning_effort': self.reasoning}
        if self.provider == 'cerebras':
            payload['reasoning_format'] = 'parsed'
        if not self.full:
            payload['stream_options'] = {'include_usage': True}
        endpoint = ('https://api.cerebras.ai/v1/chat/completions' if self.provider == 'cerebras'
                    else 'https://api.groq.com/openai/v1/chat/completions')
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
            total = int(usage.get('completion_tokens') or 0)
            reasoning = int((usage.get('completion_tokens_details') or {}).get('reasoning_tokens') or 0)
            clean = json.dumps(omit_null_optionals(json.loads(answer)), ensure_ascii=False)
            finish = (result.get('choices') or [{}])[0].get('finish_reason')
            mapped = {'usageMetadata': {'promptTokenCount': int(usage.get('prompt_tokens') or 0),
                'candidatesTokenCount': max(0, total - reasoning), 'thoughtsTokenCount': reasoning},
                'candidates': [{'content': {'parts': [{'text': clean}]},
                                'finishReason': 'STOP' if finish == 'stop' else 'MAX_TOKENS'}]}
            return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                content=('data: ' + json.dumps(mapped) + '\n\n').encode())
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                              stream=ConvertedStream(response, started, stats))


class BenchAuthor:
    def __init__(self, manager, client, arm, key, reasoning='low', profile='native'):
        self.arm, self.provider, self.model, self.prices = arm, *ARMS[arm]
        self.bridge = None if arm == 'gemini' else OpenAITransport(client, self.provider, self.model, key, reasoning, full=arm.endswith('-full'), profile=profile)
        self.client = client if self.bridge is None else httpx.AsyncClient(transport=self.bridge, timeout=45)
        self.delegate = WorkflowGeminiAuthor(manager, self.client)

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
        if self.bridge:
            details = self.bridge.attempts[-1]
            metrics['first_content_ms'] = details.get('first_content_ms')
            metrics['provider_http_status'] = details.get('http_status')
            if details.get('usage') is None:
                metrics['estimated_cost_usd'] = None
                return
            usage = details['usage']
            metrics['input_tokens'] = int(usage.get('prompt_tokens') or 0)
            metrics['output_tokens'] = int(usage.get('completion_tokens') or 0)
            metrics['thinking_tokens'] = int((usage.get('completion_tokens_details') or {}).get('reasoning_tokens') or 0)
        metrics['estimated_cost_usd'] = round((metrics['input_tokens'] * self.prices[0]
                                               + metrics['output_tokens'] * self.prices[1]) / 1_000_000, 8)

    async def close(self):
        if self.bridge:
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


async def run(args):
    logging.disable(logging.CRITICAL)
    manager = SecretsManager()
    await manager.initialize()
    report = {'revision': args.revision, 'arms': {k: ARMS[k] for k in args.arms},
              'reasoning_effort': args.reasoning, 'profile': args.profile, 'in_memory_only': True, 'selections': [], 'results': []}
    selected_cases = [c for c in cases() if not args.cases or c.id in args.cases]
    if not selected_cases or args.cases and len(selected_cases) != len(set(args.cases)):
        raise ValueError('Unknown or duplicate case')
    original_selector = planner_module.WorkflowAuthoringPreselector
    frozen_selections = ({item['case']: item for item in json.loads(args.selection_report.read_text())['selections']}
                         if args.selection_report else {})
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=5)) as client:
            keys = {p: await manager.get_secret(secret_path='kv/data/providers/' + p, secret_key='api_key')
                    for p in ('groq', 'cerebras')}
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
                        except Exception as exc:
                            row.update(error_type=type(exc).__name__, error=str(exc)[:200])
                        finally:
                            row.update(wall_ms=round((time.perf_counter() - started) * 1000, 1),
                                first_header_ms=header_times[0] if header_times else None,
                                first_node_ms=node_times[0] if node_times else None,
                                validated_node_events=len(node_times), corrections=corrections,
                                provider_attempts=author.bridge.attempts if author.bridge else None)
                            await author.close()
                        report['results'].append(row)
                        write_report(args.output, report)
                        print(json.dumps({k: row.get(k) for k in ('case','arm','repeat','action','reason','graph_valid','intent_match','semantic_issues','wall_ms','first_header_ms','first_node_ms')}, separators=(',', ':')), flush=True)
    finally:
        planner_module.WorkflowAuthoringPreselector = original_selector
        await manager.aclose()
        write_report(args.output, report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-paid-dev-inference', action='store_true')
    parser.add_argument('--revision', required=True)
    parser.add_argument('--arms', nargs='+', choices=list(ARMS), default=['gemini','cerebras-oss-full','groq-oss-full'])
    parser.add_argument('--cases', nargs='+')
    parser.add_argument('--selection-report', type=Path, help='Reuse measured Jev decisions for an exactly paired author comparison')
    parser.add_argument('--repeats', type=int, default=1, choices=(1,2))
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
