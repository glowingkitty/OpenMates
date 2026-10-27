"""Opt-in full-refresh supplier-cost comparison; never invokes delivery/pool tasks.

Each setup runs in a fresh child process. Original modules must match the exact
pre-Jev revision; current native wrappers and tariffs are explicit replay inputs.
Default: one full 3-video/3-wiki/4-static refresh in English and Japanese per setup.
Live discovery is independently measured, not represented as identical sources.
Receipts retain public provider payloads only, without URLs' secret query values
or auth headers. Missing/failed usage is unknown spend, never a zero-cost claim.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import copy
from contextlib import ExitStack
from contextvars import ContextVar
import hashlib
import importlib
import importlib.util
import json
import logging
from pathlib import Path
import random
import subprocess
import sys
import time
from urllib.parse import urlsplit
from unittest.mock import patch

from backend.scripts.benchmark_daily_inspiration_multilingual import atomic_json, sanitized

BASELINE_REF = 'c94ebe85a14f87aa3223eacfe129aa85ec93d939'
PACKAGE = 'backend.apps.ai.daily_inspiration'
HISTORICAL_HASHES = {
    'backend/apps/ai/daily_inspiration/__init__.py': '19377068cfb0af9949f6e19e922f9ba628f25ef291960a90ae306e1e4cab7b69',
    'backend/apps/ai/daily_inspiration/category_age_policy.py': '1e46a2ae2a788cc3a2ea2ae382c279876eab29d2cc68b1b69c0df17763270035',
    'backend/apps/ai/daily_inspiration/content_filter.py': '3c00bc7095539526ec8da9cbb1742b05565011686168af745f1d207985ee28e7',
    'backend/apps/ai/daily_inspiration/feature_suggestions.py': 'e748d7f8d2394ebef5448815c739b6d7fa42f95849439316789303d101cfbebe',
    'backend/apps/ai/daily_inspiration/generator.py': '924824db98c764159ed6fba0b53595c21d00bd334fe7c7e5445b0ba3484027d5',
    'backend/apps/ai/daily_inspiration/media_coherence.py': '8c7403d87cbfe30106dac6b6a5bb5d9d03289ae65a58404e06ed5f6018bd9260',
    'backend/apps/ai/daily_inspiration/schemas.py': '306c9a670bbc962d0c2546dc6d7555e0f3b7cbeb19d9d0232d8a3c3cc4436db7',
    'backend/apps/ai/daily_inspiration/validator.py': 'b6565571e40ee005653390595de5a9514cb8fc47d93058b1ca6fbc3a63132c2a',
    'backend/apps/ai/daily_inspiration/video_processor.py': '7d0cbaaf573cb356af4849a7bf92072449c303073788986e37baab63251bd2c0',
    'backend/apps/ai/daily_inspiration/wiki_generator.py': 'dc3fc3a0b17e842992890b8860d2de2d3b51c3e890e7bd1ff314699ea869b0c1',
    'backend/apps/ai/daily_inspiration/wiki_suggestions.py': '57817709f906796141e7425448afeb26c6a57e5542bf9315522ffc86f02f142d',
    'backend/shared/config/blocked_content_keywords.yml': '75e72dbba14810198fde7865983934f1a69b03dc7f4074e493739578f7ccd936',
}
INFERENCE_ENDPOINTS = {
    'api.mistral.ai': {'/v1/chat/completions'},
    'api.inceptionlabs.ai': {'/v1/chat/completions'},
    'api.typesafe.ai': {'/v1/systemone'},
    'openrouter.ai': {'/api/v1/chat/completions', '/api/alpha/decisions'},
}
PUBLIC_HOSTS = {'api.search.brave.com', 'www.googleapis.com', 'i.ytimg.com', 'www.wikidata.org'}
ACTIVE = ContextVar('full_refresh_cost_receipt', default=None)
CALL = ContextVar('full_refresh_logical_call', default=None)
TOPICS = {'en': ['Volcano', 'Pollination', 'Solar eclipse'],
          'de': ['Vulkan', 'Bestäubung', 'Sonnenfinsternis'],
          'ja': ['火山', '受粉', '日食']}
CURRENT_SOURCE_PATHS = [f'backend/apps/ai/daily_inspiration/{name}.py' for name in (
    'decisions', 'writer', 'generator', 'wiki_generator', 'video_processor',
    'validator', 'thumbnail_review', 'config', 'media_coherence', 'writer_prompt',
)] + ['backend/apps/ai/utils/llm_utils.py',
      'backend/core/api/app/tasks/default_inspiration_tasks.py',
      'backend/core/api/app/tasks/daily_inspiration_tasks.py',
      'backend/core/api/app/routes/default_inspirations.py']


def pool_rows_from_cards(cards, language):
    """Mirror the public add_to_pool payload with an explicit metadata allowlist."""
    rows = []
    wiki_fields = ('source_language', 'title', 'wiki_title', 'description', 'thumbnail_url',
                   'wikidata_id', 'extract')
    for index, card in enumerate(cards):
        kind = card.get('content_type')
        if kind not in {'video', 'wiki'}:
            continue
        video, wiki = card.get('video') or {}, card.get('wiki') or {}
        row = {key: copy.deepcopy(card.get(key)) for key in (
            'phrase', 'title', 'assistant_response', 'category', 'content_type',
            'follow_up_suggestions', 'generated_at')}
        row.update(id=f'public-cost-{language}-{index}', language=card.get('language') or language,
                   youtube_id=video.get('youtube_id'),
                   wiki_metadata={key: copy.deepcopy(wiki[key]) for key in wiki_fields if key in wiki} if wiki else None)
        for source, target in (
            ('title', 'video_title'), ('description', 'video_description'),
            ('thumbnail_url', 'video_thumbnail_url'), ('channel_name', 'video_channel_name'),
            ('view_count', 'video_view_count'), ('duration_seconds', 'video_duration_seconds'),
            ('published_at', 'video_published_at'),
        ):
            row[target] = copy.deepcopy(video.get(source))
        rows.append(row)
    return rows


def extract_pool_reviewer(source_path, review_candidates, editorial_review_digest,
                          canonical_wiki_review_source):
    """Compile the exact function alone; never execute the task module/imports."""
    source_path = Path(source_path)
    source = source_path.read_text()
    parsed = ast.parse(source)
    nodes = [node for node in parsed.body if isinstance(node, ast.AsyncFunctionDef)
             and node.name == '_review_pool_entries']
    if len(nodes) != 1 or nodes[0].decorator_list:
        raise ValueError('Expected one undecorated current pool review function')
    node = nodes[0]
    namespace = {'json': json, 'review_candidates': review_candidates,
                 'editorial_review_digest': editorial_review_digest,
                 'canonical_wiki_review_source': canonical_wiki_review_source}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source_path), 'exec'), namespace)
    return namespace[node.name], {
        'source_file_sha256': hashlib.sha256(source_path.read_bytes()).hexdigest(),
        'function_ast_sha256': hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest(),
        'function_source_sha256': hashlib.sha256(ast.get_source_segment(source, node).encode()).hexdigest(),
        'scope': 'Exact current _review_pool_entries only; freshly generated public video/wiki sample; no task initialization, DB access, selection or writes.',
    }


def current_source_preflight(reviewed_manifest=None):
    root = Path(__file__).resolve().parents[2]
    hashes = {Path(relative).name: hashlib.sha256((root / relative).read_bytes()).hexdigest()
              for relative in CURRENT_SOURCE_PATHS}
    review = {'matched_keys': [], 'unreviewed_keys': sorted(hashes)}
    if reviewed_manifest:
        path = Path(reviewed_manifest)
        document = json.loads(path.read_text())
        expected = document.get('source_sha256', document.get('current_source_sha256', document))
        if not isinstance(expected, dict):
            raise ValueError('Reviewed source manifest must contain a hash mapping')
        normalized = {Path(key).name: value for key, value in expected.items()}
        matched = sorted(hashes.keys() & normalized.keys())
        if not matched:
            raise ValueError('Reviewed manifest contains no recognized application source hashes')
        for key in matched:
            if hashes[key] != normalized[key]:
                raise ValueError(f'Reviewed source hash differs before native calls: {key}')
        review = {'manifest_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                  'matched_keys': matched, 'unreviewed_keys': sorted(hashes.keys() - set(matched))}
    return {'current_source_sha256': hashes, 'reviewed_source_comparison': review}


def verify_historical(root):
    root = Path(root).resolve()
    for relative, expected in HISTORICAL_HASHES.items():
        path = root / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Historical source does not match {BASELINE_REF}: {relative}')
    return root


def mode_output_name(mode, historical_deadline_seconds=None):
    if mode == 'original' and historical_deadline_seconds is not None:
        return f'original-deadline-{historical_deadline_seconds}s'
    return mode


def install_deadline_overrides(stack, mode, seconds, llm_utils):
    if mode == 'original' and seconds is not None:
        # Supplementary timing sensitivity only; leave model/content/role and
        # retry/fallback policy unchanged. ExitStack restores both globals.
        stack.enter_context(patch.object(llm_utils, 'PREPROCESSING_TIMEOUT_SECONDS', seconds))
        stack.enter_context(patch.object(llm_utils, 'PREPROCESSING_TOTAL_TIMEOUT_SECONDS', seconds))


def install_historical(root):
    """Replace the package search path, never mix old and current daily modules."""
    root = verify_historical(root)
    if any(name == PACKAGE or name.startswith(PACKAGE + '.') for name in sys.modules):
        raise RuntimeError('Daily package already loaded; use a fresh original subprocess')
    parent = importlib.import_module('backend.apps.ai')
    directory = root / 'backend/apps/ai/daily_inspiration'
    spec = importlib.util.spec_from_file_location(PACKAGE, directory / '__init__.py',
                                                submodule_search_locations=[str(directory)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    setattr(parent, 'daily_inspiration', module)
    spec.loader.exec_module(module)


def inference_request(host, path):
    return path in INFERENCE_ENDPOINTS.get(host, set()) or (
        host in {'generativelanguage.googleapis.com', 'aiplatform.googleapis.com'}
        or host.endswith('-aiplatform.googleapis.com')) and (
            path.endswith(':generateContent') or path.endswith(':streamGenerateContent'))


def assert_allowed_request(method, host, path, vault_host):
    """Fail before transmitting private API reads or any non-inference mutation."""
    if inference_request(host, path) and method == 'POST':
        return
    public = host in PUBLIC_HOSTS or host.endswith('.wikipedia.org')
    if method in {'GET', 'HEAD'} and (public or (host == vault_host and path.startswith('/v1/'))):
        return
    # OAuth exchange is needed only for the current Google provider, not product data.
    if method == 'POST' and host == 'oauth2.googleapis.com' and path == '/token':
        return
    raise RuntimeError(f'Benchmark blocked non-provider/private request: {method} {host}{path}')


def event(kind, data):
    active = ACTIVE.get()
    if active:
        row, path = active
        row.setdefault(kind, []).append(sanitized(data))
        atomic_json(path, row)


def native_jev_usage(row):
    """One ledger entry per actual native transport, not shared-list slices.

    Equal payloads can be separately billed retries, so do not hash/deduplicate
    identical responses. Async HTTP capture already appends each send exactly once.
    """
    ledger = []
    for index, item in enumerate(row.get('native_http', [])):
        if item.get('host') != 'api.typesafe.ai' and not (
            item.get('host') == 'openrouter.ai' and item.get('path') == '/api/alpha/decisions'
        ):
            continue
        response = item.get('response') or {}
        usage = response.get('usage') or {}
        inputs = usage.get('input_tokens', usage.get('prompt_tokens'))
        outputs = usage.get('output_tokens', usage.get('completion_tokens'))
        valid_input = isinstance(inputs, (int, float)) and not isinstance(inputs, bool) and inputs >= 0
        cost = None
        source = None
        if item.get('host') == 'api.typesafe.ai' and valid_input:
            cost, source = inputs * .042 / 1_000_000, 'typesafe_input_$0.042_per_million_output_free'
        elif item.get('host') == 'openrouter.ai':
            reported = usage.get('cost')
            if isinstance(reported, (int, float)) and not isinstance(reported, bool) and reported >= 0:
                cost, source = reported, 'openrouter_reported_usage_cost_usd'
        ledger.append({'native_http_index': index, 'host': item.get('host'),
            'status': item.get('status'), 'error': item.get('error'),
            'model': response.get('model'), 'input_tokens': inputs, 'output_tokens': outputs,
            'supplier_cost_usd': cost, 'supplier_cost_complete': cost is not None,
            'supplier_cost_source': source})
    return ledger


async def recorded_semantic_call(original, kwargs, row, flush, context):
    """Record the dedicated review seam without adding a writer attempt."""
    attempts = row.setdefault('semantic_review_attempts', [])
    identity = 'semantic:' + str(len(attempts))
    entry = {'call_id': identity, 'requested_model': kwargs.get('model_id'),
             'request': kwargs.get('message_history'), 'tool': kwargs.get('tool_definition')}
    attempts.append(entry)
    token = context.set(identity)
    stamp = time.monotonic()
    try:
        result = await original(**kwargs)
        entry['result'] = {'arguments': result.arguments,
            'error_message_present': bool(result.error_message), 'usage_telemetry': result.usage_telemetry}
        return result
    except BaseException as error:
        entry['error'] = type(error).__name__
        raise
    finally:
        entry['seconds'] = time.monotonic() - stamp
        flush()
        context.reset(token)


def semantic_native_usage(row):
    """Raw native Google review usage once; facade events are not extra charges.

    Introductory standard Gemini 3.8 prices verified 2026-10-21 against the
    catalog and https://ai.google.dev/gemini-api/docs/pricing (through 2026-12-31).
    Absent cache telemetry gives an uncached upper bound, never exact cost.
    """
    ledger, seen, captured = [], set(), set()
    # SDK and HTTP may capture the same physical response; response IDs join them.
    for native in [*row.get('google_sdk', []), *row.get('native_http', [])]:
        identity = native.get('logical_call')
        if not isinstance(identity, str) or not identity.startswith('semantic:'):
            continue
        response = native.get('response') or {}
        usage = response.get('usage_metadata', response.get('usageMetadata')) or {}
        response_id = response.get('response_id', response.get('responseId'))
        if not usage:
            continue
        key = (identity, response_id) if response_id else None
        if key is not None and key in seen:
            continue
        if key is not None:
            seen.add(key)
        captured.add(identity)
        model = response.get('model_version', response.get('modelVersion')) or native.get('requested_model')
        inputs = usage.get('prompt_token_count', usage.get('promptTokenCount'))
        cached = usage.get('cached_content_token_count', usage.get('cachedContentTokenCount'))
        candidates = usage.get('candidates_token_count', usage.get('candidatesTokenCount'))
        thoughts = usage.get('thoughts_token_count', usage.get('thoughtsTokenCount')) or 0
        valid = (str(model).startswith('gemini-3.8-flash') and isinstance(inputs, int)
                 and isinstance(candidates, int) and (cached is None or isinstance(cached, int)))
        upper = ((inputs - (cached or 0)) * .75 + (cached or 0) * .075
                 + (candidates + thoughts) * 3.75) / 1e6 if valid else None
        ledger.append({'call_id': identity, 'response_id': response_id, 'model': model,
            'input_tokens': inputs, 'cached_input_tokens': cached,
            'output_tokens_including_thoughts': candidates + thoughts if isinstance(candidates, int) else None,
            'supplier_cost_usd': upper if cached is not None else None,
            'supplier_cost_upper_bound_usd': upper,
            'supplier_cost_complete': valid and cached is not None,
            'supplier_upper_bound_complete': valid,
            'tariff': 'Gemini3.8_standard_intro_2026-12-31_input0.75_cached0.075_output3.75_perM'})
    for attempt in row.get('semantic_review_attempts', []):
        if attempt['call_id'] not in captured:
            ledger.append({'call_id': attempt['call_id'], 'model': attempt['requested_model'],
                'supplier_cost_usd': None, 'supplier_cost_upper_bound_usd': None,
                'supplier_cost_complete': False, 'supplier_upper_bound_complete': False})
    return ledger


def native_writer_usage(row):
    """Price captured writer responses once, retaining canceled/failed attempts.

    Semantic-review ledgers above remain readable for historical diagnostics;
    current production has no semantic reviewer. Cached-token absence is an
    uncached estimate, not exact spend. Rates are the frozen 2026-10-21 catalog.
    """
    rates = {'mercury-3': (.10, .01, .35), 'mistral-small-latest': (.15, .015, .60),
             'gemini-3.5-flash-lite': (.30, .03, 2.50), 'gemini-3.8-flash': (.75, .075, 3.75)}
    calls = row.get('calls', row.get('attempts', []))
    ledger, seen, captured = [], set(), set()
    for native in [*row.get('google_sdk', []), *row.get('native_http', [])]:
        identity = native.get('logical_call')
        if not isinstance(identity, int) or isinstance(identity, bool) or not 0 <= identity < len(calls):
            continue
        response = native.get('response') or {}
        model = response.get('model_version', response.get('modelVersion', response.get('model')))
        rate = next((value for key, value in rates.items() if str(model).startswith(key)), None)
        usage = response.get('usage_metadata', response.get('usageMetadata', response.get('usage'))) or {}
        if not rate or not usage:
            continue
        response_id = response.get('response_id', response.get('responseId', response.get('id')))
        key = (identity, response_id) if response_id else None
        if key is not None and key in seen:
            continue
        if key is not None:
            seen.add(key)
        google = str(model).startswith('gemini-')
        inputs = usage.get('prompt_token_count', usage.get('promptTokenCount')) if google else usage.get('prompt_tokens')
        outputs = usage.get('candidates_token_count', usage.get('candidatesTokenCount')) if google else usage.get('completion_tokens')
        thoughts = (usage.get('thoughts_token_count', usage.get('thoughtsTokenCount')) or 0) if google else 0
        cached = (usage.get('cached_content_token_count', usage.get('cachedContentTokenCount')) if google
                  else (usage.get('prompt_tokens_details') or {}).get('cached_tokens'))
        valid = all(isinstance(value, int) and not isinstance(value, bool) and value >= 0
                    for value in (inputs, outputs, thoughts))
        valid = valid and (cached is None or isinstance(cached, int) and 0 <= cached <= inputs)
        estimate = ((inputs - (cached or 0)) * rate[0] + (cached or 0) * rate[1]
                    + (outputs + thoughts) * rate[2]) / 1e6 if valid else None
        captured.add(identity)
        ledger.append({'logical_call': identity, 'model_id': calls[identity].get('requested_model'),
            'observed_model': model, 'response_id': response_id,
            'input_tokens': inputs, 'cache_read_input_tokens': cached,
            'output_tokens': outputs + thoughts if valid else None,
            'output_reasoning_tokens': thoughts if google else (usage.get('completion_tokens_details') or {}).get('reasoning_tokens'),
            'supplier_cost_usd': estimate, 'supplier_cost_upper_bound_usd': estimate,
            'supplier_cost_complete': valid and cached is not None,
            'supplier_upper_bound_complete': valid,
            'cost_basis': 'Once-only native response; missing cache counter priced uncached. Google thoughts included once; Mercury completion already includes reasoning.'})
    fallback_events = [entry for entry in row.get('facade_attempt_usage', [])
                       if not str(entry.get('logical_call', '')).startswith('semantic:')]
    facade = {}
    for index, entry in enumerate(fallback_events):
        facade.setdefault(entry.get('logical_call', index), []).append(entry)
    for index, attempt in enumerate(calls):
        if index not in captured:
            events = facade.get(index) or [(attempt.get('result') or {}).get('usage_telemetry') or {}]
            for telemetry in events:
                ledger.append({**telemetry, 'logical_call': index,
                    'model_id': attempt.get('requested_model'),
                    'supplier_cost_complete': bool(telemetry.get('supplier_cost_complete')),
                    'cost_basis': 'Facade fallback: no priced native response captured; absent usage remains unknown.'})
    return ledger


def summarize_row(row):
    usage = native_writer_usage(row)
    row['native_writer_usage'] = usage
    semantic = semantic_native_usage(row)
    row['native_semantic_review_usage'] = semantic
    jev = native_jev_usage(row)
    row['native_jev_usage'] = jev
    native = row.get('native_http', [])
    searches = [item for item in row.get('retrieval_http', [])
                if item['host'] == 'api.search.brave.com' and item['status'] < 400]
    known = sum(item.get('supplier_cost_usd') or 0 for item in [*usage, *jev, *semantic])
    # HTTP and SDK captures may overlap. They prove attempts/model identities; their
    # usage must not be added again to the facade/Jev supplier accounting ledger.
    row['cost'] = {
        'known_inference_supplier_usd': known,
        'semantic_review_attempts': len(row.get('semantic_review_attempts', [])),
        'known_semantic_review_supplier_usd': sum(item.get('supplier_cost_usd') or 0 for item in semantic),
        'semantic_review_supplier_upper_bound_usd': sum(item.get('supplier_cost_upper_bound_usd') or 0 for item in semantic),
        'semantic_review_cost_complete': all(item.get('supplier_cost_complete') for item in semantic),
        'inference_supplier_upper_bound_usd': sum(item.get('supplier_cost_upper_bound_usd', item.get('supplier_cost_usd')) or 0 for item in [*usage, *jev, *semantic]),
        'successful_brave_http_requests': len(searches),
        'brave_gross_catalog_usd': len(searches) * .005,
        'known_inference_plus_search_gross_usd': known + len(searches) * .005,
        'facade_attempt_usage_records': len(row.get('facade_attempt_usage', [])),
        'native_writer_usage_records': len(usage), 'jev_attempts': len(jev),
        'raw_jev_accounting_rows_not_summed': len(row.get('jev_accounting', [])),
        'known_jev_supplier_usd': sum(item.get('supplier_cost_usd') or 0 for item in jev),
        'jev_accounting_method': 'One captured native HTTP send per ledger entry; raw shared accounting slices retained but never summed because concurrent image reviews can duplicate them.',
        'native_http_attempts': len(native),
        'failed_native_http_attempts': sum(item.get('status', 0) >= 400 or 'error' in item for item in native),
        'accounted_inference_complete': bool(usage or jev or semantic) and all(item.get('supplier_cost_complete') for item in [*usage, *jev, *semantic]),
        'all_transport_spend_complete': False,
        'limits': 'Captured native/telemetry estimate before credits; missing cache counters priced uncached. SDK retries/timeouts can lack usage, so captured-response prices are not total-spend bounds. Native captures are not double-counted. No invoice, infra or YouTube/Wikimedia monetary cost is available. Brave $5/1000 successful HTTP requests is a gross catalog estimate, not verified billable net requests.',
    }
    admitted = row.get('counts', {}).get('video', 0) + row.get('counts', {}).get('wiki', 0)
    row['cost']['known_gross_per_admitted_generated_card_usd'] = (known + len(searches) * .005) / admitted if admitted else None
    row['cost']['known_gross_per_delivered_slot_usd'] = (known + len(searches) * .005) / len(row.get('items', [])) if row.get('items') else None
    row['logical_facade_calls'] = len(row.get('calls', []))
    row['logical_search_calls'] = sum(item['operation'] == 'video_search' for item in row.get('retrieval_calls', []))
    row['observed_models'] = sorted({str(item['response'].get('model') or item['response'].get('model_version') or item['response'].get('modelVersion'))
        for item in [*native, *row.get('google_sdk', [])] if isinstance(item.get('response'), dict)
        and any(item['response'].get(key) for key in ('model', 'model_version', 'modelVersion'))})


async def worker(options):
    logging.disable(logging.CRITICAL)  # Receipts carry errors, not arbitrary SDK log strings.
    source_preflight = current_source_preflight(options.reviewed_source_manifest)
    output_mode = mode_output_name(options.mode, options.historical_deadline_seconds)
    if options.mode == 'original':
        install_historical(options.historical_source_dir)
    import httpx
    from google.genai.models import AsyncModels
    from backend.apps.ai.utils import llm_utils
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    from backend.shared.providers.typesafe import client as jev_client

    modules = {name: importlib.import_module(PACKAGE + '.' + name)
               for name in ('generator', 'wiki_generator', 'video_processor', 'feature_suggestions')}
    if options.mode == 'original':
        modules['validator'] = importlib.import_module(PACKAGE + '.validator')
        expected_root = Path(options.historical_source_dir).resolve()
        for name, module in list(sys.modules.items()):
            if name == PACKAGE or name.startswith(PACKAGE + '.'):
                if not Path(module.__file__).resolve().is_relative_to(expected_root):
                    raise RuntimeError('Historical package mixed with current modules')
        if modules['generator'].INSPIRATION_MODEL_ID != 'mistral/mistral-small-latest':
            raise ValueError('Unexpected historical model')
    root = Path(options.output_dir).resolve()
    manager = SecretsManager()
    vault_host = urlsplit(manager.vault_url or '').hostname
    original_send = httpx.AsyncClient.send
    original_google = AsyncModels.generate_content
    original_call = llm_utils.call_preprocessing_llm
    original_telemetry = llm_utils._auxiliary_usage_telemetry
    original_jev = jev_client.JevDecisionClient

    async def send(client, request, *args, **kwargs):
        host, path = request.url.host, request.url.path
        assert_allowed_request(request.method, host, path, vault_host)
        inference = inference_request(host, path)
        source = host in PUBLIC_HOSTS or host.endswith('.wikipedia.org')
        stamp = time.monotonic()
        entry = {'host': host, 'path': path, 'method': request.method,
                 'logical_call': CALL.get(), 'started_at': time.time()}
        if inference:
            try:
                entry['request'] = json.loads(request.content)
            except (ValueError, httpx.RequestNotRead):
                entry['request_unavailable'] = True
        elif source:
            entry['public_params'] = {key: value for key, value in request.url.params.items()
                                      if key.lower() in {'q', 'query', 'id', 'ids', 'titles', 'language', 'search_lang', 'country', 'count', 'limit'}}
        try:
            response = await original_send(client, request, *args, **kwargs)
            if inference or source:
                await response.aread()
                entry['status'] = response.status_code
                try:
                    entry['response'] = response.json()
                except ValueError:
                    entry['response_bytes'] = len(response.content)
                    entry['response_sha256'] = hashlib.sha256(response.content).hexdigest()
            return response
        except BaseException as error:
            entry['error'] = type(error).__name__
            raise
        finally:
            entry['seconds'] = time.monotonic() - stamp
            if inference or source:
                event('native_http' if inference else 'retrieval_http', entry)

    async def google(client, **kwargs):
        stamp = time.monotonic()
        try:
            result = await original_google(client, **kwargs)
            event('google_sdk', {'logical_call': CALL.get(), 'requested_model': kwargs.get('model'),
                'response': result.model_dump(mode='json', exclude_none=True), 'seconds': time.monotonic() - stamp})
            return result
        except BaseException as error:
            event('google_sdk', {'logical_call': CALL.get(), 'requested_model': kwargs.get('model'),
                                'error': type(error).__name__, 'seconds': time.monotonic() - stamp})
            raise

    def telemetry(*args, **kwargs):
        result = original_telemetry(*args, **kwargs)
        event('facade_attempt_usage', {'logical_call': CALL.get(),
            'logical_model_id': kwargs.get('logical_model_id'),
            'server_model_id': kwargs.get('server_model_id'), 'route_id': kwargs.get('route_id'), **result})
        return result

    async def call(**kwargs):
        row = ACTIVE.get()[0]
        number = len(row.setdefault('calls', []))
        token = CALL.set(number)
        entry = {'requested_model': kwargs.get('model_id'), 'task_id': kwargs.get('task_id'),
                 'request': kwargs.get('message_history'), 'tool': kwargs.get('tool_definition')}
        row['calls'].append(entry)
        stamp = time.monotonic()
        try:
            result = await original_call(**kwargs)
            entry['result'] = {'arguments': result.arguments,
                'error_message_present': bool(result.error_message), 'usage_telemetry': result.usage_telemetry}
            return result
        except BaseException as error:
            entry['error'] = type(error).__name__
            raise
        finally:
            entry['seconds'] = time.monotonic() - stamp
            atomic_json(ACTIVE.get()[1], row)
            CALL.reset(token)

    class RecordedJev:
        def __init__(self, **kwargs):
            self.accounting = []
            self.client = original_jev(**{**kwargs, 'accounting': self.accounting})

        async def evaluate(self, **kwargs):
            offset = len(self.accounting)
            try:
                result = await self.client.evaluate(**kwargs)
                event('jev', {'request': kwargs, 'response': result.model_dump(mode='json')})
                return result
            finally:
                for item in self.accounting[offset:]:
                    event('jev_accounting', item)

    async def refresh(language, row):
        task = f'public-cost-benchmark-{options.mode}-{language}'
        random.seed(1531)
        for kind, coroutine in (
            ('video', modules['generator'].generate_inspirations('public-cost-benchmark', 3, TOPICS[language], manager, language=language, task_id=task)),
            ('wiki', None),
        ):
            # Construct wiki coroutine only after video finishes so cancellation
            # cannot leave an unawaited coroutine or reorder the historical path.
            if kind == 'wiki':
                coroutine = modules['wiki_generator'].generate_wiki_inspirations(TOPICS[language], manager, count=3, language=language, task_id=task + '_wiki')
            cards = await coroutine
            row.setdefault('counts', {})[kind] = len(cards)
            row.setdefault('items', []).extend(card.model_dump(mode='json') for card in cards)
            atomic_json(ACTIVE.get()[1], row)

    async def measure_pool_review(language, personal):
        if options.mode != 'current' or not options.measure_pool_review:
            return
        path = root / 'current-pool-review' / f'{language}.json'
        if path.exists():
            if json.loads(path.read_text()).get('status') == 'complete':
                return
            history = root / 'history' / 'current-pool-review' / f'{language}-{time.time_ns()}.json'
            history.parent.mkdir(parents=True, exist_ok=True)
            path.replace(history)
        decisions = importlib.import_module(PACKAGE + '.decisions')
        coherence = importlib.import_module(PACKAGE + '.media_coherence')
        source_path = Path(__file__).resolve().parents[2] / 'backend/core/api/app/tasks/default_inspiration_tasks.py'
        review, provenance = extract_pool_reviewer(source_path, decisions.review_candidates,
                                                  coherence.editorial_review_digest,
                                                  coherence.canonical_wiki_review_source)
        entries = pool_rows_from_cards(personal['items'], language)
        row = {'mode': 'current-pool-review', 'language': language, 'status': 'running',
               **source_preflight, **provenance, 'input_count': len(entries), 'input_records': entries,
               'personal_receipt_sha256': hashlib.sha256((root / 'current' / f'{language}.json').read_bytes()).hexdigest(),
               'historical_equivalent_inference_usd': 0,
               'cost_scope': 'Separate public-pool revalidation sample; never charged into personal refresh rows. Actual shared spend depends on pool volume, not user count.'}
        token = ACTIVE.set((row, path))
        stamp = time.monotonic()
        try:
            output = await asyncio.wait_for(review(entries, manager,
                f'public-cost-pool-review-{language}'), timeout=options.pool_review_max_seconds)
            row.update(status='complete', output_records=output, output_count=len(output))
        except BaseException as error:
            row.update(status='failed', error=type(error).__name__)
        finally:
            row['seconds'] = time.monotonic() - stamp
            summarize_row(row)
            row['cost']['known_inference_per_input_entry_usd'] = row['cost']['known_inference_supplier_usd'] / len(entries) if entries else None
            row['cost']['known_inference_per_retained_entry_usd'] = row['cost']['known_inference_supplier_usd'] / row['output_count'] if row.get('output_count') else None
            pool_usage = [*row['native_jev_usage'], *row['native_semantic_review_usage']]
            row['cost']['accounted_inference_complete'] = all(item.get('supplier_cost_complete') for item in pool_usage) and (not entries or bool(pool_usage))
            atomic_json(path, row)
            ACTIVE.reset(token)

    try:
        with ExitStack() as stack:
            install_deadline_overrides(stack, options.mode, options.historical_deadline_seconds, llm_utils)
            stack.enter_context(patch.object(httpx.AsyncClient, 'send', send))
            stack.enter_context(patch.object(AsyncModels, 'generate_content', google))
            stack.enter_context(patch.object(llm_utils, '_auxiliary_usage_telemetry', telemetry))
            for module in modules.values():
                if hasattr(module, 'call_preprocessing_llm'):
                    stack.enter_context(patch.object(module, 'call_preprocessing_llm', call))
            if options.mode == 'current':
                decisions = importlib.import_module(PACKAGE + '.decisions')
                stack.enter_context(patch.object(decisions, 'JevDecisionClient', RecordedJev))
            for module_name, operation, name in (
                ('video_processor', 'video_search', 'search_videos'),
                ('video_processor', 'youtube_enrichment', '_enrich_with_youtube'),
                ('wiki_generator', 'wiki_title_lookup', 'batch_validate_topics'),
                ('wiki_generator', 'wiki_summary', 'fetch_page_summary'),
                ('wiki_generator', 'wikidata_entity', 'fetch_wikidata_entity'),
                ('wiki_generator', 'wiki_search', 'search_wikipedia_titles'),
            ):
                module = modules[module_name]
                if not hasattr(module, name):
                    continue
                original_io = getattr(module, name)

                def recorded_io(original_io=original_io, operation=operation):
                    async def invoke(*args, **kwargs):
                        entry = {'operation': operation, 'language': kwargs.get('language'),
                                 'query': kwargs.get('query')}
                        stamp = time.monotonic()
                        try:
                            return await original_io(*args, **kwargs)
                        except BaseException as error:
                            entry['error'] = type(error).__name__
                            raise
                        finally:
                            entry['seconds'] = time.monotonic() - stamp
                            event('retrieval_calls', entry)
                    return invoke

                stack.enter_context(patch.object(module, name, recorded_io()))
            await manager.initialize()
            for language in options.languages:
                path = root / output_mode / f'{language}.json'
                if path.exists():
                    prior = json.loads(path.read_text())
                    if prior.get('status') == 'complete':
                        await measure_pool_review(language, prior)
                        continue
                    history = root / 'history' / output_mode / f'{language}-{time.time_ns()}.json'
                    history.parent.mkdir(parents=True, exist_ok=True)
                    path.replace(history)
                row = {'mode': output_mode, 'language': language, 'status': 'running', 'items': [],
                       'accounting_version': 'sole-writer-native-usage-v1',
                       **source_preflight,
                       'historical_declared_deadline_seconds': options.historical_deadline_seconds if options.mode == 'original' else None,
                       'deadline_scope': ('Supplementary original architecture with declared extended caller deadlines; not exact historical timing.'
                           if options.mode == 'original' and options.historical_deadline_seconds is not None else 'Unmodified caller deadlines.'),
                       'effective_preprocessing_deadlines': {'request_seconds': llm_utils.PREPROCESSING_TIMEOUT_SECONDS,
                                                           'total_seconds': llm_utils.PREPROCESSING_TOTAL_TIMEOUT_SECONDS},
                       'historical_ref': BASELINE_REF if options.mode == 'original' else None,
                       'source_sha256': {name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                                         for name, module in modules.items()},
                       'requested_counts': {'video': 3, 'wiki': 3, 'feature': 4},
                       'runtime_tariff_sha256': {relative: hashlib.sha256((Path(__file__).resolve().parents[2] / relative).read_bytes()).hexdigest()
                           for relative in ('backend/providers/mistral.yml', 'backend/providers/google.yml',
                                            'backend/providers/inception.yml', 'backend/providers/brave.yml')},
                       'runtime_wrapper_sha256': {'llm_utils': hashlib.sha256(Path(llm_utils.__file__).read_bytes()).hexdigest(),
                                                  'jev_client': hashlib.sha256(Path(jev_client.__file__).read_bytes()).hexdigest()}}
                row['daily_package_sha256'] = {name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                    for name, module in list(sys.modules.items()) if (name == PACKAGE or name.startswith(PACKAGE + '.')) and getattr(module, '__file__', None)}
                token = ACTIVE.set((row, path))
                stamp = time.monotonic()
                try:
                    await asyncio.wait_for(refresh(language, row), timeout=options.max_seconds)
                    row['status'] = 'complete'
                except BaseException as error:
                    row.update(status='interrupted' if isinstance(error, asyncio.CancelledError) else 'failed', error=type(error).__name__)
                finally:
                    tips = modules['feature_suggestions'].build_feature_inspirations(4, language=language)
                    row['items'].extend(item.model_dump(mode='json') for item in tips)
                    row.setdefault('counts', {})['feature'] = len(tips)
                    row['seconds'] = time.monotonic() - stamp
                    row['source_ids'] = [item.get('video', {}).get('youtube_id') if item.get('video') else
                        item.get('wiki', {}).get('wiki_title') for item in row['items'] if item.get('video') or item.get('wiki')]
                    row['full_ten_card_refresh'] = row['counts'] == {'video': 3, 'wiki': 3, 'feature': 4}
                    summarize_row(row)
                    atomic_json(path, row)
                    ACTIVE.reset(token)
                await measure_pool_review(language, row)
    finally:
        await manager.aclose()


def child_command(options, mode):
    if mode not in {'original', 'current'}:
        raise ValueError('Each worker has exactly one mode')
    command = [sys.executable, '-m', 'backend.scripts.benchmark_daily_inspiration_costs',
            '--execute', '--worker', '--mode', mode, '--output-dir', str(Path(options.output_dir).resolve()),
            '--historical-source-dir', str(Path(options.historical_source_dir).resolve()),
            '--max-seconds', str(options.max_seconds), '--languages', *options.languages]
    if getattr(options, 'reviewed_source_manifest', None):
        command.extend(['--reviewed-source-manifest', str(Path(options.reviewed_source_manifest).resolve())])
    command.extend(['--pool-review-max-seconds', str(getattr(options, 'pool_review_max_seconds', 180))])
    if getattr(options, 'historical_deadline_seconds', None) is not None:
        command.extend(['--historical-deadline-seconds', str(options.historical_deadline_seconds)])
    if not getattr(options, 'measure_pool_review', True):
        command.append('--no-measure-pool-review')
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--historical-source-dir', required=True)
    parser.add_argument('--reviewed-source-manifest', help='Optional source_sha256 mapping; compare recognized current application files before native calls')
    parser.add_argument('--mode', choices=('both', 'original', 'current'), default='both')
    parser.add_argument('--historical-deadline-seconds', type=int, choices=(30,),
                        help='Opt-in original-only timing supplement: keep architecture unchanged but extend request and total caller deadlines to 30s; separate variant output')
    parser.add_argument('--languages', choices=TOPICS, nargs='+', default=['en', 'ja'])
    parser.add_argument('--max-seconds', type=int, choices=range(30, 901), default=600)
    parser.add_argument('--measure-pool-review', action=argparse.BooleanOptionalAction, default=True,
                        help='Separately revalidate only new current public cards; no pool DB/task access')
    parser.add_argument('--pool-review-max-seconds', type=int, choices=range(30, 301), default=180)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    options = parser.parse_args()
    if options.worker and options.mode == 'both':
        parser.error('A worker cannot load both setups')
    modes = ['original', 'current'] if options.mode == 'both' else [options.mode]
    if not options.execute:
        print(json.dumps({'execute': False, 'refreshes_per_setup': len(options.languages),
                          'setups': modes, 'historical_ref': BASELINE_REF,
                          'output_variants': [mode_output_name(mode, options.historical_deadline_seconds) for mode in modes],
                          'separate_current_pool_review': options.measure_pool_review,
                          'historical_staging_files': list(HISTORICAL_HASHES),
                          'commands': [child_command(options, mode) for mode in modes]}))
        return
    verify_historical(options.historical_source_dir)
    source_preflight = current_source_preflight(options.reviewed_source_manifest)
    if options.worker:
        asyncio.run(worker(options))
        return
    root = Path(options.output_dir).resolve()
    manifest = {'historical_ref': BASELINE_REF, 'historical_hashes': HISTORICAL_HASHES,
                **source_preflight,
                'languages': options.languages, 'modes': modes, 'max_seconds': options.max_seconds,
                'historical_declared_deadline_seconds': options.historical_deadline_seconds,
                'measure_pool_review': options.measure_pool_review, 'pool_review_max_seconds': options.pool_review_max_seconds,
                'benchmark_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'scope': 'Fresh live discovery per setup; current wrappers/tariffs; direct generation only; no account or delivery writes.'}
    if (root / 'manifest.json').exists() and json.loads((root / 'manifest.json').read_text()) != manifest:
        raise ValueError('Existing output manifest differs; use a fresh output directory')
    atomic_json(root / 'manifest.json', manifest)
    results = []
    for mode in modes:
        try:
            extra = options.pool_review_max_seconds if mode == 'current' and options.measure_pool_review else 0
            result = subprocess.run(child_command(options, mode), timeout=min(1800, len(options.languages) * (options.max_seconds + extra + 30)), check=False)
            results.append({'mode': mode, 'exit_code': result.returncode})
        except subprocess.TimeoutExpired:
            results.append({'mode': mode, 'error': 'worker_deadline'})
    atomic_json(root / 'processes.json', results)
    rows = [json.loads(path.read_text()) for mode in modes
            for path in (root / mode_output_name(mode, options.historical_deadline_seconds)).glob('*.json')]
    pool_rows = [json.loads(path.read_text()) for path in (root / 'current-pool-review').glob('*.json')]
    atomic_json(root / 'summary.json', {'processes': results, 'refreshes': [
        {key: row.get(key) for key in ('mode', 'language', 'status', 'counts', 'full_ten_card_refresh', 'logical_facade_calls', 'logical_search_calls', 'observed_models', 'seconds', 'cost', 'source_ids')}
        for row in rows], 'separate_current_pool_review_samples': [
            {key: row.get(key) for key in ('language', 'status', 'input_count', 'output_count', 'seconds', 'cost', 'scope')}
            for row in pool_rows],
        'limits': 'Independent live retrieval is not a matched-source quality comparison. Pool review is a separate small fresh-card sample, not a full scheduled pool scan or per-user shared-default charge. Include archived history receipts when totaling interrupted/retried experiment spend.'})


if __name__ == '__main__':
    main()
