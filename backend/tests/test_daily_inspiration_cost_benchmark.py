"""Offline safety and provenance checks for the opt-in historical cost tool."""
# contract-test-file: infrastructure
import hashlib
import asyncio
from contextlib import ExitStack
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys

import pytest

from backend.scripts import benchmark_daily_inspiration_costs as benchmark


def test_write_guard_allows_only_inference_and_read_only_public_or_vault():
    allow = benchmark.assert_allowed_request
    allow('POST', 'api.mistral.ai', '/v1/chat/completions', 'vault')
    allow('POST', 'api.typesafe.ai', '/v1/systemone', 'vault')
    allow('GET', 'ja.wikipedia.org', '/api/rest_v1/page/summary/受粉', 'vault')
    allow('GET', 'vault', '/v1/kv/data/providers/mistral', 'vault')
    for method, host, path in [
        ('POST', 'directus', '/items/daily_inspiration_pool'),
        ('GET', 'directus', '/items/users'),
        ('POST', 'api.dev.openmates.org', '/v1/daily-inspirations'),
        ('DELETE', 'vault', '/v1/kv/data/providers/mistral'),
        ('POST', 'api.mistral.ai', '/v1/files'),
        ('GET', 'attacker.wikipedia.org.evil.example', '/leak'),
    ]:
        with pytest.raises(RuntimeError, match='blocked'):
            allow(method, host, path, 'vault')


def test_historical_identity_rejects_even_single_byte_change(tmp_path, monkeypatch):
    relative = 'backend/apps/ai/daily_inspiration/__init__.py'
    content = b'# historical fixture\n'
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    monkeypatch.setattr(benchmark, 'HISTORICAL_HASHES', {relative: hashlib.sha256(content).hexdigest()})
    assert benchmark.verify_historical(tmp_path) == tmp_path
    path.write_bytes(content + b' ')
    with pytest.raises(ValueError, match='does not match'):
        benchmark.verify_historical(tmp_path)


def test_historical_package_cannot_replace_loaded_current_package(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, 'verify_historical', lambda root: Path(root))
    monkeypatch.setitem(sys.modules, benchmark.PACKAGE, SimpleNamespace())
    with pytest.raises(RuntimeError, match='fresh original subprocess'):
        benchmark.install_historical(tmp_path)


def test_modes_always_use_separate_fresh_process_commands(tmp_path):
    options = SimpleNamespace(output_dir=tmp_path / 'receipts', historical_source_dir=tmp_path / 'source',
                              max_seconds=600, languages=['en', 'ja'])
    original = benchmark.child_command(options, 'original')
    current = benchmark.child_command(options, 'current')
    assert original[original.index('--mode') + 1] == 'original'
    assert current[current.index('--mode') + 1] == 'current'
    assert '--worker' in original and '--worker' in current
    assert original[0] == sys.executable
    assert '--historical-deadline-seconds' not in original
    assert benchmark.mode_output_name('original') == 'original'
    options.historical_deadline_seconds = 30
    supplement = benchmark.child_command(options, 'original')
    assert supplement[supplement.index('--historical-deadline-seconds') + 1] == '30'
    assert benchmark.mode_output_name('original', 30) == 'original-deadline-30s'
    assert benchmark.mode_output_name('current', 30) == 'current'
    utility = SimpleNamespace(PREPROCESSING_TIMEOUT_SECONDS=5, PREPROCESSING_TOTAL_TIMEOUT_SECONDS=12)
    with ExitStack() as stack:
        benchmark.install_deadline_overrides(stack, 'original', None, utility)
        assert utility.PREPROCESSING_TIMEOUT_SECONDS == 5
    with ExitStack() as stack:
        benchmark.install_deadline_overrides(stack, 'current', 30, utility)
        assert utility.PREPROCESSING_TIMEOUT_SECONDS == 5
    with ExitStack() as stack:
        benchmark.install_deadline_overrides(stack, 'original', 30, utility)
        assert utility.PREPROCESSING_TIMEOUT_SECONDS == utility.PREPROCESSING_TOTAL_TIMEOUT_SECONDS == 30
    assert utility.PREPROCESSING_TIMEOUT_SECONDS == 5
    assert utility.PREPROCESSING_TOTAL_TIMEOUT_SECONDS == 12
    with pytest.raises(ValueError, match='exactly one mode'):
        benchmark.child_command(options, 'both')


def test_dry_run_needs_no_provider_packages_credentials_or_staged_sources(tmp_path):
    result = subprocess.run([sys.executable, '-m', 'backend.scripts.benchmark_daily_inspiration_costs',
        '--output-dir', str(tmp_path / 'unused'), '--historical-source-dir', str(tmp_path / 'missing')],
        capture_output=True, text=True, check=True)
    plan = json.loads(result.stdout)
    assert plan['execute'] is False
    assert plan['setups'] == ['original', 'current']
    assert plan['refreshes_per_setup'] == 2
    assert not (tmp_path / 'unused').exists()


def test_cost_accounting_does_not_double_count_native_usage_or_hide_shortfalls():
    row = {'counts': {'video': 1, 'wiki': 0, 'feature': 4}, 'items': [{}] * 5,
        'calls': [{}, {}],
        'facade_attempt_usage': [{'supplier_cost_usd': .01, 'supplier_cost_complete': True}],
        'jev_accounting': [{'input_tokens': 1000}, {'input_tokens': 1000}, {'input_tokens': 2000}],
        'native_http': [{'status': 200, 'response': {'usage': {'cost': 999}}}, {'error': 'TimeoutError'},
                        {'host': 'api.typesafe.ai', 'status': 200, 'response': {'model': 'jev-1.14.0', 'usage': {'input_tokens': 1000, 'output_tokens': 50}}},
                        {'host': 'api.typesafe.ai', 'status': 200, 'response': {'model': 'jev-1.14.0', 'usage': {'input_tokens': 2000, 'output_tokens': 50}}}],
        'retrieval_http': [{'host': 'api.search.brave.com', 'status': 200},
                           {'host': 'api.search.brave.com', 'status': 429}]}
    benchmark.summarize_row(row)
    assert row['cost']['known_inference_supplier_usd'] == pytest.approx(.010126)
    assert row['cost']['known_inference_plus_search_gross_usd'] == pytest.approx(.015126)
    assert row['cost']['known_gross_per_admitted_generated_card_usd'] == pytest.approx(.015126)
    assert row['cost']['jev_attempts'] == 2
    assert row['cost']['raw_jev_accounting_rows_not_summed'] == 3
    assert row['cost']['all_transport_spend_complete'] is False
    assert row['cost']['failed_native_http_attempts'] == 1


def test_reviewed_current_hash_mismatch_fails_before_provider_imports(tmp_path):
    manifest = tmp_path / 'reviewed.json'
    actual = benchmark.current_source_preflight()['current_source_sha256']
    assert {'decisions.py', 'writer.py', 'generator.py', 'wiki_generator.py',
            'video_processor.py', 'validator.py', 'thumbnail_review.py', 'config.py',
            'llm_utils.py', 'media_coherence.py'} <= actual.keys()
    assert 'semantic_review.py' not in actual
    manifest.write_text(json.dumps({'source_sha256': actual}))
    verified = benchmark.current_source_preflight(manifest)
    assert verified['reviewed_source_comparison']['unreviewed_keys'] == []
    manifest.write_text(json.dumps({'source_sha256': {**actual, 'validator.py': '0' * 64}}))
    with pytest.raises(ValueError, match='validator.py'):
        benchmark.current_source_preflight(manifest)


def test_semantic_native_usage_prices_all_paid_responses_once_separate_from_writer():
    def response(identity, cache):
        usage = {'prompt_token_count': 1000, 'candidates_token_count': 100,
                 'thoughts_token_count': 20}
        if cache is not None:
            usage['cached_content_token_count'] = cache
        return {'logical_call': 'semantic:0', 'response': {'response_id': identity,
                'model_version': 'gemini-3.8-flash', 'usage_metadata': usage}}
    paid = response('paid-parse-failure', 400)
    uncached_upper = response('paid-retry', None)
    row = {'calls': [{'requested_model': 'inception/mercury-3'}],
        'semantic_review_attempts': [{'call_id': 'semantic:0', 'requested_model': 'google/gemini-3.8-flash'}],
        'google_sdk': [paid, uncached_upper], 'native_http': [paid],
        'facade_attempt_usage': [{'logical_call': 'semantic:0', 'supplier_cost_usd': 99},
                                 {'logical_call': 0, 'supplier_cost_usd': .01,
                                  'supplier_cost_complete': True}]}
    benchmark.summarize_row(row)
    ledger = row['native_semantic_review_usage']
    assert len(ledger) == 2  # SDK/HTTP overlap is one send; retry is still paid.
    assert ledger[0]['supplier_cost_usd'] == pytest.approx(.00093)
    assert ledger[1]['supplier_cost_usd'] is None
    assert ledger[1]['supplier_cost_upper_bound_usd'] == pytest.approx(.0012)
    assert row['cost']['known_inference_supplier_usd'] == pytest.approx(.01093)
    assert row['cost']['semantic_review_supplier_upper_bound_usd'] == pytest.approx(.00213)
    assert row['logical_facade_calls'] == 1 and row['cost']['semantic_review_attempts'] == 1
    assert not row['cost']['semantic_review_cost_complete']


def test_sole_writer_native_ledger_includes_thoughts_paid_parse_errors_and_cancels():
    google = {'logical_call': 0, 'response': {'response_id': 'google-one',
        'model_version': 'gemini-3.8-flash', 'usage_metadata': {
            'prompt_token_count': 1000, 'cached_content_token_count': 400,
            'candidates_token_count': 100, 'thoughts_token_count': 20}}}
    mercury = {'logical_call': 1, 'host': 'api.inceptionlabs.ai', 'status': 200,
        'response': {'id': 'paid-length', 'model': 'mercury-3', 'usage': {
            'prompt_tokens': 1000, 'prompt_tokens_details': {'cached_tokens': 100},
            'completion_tokens': 200, 'completion_tokens_details': {'reasoning_tokens': 190}},
            'choices': [{'finish_reason': 'length'}]}}
    row = {'calls': [{'requested_model': 'google/gemini-3.8-flash'},
                     {'requested_model': 'inception/mercury-3', 'error': 'parse_failure'},
                     {'requested_model': 'google/gemini-3.8-flash', 'error': 'CancelledError'}],
           'google_sdk': [google], 'native_http': [google, mercury],
           'facade_attempt_usage': [{'logical_call': 0, 'supplier_cost_usd': 99}]}
    ledger = benchmark.native_writer_usage(row)
    assert len(ledger) == 3
    assert ledger[0]['supplier_cost_usd'] == pytest.approx(.00093)
    assert ledger[0]['output_tokens'] == 120
    assert ledger[1]['supplier_cost_usd'] == pytest.approx(.000161)
    assert ledger[1]['output_tokens'] == 200  # Reasoning is already included.
    assert ledger[2].get('supplier_cost_usd') is None
    assert not ledger[2]['supplier_cost_complete']
    assert benchmark.native_writer_usage({'calls': [], 'semantic_review_attempts': []}) == []


def test_gemini38_writer_without_cache_counter_is_an_uncached_estimate():
    row = {'attempts': [{'requested_model': 'google/gemini-3.8-flash'}],
        'native_http': [{'logical_call': 0, 'transport': 'google_sdk', 'response': {
            'response_id': 'uncached-unknown', 'model_version': 'gemini-3.8-flash',
            'usage_metadata': {'prompt_token_count': 1000, 'candidates_token_count': 100,
                               'thoughts_token_count': 20}}}]}
    usage = benchmark.native_writer_usage(row)[0]
    assert usage['supplier_cost_upper_bound_usd'] == pytest.approx(.0012)
    assert not usage['supplier_cost_complete']
    assert usage['supplier_upper_bound_complete']


@pytest.mark.asyncio
async def test_semantic_seam_records_cancellation_without_writer_attempt_or_lost_context():
    from contextvars import ContextVar
    context = ContextVar('offline-semantic-test', default=None)
    row = {'calls': [{'writer': True}]}
    flushes = []

    async def canceled(**_kwargs):
        assert context.get() == 'semantic:0'
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await benchmark.recorded_semantic_call(canceled, {'model_id': 'google/gemini-3.8-flash'},
            row, lambda: flushes.append(True), context)
    assert context.get() is None and flushes == [True]
    assert len(row['calls']) == 1 and len(row['semantic_review_attempts']) == 1
    assert row['semantic_review_attempts'][0]['error'] == 'CancelledError'
    assert benchmark.semantic_native_usage(row)[0]['supplier_cost_upper_bound_usd'] is None


def test_pool_conversion_preserves_public_source_edition_and_strips_private_fields():
    cards = [
        {'content_type': 'wiki', 'title': 'Public translated title', 'phrase': 'Public phrase',
         'assistant_response': 'Public intro', 'follow_up_suggestions': ['One', 'Two', 'Three'],
         'user_id': 'private-user', 'email': 'private@example.invalid',
         'wiki': {'wiki_title': '受粉', 'title': '受粉', 'source_language': 'ja', 'extract': 'Actual public summary',
                  'description': 'Actual description', 'wikidata_id': 'Q134624', 'secret': 'private-nested'}},
        {'content_type': 'video', 'title': 'Card title', 'language': 'en',
         'video': {'youtube_id': 'AbCdEfGhI12', 'title': 'Public video', 'description': 'Public evidence',
                   'thumbnail_url': 'https://i.ytimg.com/vi/AbCdEfGhI12/hqdefault.jpg',
                   'published_at': '2026-01-01T00:00:00Z', 'user_id': 'private-nested'}},
        {'content_type': 'feature', 'title': 'Static tip'},
    ]
    rows = benchmark.pool_rows_from_cards(cards, 'en')
    assert len(rows) == 2
    assert rows[0]['language'] == 'en'
    assert rows[0]['wiki_metadata']['source_language'] == 'ja'
    assert rows[0]['wiki_metadata']['wiki_title'] == '受粉'
    assert rows[0]['follow_up_suggestions'] == ['One', 'Two', 'Three']
    assert rows[1]['video_description'] == 'Public evidence'
    assert rows[1]['video_thumbnail_url'] == cards[1]['video']['thumbnail_url']
    assert 'private' not in json.dumps(rows)
    rows[0]['follow_up_suggestions'].append('Mutation')
    assert len(cards[0]['follow_up_suggestions']) == 3


def test_pool_function_extraction_executes_exact_function_without_task_module_imports():
    from backend.apps.ai.daily_inspiration.media_coherence import canonical_wiki_review_source

    source_path = Path(benchmark.__file__).resolve().parents[2] / 'backend/core/api/app/tasks/default_inspiration_tasks.py'
    existing_task_module = sys.modules.get('backend.core.api.app.tasks.default_inspiration_tasks')
    calls = []

    async def review(candidates, manager, **kwargs):
        calls.append((candidates, manager, kwargs))
        return [{**row, 'thumbnail_url': 'https://i.ytimg.com/vi/AbCdEfGhI12/hqdefault.jpg'} for row in candidates]

    function, provenance = benchmark.extract_pool_reviewer(source_path, review,
        lambda _entry: 'actual-digest-stub', canonical_wiki_review_source)
    rows = benchmark.pool_rows_from_cards([
        {'content_type': 'video', 'title': 'Public card',
         'video': {'youtube_id': 'AbCdEfGhI12', 'title': 'Exact source', 'description': 'Exact evidence'}},
        {'content_type': 'wiki', 'title': 'Translated card title', 'language': 'en',
         'wiki': {'title': '受粉', 'wiki_title': '受粉', 'source_language': 'ja', 'extract': 'Actual fetched source passage'}},
        {'content_type': 'wiki', 'title': 'Generated copy must not replace missing source',
         'wiki': {'wiki_title': 'Unproven_article', 'extract': 'No verified source edition or source title'}},
    ], 'en')
    manager = object()
    output = asyncio.run(function(rows, manager, 'offline-pool-tool-test'))
    assert calls[0][0][0]['description'] == 'Exact evidence'
    assert calls[0][0][0]['record'] == rows[0]
    assert len(calls[0][0]) == 2  # Missing canonical evidence is withheld before review.
    assert calls[0][0][1]['title'] == '受粉'
    assert calls[0][0][1]['wiki_title'] == '受粉'
    assert calls[0][0][1]['extract'] == 'Actual fetched source passage'
    assert calls[0][0][1]['card_title'] == 'Translated card title'
    assert calls[0][0][1]['record']['wiki_metadata']['source_language'] == 'ja'
    assert calls[0][1] is manager
    assert len(output) == 2
    assert output[0]['editorial_review'] == 'actual-digest-stub'
    assert provenance['source_file_sha256'] == hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert len(provenance['function_ast_sha256']) == 64
    assert sys.modules.get('backend.core.api.app.tasks.default_inspiration_tasks') is existing_task_module
