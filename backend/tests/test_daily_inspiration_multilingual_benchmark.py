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
async def test_instrumentation_tracks_targeted_attempt_admissions_and_final_union(monkeypatch):
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
            for identity in ('a', 'b')]})

    async def accept(arguments):
        ids = [draft['wiki_title'] for draft in arguments['articles']]
        expected = ['a', 'b'] if len(row['attempts']) == 1 else ['b']
        assert ids == expected
        identity = 'a' if len(row['attempts']) == 1 else 'b'
        originals[identity] = Card(identity)
        if identity == 'a':
            feedback['b'] = ['phrase.grounding:unsupported']
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
    assert row['attempts'][0]['rejection_feedback'] == {'b': ['phrase.grounding:unsupported']}
