// Focused native-Node regression checks for assistant speech playback.
// Exercises the production queue and shared projection without browser globals.
// Fake media exposes delayed playback and real media-event ordering explicitly.
// Browser rendering and encrypted asset transport are separate CI evidence.
// Run with node --experimental-strip-types --test on this file.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { AssistantSpeechQueue } from '../assistantSpeechQueue.ts';
import { projectAssistantSpeech } from '../../../../assistantSpeechProjection.ts';

const segment = (sequence, status = 'ready') => ({
  id: `segment-${sequence}`, sequence, status, audioUrl: `blob:audio-${sequence}`,
  durationMs: 1000, playbackClass: 'replayable',
  chapter: { kind: 'part', number: sequence + 1 }, waveform: [],
});
function harness(play = async () => {}) {
  const events = new Map();
  const audio = { play, pause() {}, addEventListener(name, fn) { events.set(name, fn); } };
  const queue = new AssistantSpeechQueue({ audioFactory: () => audio });
  return { queue, emit: (name) => events.get(name)?.() };
}

// contract-test: supporting surface=gui.web assertions=assistant-speech.failure.nonblocking-visible-resumable
test('failed generation stops waiting at the affected chapter', () => {
  const { queue } = harness();
  queue.start('response', [segment(0, 'generating')]);
  queue.upsertSegment(segment(0, 'failed'));
  assert.equal(queue.state.status, 'failed');
  queue.stop();
});

// contract-test: supporting surface=gui.web assertions=assistant-speech.failure.nonblocking-visible-resumable
test('media errors are visible after playback has started', async () => {
  const { queue, emit } = harness();
  queue.start('response', [segment(0)]);
  await Promise.resolve();
  emit('error');
  assert.equal(queue.state.status, 'failed');
  queue.stop();
});

// contract-test: supporting surface=gui.web assertions=assistant-speech.playback.single-queue-segment-control
test('late play promise cannot undo user pause', async () => {
  let resolvePlay;
  const { queue } = harness(() => new Promise((resolve) => { resolvePlay = resolve; }));
  queue.start('response', [segment(0)]);
  queue.pause();
  resolvePlay();
  await Promise.resolve();
  assert.equal(queue.state.status, 'paused');
  queue.stop();
});

// contract-test: supporting surface=cli assertions=assistant-speech.projection.deterministic-semantic
test('search metadata is not code and natural leading citations remain prose', () => {
  const markdown = '```json\n{"type":"app_skill_use","app_id":"web","skill_id":"search","embed_id":"search-1"}\n```';
  assert.equal(projectAssistantSpeech(markdown)[0].speakableText, 'Search results are available.');
  assert.equal(projectAssistantSpeech(markdown)[0].kind, 'embed_summary');
  const citation = projectAssistantSpeech('[According to CNBC](embed:cnbc.com-Ab1), it comes in burgundy.')[0];
  assert.equal(citation.kind, 'prose_paragraph');
  assert.equal(citation.speakableText, 'According to CNBC, it comes in burgundy.');
});

// contract-test: supporting surface=cli assertions=assistant-speech.projection.deterministic-semantic
test('multiline and long embed metadata never leaks into narrated chunks', () => {
  const payload = JSON.stringify({ type: 'app_skill_use', app_id: 'web', skill_id: 'search', query: 'private'.repeat(500) }, null, 2);
  const output = projectAssistantSpeech(`Intro.\n\n\`\`\`json\n\n${payload}\n\n\`\`\`\n\nSummary.`);
  assert.deepEqual(output.map(({ speakableText }) => speakableText), ['Intro.', 'Search results are available.', 'Summary.']);
});

// contract-test: supporting surface=gui.web assertions=assistant-speech.playback.two-second-idle-grace,assistant-speech.playback.single-queue-segment-control
test('a known complete response finishes instead of loading forever', async () => {
  const { queue, emit } = harness();
  queue.start('response', [segment(0)]);
  queue.markComplete();
  await Promise.resolve();
  emit('ended');
  assert.equal(queue.state.status, 'completed');
  queue.stop();
});
