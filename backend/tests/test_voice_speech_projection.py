"""Voice calls project canonical rich text into immutable low-latency speech."""
import asyncio

from backend.apps.ai.assistant_speech.projection import project_streaming_speech_segment
from backend.apps.ai.assistant_speech.streaming import ImmutableSpeechBoundaryTracker


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response
def test_voice_keeps_prose_and_link_labels_without_visual_announcements():
    rich = ('**Here is the answer.** Read [the guide](https://example.org/private).\n\n'
            '```json\n{"type":"app_skill_use","embed_id":"private"}\n```\n'
            '| Name | Secret |\n| --- | --- |\n| A | B |\n'
            'Next, look here. `private_code` embed:private-ref https://example.org/raw')
    assert project_streaming_speech_segment(rich, voice_mode=True) == (
        'prose_paragraph', 'Here is the answer. Read the guide. Next, look here.')
    for structured in ('```python\nprint("secret")\n```', '| A | B |\n| --- | --- |', '{"secret":1}'):
        assert project_streaming_speech_segment(structured, voice_mode=True) is None
    # Existing independent message playback retains its deterministic summaries.
    assert project_streaming_speech_segment('```python\npass\n```') == (
        'code_summary', 'A code example is available.')


def tracker_for(dispatched, monkeypatch, *, voice_mode=True, **callbacks):
    monkeypatch.setattr('backend.apps.ai.assistant_speech.streaming._token_secret', lambda: b'test-only')
    async def dispatch(segment):
        dispatched.append(segment)
    return ImmutableSpeechBoundaryTracker(metadata={
        'chat_id': 'chat', 'assistant_message_id': 'assistant', 'source_version': 1,
        'language': 'en', 'voice_mode': voice_mode,
    }, dispatch_speech=dispatch, **callbacks)


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response
def test_sentence_handoff_precedes_paragraph_and_flushes_final_without_repeats(monkeypatch):
    dispatched, finalized = [], []
    async def exercise():
        async def finalize(payload):
            finalized.append(payload)
        tracker = tracker_for(dispatched, monkeypatch, finalize_speech=finalize)
        assert not tracker.has_new_boundary('First sentence.')
        assert tracker.has_new_boundary('First sentence. Next')
        tracker.observe('First sentence. Next')
        await tracker.wait_for_handoff()
        assert [s['speakable_text'] for s in dispatched] == ['First sentence.']
        tracker.observe('First sentence. Next')
        tracker.observe('First sentence. Next sentence. Last words', is_final=True)
        await tracker.wait_for_handoff()
        tracker.observe('First sentence. Next sentence. Last words', is_final=True)
        await tracker.wait_for_handoff()
    asyncio.run(exercise())
    assert [s['speakable_text'] for s in dispatched] == ['First sentence.', 'Next sentence.', 'Last words']
    assert [s['sequence'] for s in dispatched] == [0, 1, 2]
    assert len({s['segment_id'] for s in dispatched}) == 3
    assert len(finalized) == 1 and len(finalized[0]['segment_ids']) == 3


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response
def test_delta_splits_inside_links_code_and_tables_never_leak_or_mutate(monkeypatch):
    dispatched = []
    async def exercise():
        tracker = tracker_for(dispatched, monkeypatch)
        snapshots = [
            'Read [a useful. ',
            'Read [a useful. guide](https://example.org). Then ',
            'Read [a useful. guide](https://example.org). Then ```json\n{"secret": 1. ',
            'Read [a useful. guide](https://example.org). Then ```json\n{"secret": 1. }\n```\n| A | B |\n',
        ]
        for snapshot in snapshots:
            tracker.observe(snapshot)
            await tracker.wait_for_handoff()
        tracker.observe(snapshots[-1] + 'Continue now.', is_final=True)
        await tracker.wait_for_handoff()
    asyncio.run(exercise())
    assert [s['speakable_text'] for s in dispatched] == ['Read a useful. guide.', 'Then', 'Continue now.']
    assert all('secret' not in s['speakable_text'] for s in dispatched)


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response
def test_rewritten_spoken_prefix_is_never_replayed_or_replaced(monkeypatch):
    dispatched, invalidated = [], []
    async def exercise():
        async def invalidate(segment):
            invalidated.append(segment)
        tracker = tracker_for(dispatched, monkeypatch, invalidate_speech=invalidate)
        tracker.observe('Original sentence. Tail')
        await tracker.wait_for_handoff()
        assert not tracker.has_new_boundary('Revised sentence. Extra sentence. ')
        tracker.observe('Revised sentence. Extra sentence. ', is_final=True)
        await tracker.wait_for_handoff()
    asyncio.run(exercise())
    assert [s['speakable_text'] for s in dispatched] == ['Original sentence.']
    assert not invalidated


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response
def test_long_unpunctuated_voice_prose_dispatches_bounded_clauses(monkeypatch):
    dispatched = []
    text = ' '.join(['useful'] * 100)
    async def exercise():
        tracker = tracker_for(dispatched, monkeypatch)
        tracker.observe(text)
        await tracker.wait_for_handoff()
        assert dispatched and max(len(s['speakable_text']) for s in dispatched) <= 246
        tracker.observe(text, is_final=True)
        await tracker.wait_for_handoff()
    asyncio.run(exercise())
    assert ' '.join(s['speakable_text'] for s in dispatched) == text


# contract-test: supporting surface=rest_api assertions=video-call.audio.localized-waiting,video-call.audio.spoken-rich-response
def test_waiting_prelude_keeps_response_sequence_zero_and_final_manifest(monkeypatch):
    dispatched, manifests = [], []
    async def exercise():
        async def finalize(payload):
            manifests.append(payload)
        tracker = tracker_for(dispatched, monkeypatch, finalize_speech=finalize)
        tracker.dispatch_projected_segment(sequence=-1, kind='waiting_confirmation', speakable_text='Einen Moment.')
        assert not tracker.has_response_segments
        tracker.observe('**Useful answer.** More')
        assert tracker.has_response_segments
        tracker.observe('**Useful answer.** More', is_final=True)
        await tracker.wait_for_handoff()
    asyncio.run(exercise())
    assert [s['sequence'] for s in dispatched] == [-1, 0, 1]
    assert dispatched[0]['playback_class'] == 'passive_prelude'
    assert dispatched[1]['speakable_text'] == 'Useful answer.'
    assert manifests[0]['segment_ids'] == [s['segment_id'] for s in dispatched]


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response
def test_regular_message_playback_still_waits_for_paragraph_boundaries(monkeypatch):
    dispatched = []
    async def exercise():
        tracker = tracker_for(dispatched, monkeypatch, voice_mode=False)
        assert not tracker.has_new_boundary('First sentence. More')
        tracker.observe('First sentence. More')
        await tracker.wait_for_handoff()
        assert not dispatched
        tracker.observe('First sentence. More', is_final=True)
        await tracker.wait_for_handoff()
    asyncio.run(exercise())
    assert [s['speakable_text'] for s in dispatched] == ['First sentence. More']


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response,video-call.privacy
def test_hidden_delivery_cues_are_allowlisted_and_never_extracted_from_rich_literals():
    from backend.apps.ai.assistant_speech.projection import project_final_voice_clauses
    rich = ('<!-- voice:curious -->Read [the guide](https://example.org). '
            '<!-- voice:short pause -->It is useful. '
            '`<!-- voice:excited -->secret` '
            '```text\n<!-- voice:laughs -->private\n``` '
            '<!-- voice:gunshot -->Continue.')
    assert project_streaming_speech_segment(rich, voice_mode=True) == (
        'prose_paragraph', '[curious] Read the guide. [short pause] It is useful. Continue.')
    assert project_streaming_speech_segment('<!-- voice:laughs -->', voice_mode=True) is None
    assert project_streaming_speech_segment('<!-- voice:cur', voice_mode=True) is None
    assert project_streaming_speech_segment('Plain. <!-- voice:curious -->') == ('prose_paragraph', 'Plain.')
    assert project_streaming_speech_segment(
        'Read [<!-- voice:excited -->the guide](https://example.org).', voice_mode=True
    ) == ('prose_paragraph', 'Read the guide.')
    assert project_streaming_speech_segment(
        '````text\n```\n<!-- voice:excited -->private\n````', voice_mode=True
    ) is None
    # A cue on its own line must remain attached to the following clause.
    assert project_final_voice_clauses('<!-- voice:thoughtful -->\nUseful answer.') == ['[thoughtful] Useful answer.']


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response,video-call.privacy
def test_split_delivery_cue_keeps_source_offsets_and_replay_identity(monkeypatch):
    from backend.apps.ai.assistant_speech.projection import project_final_voice_clauses
    from backend.apps.ai.assistant_speech.streaming import _speech_source_identity
    dispatched = []
    final = '<!-- voice:curious -->First answer. <!-- voice:short pause -->Next answer.'
    async def exercise():
        tracker = tracker_for(dispatched, monkeypatch)
        for snapshot in ('<!-- voice:cur', '<!-- voice:curious -->First answer. ', final):
            tracker.observe(snapshot)
            await tracker.wait_for_handoff()
        tracker.observe(final, is_final=True)
        await tracker.wait_for_handoff()
    asyncio.run(exercise())
    clauses = project_final_voice_clauses(final)
    assert [s['speakable_text'] for s in dispatched] == clauses == [
        '[curious] First answer.', '[short pause] Next answer.']
    assert [s['source_hash'] for s in dispatched] == [_speech_source_identity(part) for part in clauses]
