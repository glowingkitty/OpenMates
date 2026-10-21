"""Provider-free qualification tooling tests for fresh daily-inspiration cohorts.

These exercise exclusion before source review, deterministic paired ordering,
pre-billing manifest guards and targeted recovery instrumentation. No provider,
account, public pool or shared runtime is contacted or mutated by these tests.
"""
# contract-test-file: infrastructure
import json
from types import SimpleNamespace

import pytest

from backend.scripts import benchmark_daily_inspiration_multilingual as benchmark


def options(root, **kwargs):
    values = dict(output_dir=str(root), languages=['de'], limit=1, phase_minutes=1,
                  exclude_source_root=None, expected_source_manifest=None)
    return SimpleNamespace(**(values | kwargs))


def write_source(directory, name, identity, status='complete'):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f'{name}.json').write_text(json.dumps({'status': status, 'identity': identity}))


def test_exclusions_accept_previous_root_or_sources_and_bind_identity_digest(tmp_path):
    sources = tmp_path / 'sources'
    write_source(sources, 'one', 'de:Papier_Recycling')
    write_source(sources, 'two', 'OldVideo001')
    write_source(sources, 'duplicate', 'OldVideo001')
    write_source(sources, 'shortfall', None, 'source_eligibility_shortfall')
    manifest = benchmark.exclusion_manifest(tmp_path)
    assert manifest == benchmark.exclusion_manifest(sources)
    assert manifest['source_ids'] == ['OldVideo001', 'de:Papier_Recycling']
    assert benchmark.source_identity_key('DE:Papier_Recycling') == benchmark.source_identity_key('de:Papier Recycling')
    assert benchmark.source_identity_key('OldVideo001') != benchmark.source_identity_key('oldvideo001')
    write_source(sources, 'three', 'NewVideo001')
    assert benchmark.exclusion_manifest(tmp_path)['sha256'] != manifest['sha256']


def test_explicit_missing_or_empty_exclusion_root_is_not_silently_ignored(tmp_path):
    with pytest.raises(ValueError, match='sources directory'):
        benchmark.exclusion_manifest(tmp_path)
    (tmp_path / 'sources').mkdir()
    with pytest.raises(ValueError, match='no completed'):
        benchmark.exclusion_manifest(tmp_path)


def test_fresh_topics_have_five_columns_and_order_is_reproducible_and_counterbalanced(tmp_path):
    assert benchmark.TOPICS['en'].split('|') == ['Aurora', 'Paper recycling', 'Seed dispersal', 'Arch (architecture)', 'Circadian rhythm']
    assert set(benchmark.TOPICS) == set(benchmark.LANGUAGES)
    assert all(len(topics.split('|')) == 5 for topics in benchmark.TOPICS.values())
    opts = options(tmp_path, languages=benchmark.LANGUAGES, limit=5)
    schedule = benchmark.arm_order_manifest(opts)
    assert schedule == benchmark.arm_order_manifest(opts)
    assert len(schedule) == 20 * 4  # Preserve four discovery batches per locale.
    assert {row['order'][0] for row in schedule.values()} == set(benchmark.ARMS)
    assert all(set(row['order']) == set(benchmark.ARMS) and len(row['seed']) == 64 for row in schedule.values())
    reordered = benchmark.arm_order_manifest(options(tmp_path, languages=list(reversed(benchmark.LANGUAGES)), limit=5))
    assert schedule == reordered


class Topic:
    def __init__(self, title):
        self.wiki_title = self.key = title
        self.disambiguation = False
        self.wikidata_id = None
        self.description = 'Public source'

    def model_dump(self):
        return {'wiki_title': self.wiki_title}


@pytest.mark.asyncio
async def test_exclusions_precede_source_gates_in_native_and_english_fallback_paths(monkeypatch, tmp_path):
    excluded = ['OldVideo001', 'de:Alte_Quelle']
    gate_ids, searches, summaries, enriched_inputs = [], [], [], []

    async def search_videos(**kwargs):
        searches.append(('video', kwargs['query']))
        identities = ['OldVideo001']
        if kwargs['query'].startswith('Aurora '):
            identities.append('NewVideo001')
        return {'results': [{'url': identity, 'title': 'Public video'} for identity in identities]}

    async def enrich(candidates, _manager):
        enriched_inputs.extend(row['youtube_id'] for row in candidates)
        return candidates

    async def image(_identity):
        return b'public pixels'

    async def search_wiki(query, **_kwargs):
        searches.append(('wiki', query))
        titles = ['Alte Quelle'] + (['Neue Quelle'] if query == 'Aurora' else [])
        return [Topic(title) for title in titles]

    async def validate(titles, **_kwargs):
        return [Topic(title) for title in titles]

    async def summary(title, **_kwargs):
        summaries.append(title)
        return {'title': title.replace('_', ' '), 'extract': 'Public educational source.'}

    async def gate(candidate, _manager, receipts, **_kwargs):
        identity = candidate.get('youtube_id') or candidate['wiki_title']
        gate_ids.append(identity)
        receipts.append({'identity': identity})
        return [{**candidate, 'editorial_category': 'science'}]

    monkeypatch.setattr(benchmark, 'generator', SimpleNamespace(
        get_search_params_for_language=lambda _language: {}, is_within_category_policy=lambda *_args: True), raising=False)
    monkeypatch.setattr(benchmark, 'video_processor', SimpleNamespace(
        search_videos=search_videos, _extract_youtube_id=lambda url: url,
        _enrich_with_youtube=enrich, _filter_made_for_kids=lambda rows, *_args: rows,
        _filter_by_hard_age_cutoff=lambda rows, *_args: rows,
        check_video_metadata=lambda *_args: False), raising=False)
    monkeypatch.setattr(benchmark, 'thumbnail_review', SimpleNamespace(
        thumbnail_url=lambda identity: identity, fetch_thumbnail=image), raising=False)
    monkeypatch.setattr(benchmark, 'wikipedia', SimpleNamespace(
        search_wikipedia_titles=search_wiki, batch_validate_topics=validate, fetch_page_summary=summary), raising=False)
    monkeypatch.setattr(benchmark, 'wiki_generator', SimpleNamespace(
        check_daily_inspiration_entry=lambda *_args, **_kwargs: {'verdict': 'PASS'}), raising=False)
    monkeypatch.setattr(benchmark, 'source_gate', gate)
    assert await benchmark.collect(options(tmp_path), tmp_path, None, excluded_ids=excluded)
    assert searches == [('video', 'Polarlicht educational independent creator'),
                        ('video', 'Aurora educational independent creator'),
                        ('wiki', 'Polarlicht'), ('wiki', 'Aurora')]
    assert enriched_inputs == ['NewVideo001']
    assert summaries == ['Neue_Quelle']
    assert gate_ids == ['NewVideo001', 'Neue Quelle']
    records = [json.loads(path.read_text()) for path in (tmp_path / 'sources').glob('*.json')]
    assert all(record['status'] == 'complete' for record in records)
    assert {record['identity'] for record in records} == {'NewVideo001', 'de:Neue Quelle'}


@pytest.mark.asyncio
async def test_wiki_redirect_to_excluded_canonical_identity_never_reaches_gate(monkeypatch):
    async def search(*_args, **_kwargs):
        return [Topic('Alias')]

    async def validate(*_args, **_kwargs):
        return [Topic('Alias')]

    async def summary(*_args, **_kwargs):
        return {'title': 'Alte Quelle', 'extract': 'Source content'}

    async def forbidden_gate(*_args, **_kwargs):
        raise AssertionError('excluded redirect reached native source gate')

    monkeypatch.setattr(benchmark, 'wikipedia', SimpleNamespace(
        search_wikipedia_titles=search, batch_validate_topics=validate, fetch_page_summary=summary), raising=False)
    monkeypatch.setattr(benchmark, 'source_gate', forbidden_gate)
    assert await benchmark.wiki_snapshot('query', 'de', None, {'de:alte quelle'}, []) is None


@pytest.mark.asyncio
async def test_resumed_completed_excluded_source_fails_before_retrieval(tmp_path):
    write_source(tmp_path / 'sources', 'de-video-0', 'OldVideo001')
    with pytest.raises(ValueError, match='Resumed source is excluded'):
        await benchmark.collect(options(tmp_path), tmp_path, None, excluded_ids=['OldVideo001'])


@pytest.mark.asyncio
async def test_candidate_manifest_mismatch_fails_before_vault_or_provider_setup(monkeypatch, tmp_path):
    for name in ('config', 'decisions', 'generator', 'video_processor', 'wiki_generator', 'writer', 'thumbnail_review', 'validator', 'media_coherence', 'llm_utils'):
        monkeypatch.setattr(benchmark, name, SimpleNamespace(__file__=benchmark.__file__, POLICY_VERSION='test'), raising=False)
    expected = tmp_path / 'expected.json'
    expected.write_text(json.dumps({'wrong.py': 'wrong-hash'}))

    def forbidden_manager():
        raise AssertionError('manifest mismatch reached credentials or native execution')

    monkeypatch.setattr(benchmark, 'SecretsManager', forbidden_manager, raising=False)
    with pytest.raises(ValueError, match='Runtime sources differ'):
        await benchmark.run(options(tmp_path / 'run', expected_source_manifest=str(expected)))


@pytest.mark.asyncio
async def test_changed_exclusion_manifest_prevents_resuming_old_writing_before_billing(monkeypatch, tmp_path):
    previous = tmp_path / 'previous'
    write_source(previous / 'sources', 'one', 'OldVideo001')
    output = tmp_path / 'run'
    output.mkdir()
    for name in ('config', 'decisions', 'generator', 'video_processor', 'wiki_generator', 'writer', 'thumbnail_review', 'validator', 'media_coherence', 'llm_utils'):
        monkeypatch.setattr(benchmark, name, SimpleNamespace(__file__=benchmark.__file__, POLICY_VERSION='test'), raising=False)

    def forbidden_manager():
        raise RuntimeError('prebilling checkpoint')

    monkeypatch.setattr(benchmark, 'SecretsManager', forbidden_manager, raising=False)
    opts = options(output, exclude_source_root=str(previous))
    # Persist a real current manifest, stopping before credentials/native calls.
    with pytest.raises(RuntimeError, match='prebilling checkpoint'):
        await benchmark.run(opts)
    before = json.loads((output / 'manifest.json').read_text())
    assert before['exclusions'] == benchmark.exclusion_manifest(previous)
    write_source(previous / 'sources', 'two', 'OtherOld001')
    with pytest.raises(ValueError, match='Output manifest differs'):
        await benchmark.run(opts)



@pytest.mark.asyncio
async def test_instrumentation_tracks_missing_row_retry_admissions_and_final_union(monkeypatch):
    from backend.apps.ai.daily_inspiration import writer
    monkeypatch.setattr(writer, 'RETRY_DELAY_SECONDS', 0)
    row = {'attempts': []}
    feedback = {}
    originals = {}

    class Card:
        phrase = 'Some public source copy. What happens next?'
        title = 'Public Source Card'
        assistant_response = 'One source fact. Another source fact. What happens next?'
        follow_up_suggestions = ['What is the source?', 'How does it work?', 'What happens next?']

        def __init__(self, identity):
            self.identity = identity

        def model_dump(self, **_kwargs):
            return {'source': self.identity}

    async def call(**kwargs):
        row['attempts'].append({'requested_model': kwargs['model_id']})
        return SimpleNamespace(error_message=None, arguments={'articles': [
            {'wiki_title': identity, 'phrase': Card.phrase, 'title': Card.title,
             'assistant_response': Card.assistant_response, 'follow_up_suggestions': Card.follow_up_suggestions}
            for identity in (('a',) if len(row['attempts']) == 1 else ('b',))]})

    async def accept(arguments):
        ids = [draft['wiki_title'] for draft in arguments['articles']]
        expected = ['a'] if len(row['attempts']) == 1 else ['b']
        assert ids == expected
        identity = 'a' if len(row['attempts']) == 1 else 'b'
        originals[identity] = Card(identity)
        if identity == 'a':
            feedback['b'] = ['copy:missing_or_shape']
        return [originals[identity]]

    cards = await benchmark.instrumented_write(writer.write_reviewed_cards,
        row=row, language='en', writer_call=call, accept=accept, count=2, collection='articles',
        source_ids=['b', 'a'], raw_source_id=lambda draft: draft['wiki_title'],
        card_source_id=lambda card: card.identity, rejection_feedback=feedback)
    assert cards == [originals['b'], originals['a']]
    assert row['eligible_source_ids'] == ['b', 'a']
    assert row['final_source_ids'] == ['b', 'a']
    assert row['final_source_owners'] == {'b': 1, 'a': 0}
    assert [attempt['admitted_source_ids'] for attempt in row['attempts']] == [['a'], ['b']]
    assert row['attempts'][0]['rejection_feedback'] == {'b': ['copy:missing_or_shape']}


def frozen_fixture(tmp_path):
    import hashlib
    original = tmp_path / 'original'
    output = tmp_path / 'new'
    manifest = {'languages': ['en'], 'limit': 1, 'policy_version': 'v6',
                'topics': {'en': ['Aurora']}, 'exclusions': {'source_ids': []},
                'source_sha256': {'gate.py': 'unchanged', 'writer.py': 'old'}}
    original.mkdir()
    (original / 'manifest.json').write_text(json.dumps(manifest))
    image = b'frozen thumbnail'
    image_sha = hashlib.sha256(image).hexdigest()
    video = {'status': 'complete', 'identity': 'FreshVideo1', 'english_retrieval_fallback': False,
             'image': {'path': 'thumbnails/video.jpg', 'sha256': image_sha}}
    inputs = {}
    for name, content in {'sources/en-video-0.json': json.dumps(video).encode(),
                          'sources/en-wiki-0.json': b'{"status":"source_eligibility_shortfall"}',
                          'thumbnails/video.jpg': image}.items():
        for directory in (original, output):
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        inputs[name] = hashlib.sha256(content).hexdigest()
    provenance = {'frozen_input_root': original.name,
                  'original_manifest_sha256': hashlib.sha256((original / 'manifest.json').read_bytes()).hexdigest(),
                  'inputs': inputs}
    path = output / 'frozen.json'
    path.write_text(json.dumps(provenance))
    current = json.loads(json.dumps(manifest))
    current['source_sha256']['writer.py'] = 'approved-format-fix'
    return output, path, current


def test_frozen_pin_preserves_complete_and_terminal_shortfalls_with_writer_only_change(tmp_path):
    output, provenance, manifest = frozen_fixture(tmp_path)
    result = benchmark.validate_frozen_sources(output, provenance, manifest)
    assert result['source_slots'] == 2
    assert result['eligible_sources'] == result['terminal_shortfalls'] == 1
    assert result['collection_bypassed'] is True
    assert len(result['provenance_sha256']) == 64
    manifest['source_sha256']['gate.py'] = 'changed'
    with pytest.raises(ValueError, match='gate application hashes changed'):
        benchmark.validate_frozen_sources(output, provenance, manifest)


@pytest.mark.parametrize('mutation', ['image', 'source', 'missing_slot', 'origin', 'context'])
def test_frozen_validation_rejects_changed_or_incomplete_inputs_before_billing(tmp_path, mutation):
    output, provenance, manifest = frozen_fixture(tmp_path)
    if mutation == 'image':
        (output / 'thumbnails/video.jpg').write_bytes(b'changed pixels')
    elif mutation == 'source':
        (output / 'sources/en-video-0.json').write_text('{}')
    elif mutation == 'missing_slot':
        (output / 'sources/en-wiki-0.json').unlink()
    elif mutation == 'origin':
        (tmp_path / 'original/manifest.json').write_text('{}')
    else:
        manifest['topics']['en'] = ['Different topic']
    with pytest.raises(ValueError, match='Frozen'):
        benchmark.validate_frozen_sources(output, provenance, manifest)


@pytest.mark.asyncio
@pytest.mark.parametrize('collect_only', [False, True])
async def test_frozen_run_never_collects_or_retries_terminal_shortfalls(monkeypatch, tmp_path, collect_only):
    output, provenance, manifest = frozen_fixture(tmp_path)
    before = (output / 'sources/en-wiki-0.json').read_bytes()

    async def forbidden_collect(*_args, **_kwargs):
        raise AssertionError('frozen run entered collection')

    class Manager:
        async def initialize(self):
            pass

        async def aclose(self):
            pass

    async def no_cards(*_args, **_kwargs):
        return []

    monkeypatch.setattr(benchmark, 'collect', forbidden_collect)
    monkeypatch.setattr(benchmark, 'build_manifest', lambda _options: dict(manifest))
    monkeypatch.setattr(benchmark, 'SecretsManager', Manager, raising=False)
    monkeypatch.setattr(benchmark, 'httpx', SimpleNamespace(AsyncClient=SimpleNamespace(send=None)), raising=False)
    monkeypatch.setattr(benchmark, 'AsyncModels', SimpleNamespace(generate_content=None), raising=False)
    monkeypatch.setattr(benchmark, 'decisions', SimpleNamespace(JevDecisionClient=None), raising=False)
    monkeypatch.setattr(benchmark, 'qualify_batch', no_cards)
    await benchmark.run(options(output, languages=['en'], frozen_source_manifest=str(provenance), collect_only=collect_only))
    assert (output / 'sources/en-wiki-0.json').read_bytes() == before
    saved = json.loads((output / 'manifest.json').read_text())
    assert saved['frozen_sources']['terminal_shortfalls'] == 1
    assert len(list((output / 'rows').glob('*.json'))) == (0 if collect_only else 2)


def test_jev_usage_counts_unique_responses_not_shared_transport_slices_or_locale_calls():
    success = {'call_id': 'one', 'request': {'questions': {'visual': {}}},
               'response': {'usage': {'input_tokens': 100, 'output_tokens': 2}}}
    locale = {'call_id': 'locale', 'request': {'questions': {'card_0_locale': {}}},
              'response': {'usage': {'input_tokens': 999, 'output_tokens': 8}}}
    row = {'jev': [success, success, locale,
                   {'call_id': 'two', 'response': {'usage': {'input_tokens': 200, 'output_tokens': 4}}}],
           'decision_accounting': [{'input_tokens': 10000, 'success': True},
                                   {'input_tokens': None, 'success': False},
                                   {'phase': 'locale_assessment', 'input_tokens': None, 'success': False}]}
    assert sum(item['input_tokens'] for item in benchmark.unique_jev_usage(row)) == 300
    assert benchmark.unknown_jev_attempts(row) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('arm', benchmark.ARMS)
async def test_single_model_diagnostic_override_is_one_attempt_and_restored(monkeypatch, tmp_path, arm):
    from backend.apps.ai.daily_inspiration import config, writer
    original_model, original_limit = writer.writer_model(), writer.MAX_WRITER_ATTEMPTS
    monkeypatch.setattr(benchmark, 'writer', writer, raising=False)
    monkeypatch.setattr(benchmark, 'config', config, raising=False)
    def namespace(names):
        return SimpleNamespace(**{name: None for name in names.split()})
    generator = namespace('find_video_candidates call_preprocessing_llm write_reviewed_cards')
    wiki = namespace('call_preprocessing_llm write_reviewed_cards search_wikipedia_titles review_candidates batch_validate_topics fetch_page_summary fetch_wikidata_entity')
    monkeypatch.setattr(benchmark, 'generator', generator, raising=False)
    monkeypatch.setattr(benchmark, 'wiki_generator', wiki, raising=False)
    monkeypatch.setattr(benchmark, 'thumbnail_review', namespace('fetch_thumbnail'), raising=False)

    async def provider_free(**kwargs):
        assert kwargs['temperature'] == benchmark.ARM_PROFILES[arm]['temperature']
        assert kwargs['max_output_tokens'] == 4096
        if arm == 'mercury3_only':
            assert kwargs['reasoning_effort'] == 'low'
        else:
            assert 'reasoning_effort' not in kwargs  # Preserve Gemini default thinking.
        return SimpleNamespace(model_dump=lambda **_kw: {})

    async def generate(*_args, **_kwargs):
        assert writer.writer_model() == benchmark.ARM_MODELS[arm]
        assert writer.MAX_WRITER_ATTEMPTS == 1
        request = {'model_id': writer.writer_model(), 'message_history': [],
                   'temperature': 1.0, 'max_output_tokens': 4096}
        await generator.call_preprocessing_llm(**request)
        with pytest.raises(ValueError, match='exactly one call'):
            await generator.call_preprocessing_llm(**request)
        return []

    generator.generate_inspirations = generate
    monkeypatch.setattr(benchmark, 'call_preprocessing_llm', provider_free, raising=False)
    row = {'attempts': []}
    token = benchmark.ACTIVE.set((row, tmp_path / 'case.json'))
    try:
        assert await benchmark.qualify_batch([{'query': 'public source'}], 'video', 'en', arm,
                                              row, None, tmp_path) == []
    finally:
        benchmark.ACTIVE.reset(token)
    assert len(row['attempts']) == 1
    assert row['attempts'][0]['requested_model'] == benchmark.ARM_MODELS[arm]
    assert row['attempts'][0]['request_profile']['temperature'] == benchmark.ARM_PROFILES[arm]['temperature']
    assert row['attempts'][0]['request_profile']['reasoning_effort'] == benchmark.ARM_PROFILES[arm]['reasoning_effort']
    assert writer.writer_model() == original_model == 'google/gemini-3.8-flash'
    assert writer.MAX_WRITER_ATTEMPTS == original_limit


@pytest.mark.asyncio
async def test_new_frozen_adoption_rejects_existing_writer_rows_before_billing(monkeypatch, tmp_path):
    output, provenance, manifest = frozen_fixture(tmp_path)
    (output / 'rows').mkdir()
    (output / 'rows/old.json').write_text('{"status":"complete"}')
    monkeypatch.setattr(benchmark, 'build_manifest', lambda _options: dict(manifest))
    with pytest.raises(ValueError, match='without previous writer rows'):
        await benchmark.run(options(output, languages=['en'], frozen_source_manifest=str(provenance)))
