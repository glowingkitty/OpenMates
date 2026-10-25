'use strict';
// contract-test-file: tooling
// Engineering regression for the real observer, without network or inference.
// Run: node --test scripts/verify_voice_call_live_smoke.test.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const encodedAudio = Buffer.from('public synthetic audio bytes').toString('base64');
const { installObservation, cleanupRealCall, progressivePlaybackMetrics, continuousTurnMetrics, responsePlaybackComplete, validateObservedHeardBoundaries } = require('./verify_voice_call_live_smoke.cjs');

function browserHarness() {
  let time = 0, nextTimer = 0, waveform = null;
  const timers = new Map(), frames = [];
  class Events {
    constructor() { this.listeners = new Map(); }
    addEventListener(type, listener, options) {
      const list = this.listeners.get(type) ?? [];
      list.push({ listener, capture: options?.capture === true }); this.listeners.set(type, list);
    }
    dispatch(type, event = {}) {
      const listeners = [...(this.listeners.get(type) ?? [])];
      for (const capture of [true, false]) for (const item of listeners) if (item.capture === capture) item.listener(event);
    }
  }
  class Media extends Events {
    constructor() { super(); this.currentTime = 0; this.paused = true; this.ended = false; }
    get src() { return this.source ?? ''; }
    set src(value) { this.source = value; this.currentTime = 0; this.ended = false; this.paused = true; }
    play() { this.nativePlayCalls = (this.nativePlayCalls ?? 0) + 1; this.paused = false; return Promise.resolve(); }
    finish() { this.ended = true; this.paused = true; this.dispatch('ended'); }
  }
  class Audio extends Media {}
  class SourceBuffer { appendBuffer() {} }
  class MediaSource { addSourceBuffer() { return new SourceBuffer(); } }
  class BrowserURL extends URL {
    static createObjectURL() { return `blob:mse-${++nextTimer}`; }
  }
  class Socket extends Events {
    send() {}
    receive(type, payload) { this.dispatch('message', { data: JSON.stringify({ type, payload }) }); }
  }
  const document = {
    bar: false, notifications: [],
    documentElement: { prepend(node) { node.isConnected = true; } },
    createElement: () => ({ isConnected: false }),
    querySelector(selector) {
      if (selector.includes('assistant-speech-waveform')) return waveform ? { getAttribute: () => waveform } : null;
      if (selector === '[data-testid="voice-call-bar"]') return this.bar ? { getAttribute: () => 'false' } : null;
      return null;
    },
    querySelectorAll(selector) { return selector.includes('notification') ? this.notifications : []; },
  };
  const refreshResponses = [];
  const window = { WebSocket: Socket, addEventListener() {}, fetch: async () => {
    const next = refreshResponses.shift();
    if (!next) throw new Error('Unexpected native fetch in observer regression');
    return { ok: next.ok, json: async () => next.body };
  } };
  const sandbox = { window, document, navigator: { mediaDevices: { getUserMedia: async () => {} } },
    HTMLMediaElement: Media, HTMLAudioElement: Audio, MediaSource, SourceBuffer,
    atob: value => Buffer.from(value, 'base64').toString('binary'),
    crypto: { subtle: { digest: async (_algorithm, bytes) => crypto.createHash('sha256')
      .update(Buffer.from(bytes.buffer ?? bytes, bytes.byteOffset ?? 0, bytes.byteLength)).digest() } }, URL: BrowserURL, Promise, location: { href: 'https://app.dev.openmates.org/' },
    performance: { now: () => time }, MutationObserver: class { observe() {} },
    setInterval(callback) { timers.set(++nextTimer, callback); return nextTimer; },
    clearInterval(handle) { timers.delete(handle); }, requestAnimationFrame(callback) { frames.push(callback); },
  };
  const context = vm.createContext(sandbox);
  vm.runInContext(`(${installObservation.toString()})({inputs:[]})`, context);
  const api = window.__voiceLiveSmoke;
  const socket = new window.WebSocket('wss://api.dev.openmates.org/v1/ws');
  const voice = new window.WebSocket('wss://api.dev.openmates.org/v1/voice-call');
  return { Audio, api, socket, voice, document, context,
    connectSocket: () => new window.WebSocket('wss://api.dev.openmates.org/v1/ws'),
    createMediaSourceURL: (encoded = encodedAudio) => {
      const media = new MediaSource(), url = BrowserURL.createObjectURL(media);
      if (encoded !== null) media.addSourceBuffer('audio/mpeg').appendBuffer(new Uint8Array(Buffer.from(encoded, 'base64')));
      return url;
    },
    waveform(value) { waveform = value; },
    tick(milliseconds = 50) { time += milliseconds; for (const callback of [...timers.values()]) callback(); },
    async refresh(chat, messagesVersion, { bodyChat = chat, ok = true, origin = 'https://api.dev.openmates.org' } = {}) {
      refreshResponses.push({ ok, body: { chat_id: bodyChat, messages_v: messagesVersion,
        messages: [{ encrypted_content: 'PRIVATE_REFRESH_CIPHERTEXT' }] } });
      const response = await window.fetch(`${origin}/v1/chats/${chat}/messages/window?limit=1&respect_compression_boundary=false`,
        { credentials: 'include', cache: 'no-store' });
      return response.json();
    },
    frame() { time += 16; for (const callback of frames.splice(0)) callback(); },
    ready(segment, message, kind) { socket.receive('assistant_speech_status', {
      message_id: message, segment_id: segment, status: 'ready', kind,
    }); return api.state.events.at(-1); },
    playback() { return JSON.parse(JSON.stringify(api.state.playback)); },
    async settle() { for (let i = 0; i < 20; i++) await Promise.resolve(); this.frame(); this.frame(); },
  };
}

test('only the exact known silent autoplay prime is excluded; the same element still proves real MSE playback', async () => {
  const queue = fs.readFileSync(path.resolve(__dirname, '../frontend/packages/ui/src/services/assistantSpeechQueue.ts'), 'utf8');
  const silent = queue.match(/const SILENT_AUDIO_DATA_URL = "([^"]+)";/)?.[1];
  assert.ok(silent, 'Use the actual queue priming constant so source drift cannot broaden the exclusion');
  const browser = browserHarness(), audio = new browser.Audio();
  audio.src = silent;
  await audio.play(); await browser.settle(); audio.currentTime = 0.01; browser.tick(); audio.finish();
  assert.equal(audio.nativePlayCalls, 1, 'native priming must still execute');
  assert.equal(browser.api.state.ignoredSilentAutoplayPrimes, 1);
  assert.equal(browser.playback().length, 0);
  assert.equal(browser.api.state.events.some(event => event.type === 'media_correlation_failed'), false);
  browser.socket.receive('assistant_speech_audio', { message_id: 'real-response', segment_id: 'real-segment',
    kind: 'voice_prose_clause', phase: 'start', attempt_id: 'real-attempt', chunk_index: 0 });
  browser.socket.receive('assistant_speech_audio', { message_id: 'real-response', segment_id: 'real-segment',
    kind: 'voice_prose_clause', phase: 'chunk', attempt_id: 'real-attempt', chunk_index: 0, audio_data: encodedAudio });
  audio.src = browser.createMediaSourceURL(); browser.waveform('real-segment');
  await audio.play(); await browser.settle(); audio.currentTime = 0.2; browser.tick(); browser.tick();
  const progress = browser.playback()[0];
  assert.equal(progress.sourceKind, 'media_source');
  assert.equal(progress.kind, 'voice_prose_clause');
  browser.tick();
  browser.socket.receive('assistant_speech_audio', { message_id: 'real-response', segment_id: 'real-segment',
    kind: 'voice_prose_clause', phase: 'end', attempt_id: 'real-attempt', chunk_index: 1 });
  assert.equal(progressivePlaybackMetrics(browser.api.state, progress).playbackBeforeSameSegmentProviderEnd, true);
  audio.currentTime = 1; audio.finish();
  assert.equal(audio.nativePlayCalls, 2);
  assert.deepEqual(browser.playback().map(event => event.type), ['first_progress', 'ended']);
  assert.equal(browser.api.state.events.some(event => event.type === 'media_correlation_failed'), false);
});

for (const source of ['blob:uncorrelated-real-response', 'data:audio/wav;base64,AAAA']) {
  test(`uncorrelated audio remains fatal for ${source.startsWith('blob:') ? 'real blob' : 'unknown data'} source`, async () => {
    const browser = browserHarness(), audio = new browser.Audio();
    audio.src = source;
    await audio.play(); await browser.settle(); audio.currentTime = 0.1; browser.tick(); audio.finish();
    assert.equal(browser.api.state.ignoredSilentAutoplayPrimes, undefined);
    assert.equal(browser.playback().length, 0);
    assert.equal(browser.api.state.events.filter(event => event.type === 'media_correlation_failed').length, 1);
  });
}

test('reused native Audio resets each source, rejects stale DOM and out-of-order ready, and observes the second response', async () => {
  const browser = browserHarness(), audio = new browser.Audio();
  // A future clause is ready first; neither readiness order nor stale waveform
  // may identify the actual source currently playing.
  const statuses = {
    'second-response': browser.ready('second-response', 'response-2', 'voice_prose_clause'),
    'clause-2': browser.ready('clause-2', 'response-1', 'voice_prose_clause'),
    waiting: browser.ready('waiting', 'response-1', 'waiting_confirmation'),
    'clause-1': browser.ready('clause-1', 'response-1', 'voice_prose_clause'),
  };
  let nextSource;
  // Production installs this BEFORE the observer sees play(). Its ended handler
  // synchronously changes src and starts the next clip before Svelte renders.
  audio.addEventListener('ended', () => {
    if (nextSource) { audio.src = nextSource; nextSource = null; void audio.play(); }
  });
  audio.src = 'blob:waiting'; browser.waveform('waiting');
  await audio.play(); await browser.settle();
  audio.currentTime = 0.1; browser.tick(); browser.tick();
  assert.equal(browser.playback().length, 1);
  assert.equal(browser.playback()[0].kind, 'waiting_confirmation');
  assert.equal(browser.playback()[0].segmentId, statuses.waiting.segmentId);

  for (const [source, segment, ordinal] of [
    ['blob:clause-1', 'clause-1', 2],
    ['blob:clause-2', 'clause-2', 3],
    ['blob:second-response', 'second-response', 4],
  ]) {
    nextSource = source;
    audio.currentTime = 1; audio.finish();
    const before = browser.playback().length;
    assert.equal(browser.playback().at(-1).type, 'ended', 'previous clip ends before synchronous reuse');
    assert.equal(browser.playback().at(-1).generation, ordinal - 1);
    audio.currentTime = 0.08; browser.tick();
    await browser.settle(); browser.tick(); browser.tick();
    assert.equal(browser.playback().length, before, 'advanced new source must not bind stale DOM');
    browser.waveform(segment); browser.tick(); browser.tick();
    const progress = browser.playback().at(-1);
    assert.equal(progress.type, 'first_progress');
    assert.equal(progress.kind, 'voice_prose_clause');
    assert.equal(progress.generation, ordinal);
    assert.equal(progress.segmentId, statuses[segment].segmentId);
    assert.equal(progress.messageId, statuses[segment].messageId);
  }
  audio.currentTime = 1; audio.finish();
  const playback = browser.playback();
  assert.equal(playback.filter(event => event.type === 'first_progress').length, 4);
  assert.equal(playback.filter(event => event.type === 'ended').length, 4);
  assert.equal(new Set(playback.map(event => event.mediaId)).size, 1, 'same actual element was reused');
  assert.equal(new Set(playback.map(event => event.sourceId)).size, 4, 'each actual source has its own correlation');
  assert.equal(browser.api.state.events.some(event => event.type === 'media_correlation_failed'), false);
});

test('MSE progress precedes the SAME segment provider end and retains phase metadata without audio bytes', async () => {
  const browser = browserHarness(), audio = new browser.Audio();
  const rawAudio = 'cHVibGljLXN5bnRoZXRpYy1hdWRpby1ieXRlcw==';
  for (const [phase, index] of [['start', 0], ['chunk', 0]]) browser.socket.receive('assistant_speech_audio', {
    message_id: 'response-stream', segment_id: 'stream-segment', kind: 'voice_prose_clause',
    phase, chunk_index: index, attempt_id: 'attempt-1', source_version: 1, execution_version: 2,
    ...(phase === 'chunk' ? { audio_data: rawAudio } : {}),
  });
  audio.src = browser.createMediaSourceURL(rawAudio); browser.waveform('stream-segment');
  await audio.play(); await browser.settle(); audio.currentTime = 0.2; browser.tick(); browser.tick();
  const progress = browser.playback()[0];
  assert.equal(progress.sourceKind, 'media_source');
  assert.equal(progress.kind, 'voice_prose_clause');
  browser.ready('another-ready-clause', 'response-stream', 'voice_prose_clause');
  assert.equal(progressivePlaybackMetrics(browser.api.state, progress).speechReadyMs, null,
    'a different clause ready cannot stand in for the clip actually heard');
  browser.socket.receive('assistant_speech_audio', { message_id: 'response-stream', segment_id: 'another-ready-clause', phase: 'end', attempt_id: 'attempt-1' });
  browser.socket.receive('assistant_speech_audio', { message_id: 'response-stream', segment_id: 'stream-segment', phase: 'end', attempt_id: 'older-attempt' });
  assert.equal(progressivePlaybackMetrics(browser.api.state, progress).sameSegmentProviderEndMs, null);
  assert.equal(progressivePlaybackMetrics(browser.api.state, progress).playbackBeforeSameSegmentProviderEnd, false);
  browser.tick();
  const storedReady = browser.ready('stream-segment', 'response-stream', 'voice_prose_clause');
  browser.socket.receive('assistant_speech_audio', { message_id: 'response-stream', segment_id: 'stream-segment', phase: 'end', attempt_id: 'attempt-1', source_version: 1, execution_version: 2 });
  const metric = progressivePlaybackMetrics(browser.api.state, progress);
  assert.equal(metric.speechReadyMs, storedReady.atMs);
  assert.equal(metric.playbackBeforeSameSegmentProviderEnd, true);
  assert.ok(metric.sameSegmentPlaybackLeadMs > 0);
  assert.equal(metric.generatedCallAssetStatusCount, 0);
  assert.equal(browser.playback().length, 1, 'late stored-ready does not invent another playback observation');
  const receipt = JSON.stringify(browser.api.snapshot());
  assert.equal(receipt.includes(rawAudio), false);
  assert.equal(receipt.includes('audio_data'), false);
  assert.equal(browser.api.state.events.filter(event => event.type === 'assistant_speech_audio').length, 5);
});

test('MSE byte/source correlation proves clock progress with no message player DOM', async () => {
  const browser = browserHarness(), audio = new browser.Audio();
  const querySelector = browser.document.querySelector.bind(browser.document);
  browser.document.querySelector = selector => {
    if (selector.includes('assistant-speech-waveform')) throw new Error('MSE playback must not query message player DOM');
    return querySelector(selector);
  };
  const identity = { message_id: 'hidden-call-response', segment_id: 'hidden-call-segment',
    kind: 'voice_prose_clause', attempt_id: 'hidden-attempt', source_version: 3, execution_version: 7, sequence: 2 };
  browser.socket.receive('assistant_speech_audio', { ...identity, phase: 'start', chunk_index: 0 });
  browser.socket.receive('assistant_speech_audio', { ...identity, phase: 'chunk', chunk_index: 0, audio_data: encodedAudio });
  // A newer unrelated start must not steal the actual SourceBuffer's identity.
  browser.socket.receive('assistant_speech_audio', { ...identity, segment_id: 'future-segment', phase: 'start', chunk_index: 0 });
  audio.src = browser.createMediaSourceURL();
  await audio.play(); await browser.settle(); browser.tick();
  assert.equal(browser.playback().length, 0, 'appended bytes alone are not audible progress');
  audio.currentTime = 0.2; browser.tick();
  const progress = browser.playback()[0];
  assert.equal(progress.segmentId, browser.api.state.events[0].segmentId);
  assert.equal(progress.attemptId, browser.api.state.events[0].attemptId);
  assert.equal(progress.sourceKind, 'media_source');
  browser.tick();
  for (const key of ['source_version', 'execution_version', 'sequence']) {
    browser.socket.receive('assistant_speech_audio', { ...identity, [key]: 99, phase: 'end', chunk_index: 1 });
  }
  browser.socket.send(JSON.stringify({ type: 'assistant_speech_audio', payload: { ...identity, phase: 'end', chunk_index: 1 } }));
  assert.equal(progressivePlaybackMetrics(browser.api.state, progress).sameSegmentProviderEndMs, null,
    'wrong source/execution/sequence and outgoing frames cannot provide an end fence');
  browser.socket.receive('assistant_speech_audio', { ...identity, phase: 'end', chunk_index: 1 });
  assert.equal(progressivePlaybackMetrics(browser.api.state, progress).playbackBeforeSameSegmentProviderEnd, true);
  audio.finish();
  assert.deepEqual(browser.playback().map(item => item.type), ['first_progress', 'ended']);
  const receipt = JSON.stringify(browser.api.snapshot());
  assert.equal(receipt.includes(encodedAudio), false);
  assert.equal(receipt.includes('audio_data'), false);
  assert.equal(receipt.includes(crypto.createHash('sha256').update(Buffer.from(encodedAudio, 'base64')).digest('hex')), false);
});

test('native MSE provider timing requires start, chunk and end on the exact playback connection', async () => {
  const browser = browserHarness(), audio = new browser.Audio();
  const identity = { message_id: 'response', segment_id: 'segment', kind: 'voice_prose_clause', attempt_id: 'attempt' };
  browser.socket.receive('assistant_speech_audio', { ...identity, phase: 'start', chunk_index: 0 });
  browser.socket.receive('assistant_speech_audio', { ...identity, phase: 'chunk', chunk_index: 0, audio_data: encodedAudio });
  audio.src = browser.createMediaSourceURL();
  await audio.play(); await browser.settle(); audio.currentTime = 0.2; browser.tick();
  const progress = browser.playback()[0];
  assert.equal(progress.socketId, browser.api.state.events[0].socketId, 'native playback retains the received start connection');
  browser.tick();
  browser.connectSocket().receive('assistant_speech_audio', { ...identity, phase: 'end', chunk_index: 1 });
  const mismatched = progressivePlaybackMetrics(browser.api.state, progress);
  assert.equal(mismatched.sameSegmentProviderEndMs, null);
  assert.equal(mismatched.playbackBeforeSameSegmentProviderEnd, false, 'another connection cannot complete this native source');
  browser.socket.receive('assistant_speech_audio', { ...identity, phase: 'end', chunk_index: 1 });
  assert.equal(progressivePlaybackMetrics(browser.api.state, progress).playbackBeforeSameSegmentProviderEnd, true);
  for (const phase of ['start', 'chunk', 'end']) {
    const state = { events: browser.api.state.events.filter(event => event.socketId === progress.socketId)
      .map(event => event.phase === phase ? { ...event, socketId: progress.socketId + 99 } : event) };
    assert.equal(progressivePlaybackMetrics(state, progress).playbackBeforeSameSegmentProviderEnd, false,
      `the ${phase} fence must belong to the actual playback connection`);
  }
  assert.equal(progressivePlaybackMetrics(browser.api.state, { ...progress, socketId: undefined })
    .playbackBeforeSameSegmentProviderEnd, false, 'missing playback connection fails closed');
  audio.finish();
  assert.equal(browser.playback().at(-1).socketId, progress.socketId);
});

for (const mismatch of ['bytes', 'source', 'segment', 'message', 'attempt', 'source_version', 'execution_version', 'sequence', 'sent', 'ambiguous']) {
  test(`MSE correlation fails closed for unmatched ${mismatch} despite ready status and DOM`, async () => {
    const browser = browserHarness(), audio = new browser.Audio();
    const identity = { message_id: 'response', segment_id: 'segment', kind: 'voice_prose_clause', attempt_id: 'attempt',
      source_version: 1, execution_version: 2, sequence: 0 };
    browser.socket.receive('assistant_speech_audio', { ...identity, phase: 'start', chunk_index: 0 });
    const chunk = { ...identity, phase: 'chunk', chunk_index: 0, audio_data: encodedAudio };
    const field = { segment: 'segment_id', message: 'message_id', attempt: 'attempt_id' }[mismatch] ?? mismatch;
    if (['segment', 'message', 'attempt'].includes(mismatch)) chunk[field] = 'unmatched';
    if (['source_version', 'execution_version', 'sequence'].includes(mismatch)) chunk[field] = 99;
    if (mismatch === 'sent') browser.socket.send(JSON.stringify({ type: 'assistant_speech_audio', payload: chunk }));
    else browser.socket.receive('assistant_speech_audio', chunk);
    if (mismatch === 'ambiguous') {
      const other = { ...identity, segment_id: 'ambiguous-segment' };
      browser.socket.receive('assistant_speech_audio', { ...other, phase: 'start', chunk_index: 0 });
      browser.socket.receive('assistant_speech_audio', { ...chunk, ...other });
    }
    browser.ready('segment', 'response', 'voice_prose_clause'); browser.waveform('segment');
    const matchedSource = browser.createMediaSourceURL(mismatch === 'bytes' ? Buffer.from('different actual bytes').toString('base64') : encodedAudio);
    audio.src = mismatch === 'source' ? browser.createMediaSourceURL(null) : matchedSource;
    await audio.play(); await browser.settle(); audio.currentTime = 0.3; browser.tick(); audio.finish();
    assert.equal(browser.playback().length, 0);
    assert.equal(browser.api.state.events.filter(event => event.type === 'media_correlation_failed').length, 1);
  });
}

test('hangup intent requires the actual outgoing voice frame; early closure remains unexpected', () => {
  const browser = browserHarness();
  browser.api.state.hangupRequested = true;
  browser.voice.dispatch('close', { code: 1000 });
  assert.equal(browser.api.state.expectedHangup, false);
  assert.equal(browser.api.state.unexpectedEnd, true);
  browser.voice.send(JSON.stringify({ type: 'hangup' }));
  assert.equal(browser.api.state.expectedHangup, false, 'later request cannot erase early call loss');

  const clean = browserHarness();
  clean.api.state.hangupRequested = true;
  clean.voice.send(JSON.stringify({ type: 'hangup' }));
  clean.voice.dispatch('close', { code: 1000 });
  assert.equal(clean.api.state.expectedHangup, true);
  assert.equal(clean.api.state.unexpectedEnd, false);
});

test('cleanup rejects missing visible Hangup and an already ended call before declaring intent', async () => {
  let markedIntent = false;
  const page = { locator: () => ({ count: async () => 0 }), evaluate: async () => { markedIntent = true; } };
  await assert.rejects(cleanupRealCall(page, async () => ({ callActive: true })), /visible_hangup_button_required/);
  assert.equal(markedIntent, false);
  await assert.rejects(cleanupRealCall(page, async () => ({ callActive: false, unexpectedEnd: true })), /unexpected_call_end_before_hangup/);
  assert.equal(markedIntent, false);
});

test('a disappearing UI and stopped capture cannot pass cleanup without the outgoing hangup frame', async () => {
  for (const sendFrame of [false, true]) {
    const browser = browserHarness(); browser.document.bar = true;
    const page = {
      locator: () => ({ count: async () => 1, click: async () => {
        if (sendFrame) browser.voice.send(JSON.stringify({ type: 'hangup' }));
        browser.document.bar = false; browser.api.state.inputStopped = true;
      } }),
      evaluate: async callback => vm.runInContext(`(${callback.toString()})()`, browser.context),
      waitForFunction: async callback => {
        if (!vm.runInContext(`(${callback.toString()})()`, browser.context)) throw new Error('cleanup_not_confirmed');
      },
    };
    const action = cleanupRealCall(page, async () => browser.api.snapshot());
    if (sendFrame) await action;
    else await assert.rejects(action, /cleanup_not_confirmed/);
  }
});

test('known revision conflict protocol outcome and static toast are retained without their text', () => {
  const protocol = browserHarness();
  protocol.socket.receive('call_message_confirmed', { outcome: 'call_message_revision_conflict' });
  assert.equal(protocol.api.state.revisionConflict, true);
  const toast = browserHarness();
  toast.document.notifications = [{ textContent: 'Server error: call_message_revision_conflict' }]; toast.tick();
  assert.equal(toast.api.state.revisionConflict, true);
  assert.equal(JSON.stringify(toast.api.snapshot()).includes('Server error:'), false);
});


const recoveryScope = { job: 'private-job-id', chat: 'private-chat-id', message: 'private-assistant-id' };
function sendRecovery(browser, requestId, expectedVersion, scope = recoveryScope, socket = browser.socket) {
  socket.send(JSON.stringify({ type: 'recovery_job_persist', payload: {
    job_id: scope.job, request_id: requestId, expected_messages_v: expectedVersion,
    lease_token: 'PRIVATE_LEASE_TOKEN', encrypted_assistant_message: {
      chat_id: scope.chat, client_message_id: scope.message, encrypted_content: 'PRIVATE_MESSAGE_CIPHERTEXT',
      content: 'PRIVATE_TRANSCRIPT_CANARY',
    },
  } }));
}
function conflictRecovery(browser, requestId = 'persist-first', scope = recoveryScope) {
  sendRecovery(browser, requestId, 5, scope);
  browser.socket.receive('error', { code: 'version_conflict', job_id: scope.job, request_id: requestId,
    message: 'PRIVATE_ERROR_BODY' });
}
function acknowledgeRecovery(browser, extra = {}, socket = browser.socket) {
  socket.receive('recovery_job_persisted', { job_id: recoveryScope.job, request_id: 'persist-retry',
    state: 'TERMINAL', committed_messages_v: 5, ...extra });
}

test('completion CAS permits only the real same-chat refresh, exact retry and matching terminal ACK; receipt stays pseudonymous', async () => {
  const browser = browserHarness(); conflictRecovery(browser);
  assert.equal(browser.api.snapshot().revisionConflict, false);
  assert.equal(browser.api.snapshot().recoveryPending, 1);
  assert.ok(browser.api.state.events.find(event => event.type === 'error').recoveryConflictId);
  await browser.refresh(recoveryScope.chat, 4);
  sendRecovery(browser, 'persist-retry', 4); acknowledgeRecovery(browser);
  const receipt = browser.api.snapshot();
  assert.equal(receipt.revisionConflict, false); assert.equal(receipt.recoveryPending, 0);
  assert.equal(receipt.recoveryConflicts[0].status, 'resolved');
  assert.equal(receipt.recoveryConflicts[0].expectedVersion, 5);
  assert.equal(receipt.recoveryConflicts[0].refreshVersion, 4);
  assert.equal(receipt.recoveryConflicts[0].retryExpectedVersion, 4);
  assert.equal(receipt.recoveryConflicts[0].committedVersion, 5);
  assert.equal(receipt.events.filter(event => event.type === 'recovery_chat_version_refresh').length, 2);
  const serialized = JSON.stringify(receipt);
  for (const value of [...Object.values(recoveryScope), 'persist-first', 'persist-retry', 'PRIVATE_LEASE_TOKEN',
    'PRIVATE_MESSAGE_CIPHERTEXT', 'PRIVATE_REFRESH_CIPHERTEXT', 'PRIVATE_TRANSCRIPT_CANARY', 'PRIVATE_ERROR_BODY']) {
    assert.equal(serialized.includes(value), false, `Private marker must not leave the observer: ${value}`);
  }
});

for (const mismatch of ['unscoped', 'wrong_job', 'wrong_request', 'wrong_socket']) {
  test(`version conflict remains fatal for ${mismatch}`, () => {
    const browser = browserHarness();
    if (mismatch !== 'unscoped') sendRecovery(browser, 'persist-first', 5);
    const socket = mismatch === 'wrong_socket' ? new browser.context.window.WebSocket('wss://api.dev.openmates.org/v1/ws') : browser.socket;
    socket.receive('error', { code: 'version_conflict', job_id: mismatch === 'wrong_job' ? 'other-job' : recoveryScope.job,
      request_id: mismatch === 'wrong_request' ? 'unknown-request' : 'persist-first' });
    assert.equal(browser.api.snapshot().revisionConflict, true);
  });
}

for (const mismatch of ['missing_refresh', 'wrong_chat', 'wrong_message', 'wrong_version', 'wrong_socket']) {
  test(`completion retry cannot recover with ${mismatch}`, async () => {
    const browser = browserHarness(); conflictRecovery(browser);
    if (mismatch !== 'missing_refresh') await browser.refresh(recoveryScope.chat, 4);
    const scope = { ...recoveryScope, ...(mismatch === 'wrong_chat' ? { chat: 'other-chat' } : {}),
      ...(mismatch === 'wrong_message' ? { message: 'other-message' } : {}) };
    const socket = mismatch === 'wrong_socket' ? new browser.context.window.WebSocket('wss://api.dev.openmates.org/v1/ws') : browser.socket;
    sendRecovery(browser, 'persist-retry', mismatch === 'wrong_version' ? 6 : 4, scope, socket);
    assert.equal(browser.api.snapshot().revisionConflict, true);
    assert.equal(browser.api.snapshot().recoveryPending, 1);
  });
}

for (const badRefresh of ['wrong_owner_chat', 'boolean_version', 'failed_read', 'wrong_origin']) {
  test(`completion refresh cannot invent authority from ${badRefresh}`, async () => {
    const browser = browserHarness(); conflictRecovery(browser);
    await browser.refresh(recoveryScope.chat, badRefresh === 'boolean_version' ? true : 4, {
      bodyChat: badRefresh === 'wrong_owner_chat' ? 'other-chat' : recoveryScope.chat,
      ok: badRefresh !== 'failed_read', origin: badRefresh === 'wrong_origin' ? 'https://untrusted.example' : 'https://api.dev.openmates.org',
    });
    sendRecovery(browser, 'persist-retry', 4);
    assert.equal(browser.api.snapshot().revisionConflict, true);
  });
}

for (const badAck of ['old_request', 'wrong_request', 'wrong_job', 'wrong_socket', 'wrong_type', 'wrong_state', 'missing_version']) {
  test(`completion conflict remains fatal for ${badAck} ACK`, async () => {
    const browser = browserHarness(); conflictRecovery(browser);
    await browser.refresh(recoveryScope.chat, 4); sendRecovery(browser, 'persist-retry', 4);
    const extra = badAck === 'old_request' ? { request_id: 'persist-first' }
      : badAck === 'wrong_request' ? { request_id: 'unknown-request' }
      : badAck === 'wrong_job' ? { job_id: 'other-job' }
      : badAck === 'wrong_state' ? { state: 'AVAILABLE' }
      : badAck === 'missing_version' ? { committed_messages_v: undefined } : {};
    if (badAck === 'wrong_type') browser.socket.receive('recovery_output_persisted', {
      record_id: recoveryScope.job, request_id: 'persist-retry', state: 'ACKNOWLEDGED', committed_messages_v: 5 });
    else acknowledgeRecovery(browser, extra, badAck === 'wrong_socket'
      ? new browser.context.window.WebSocket('wss://api.dev.openmates.org/v1/ws') : browser.socket);
    assert.equal(browser.api.snapshot().revisionConflict, true);
  });
}

test('unresolved completion conflict expires after the bounded callback/refresh/retry window', () => {
  const browser = browserHarness(); conflictRecovery(browser);
  browser.tick(29999); assert.equal(browser.api.snapshot().revisionConflict, false);
  browser.tick(2); assert.equal(browser.api.snapshot().revisionConflict, true);
  assert.equal(browser.api.snapshot().recoveryConflicts[0].status, 'failed');
  assert.equal(browser.api.snapshot().recoveryPending, 1);
});

for (const count of [2, 3]) {
  test(`${count} consecutive completion conflicts require a fresh authorized read at each edge and one final terminal ACK`, async () => {
    const browser = browserHarness(); conflictRecovery(browser);
    for (let index = 1; index <= count; index++) {
      await browser.refresh(recoveryScope.chat, 5 + index);
      sendRecovery(browser, `persist-retry-${index}`, 5 + index);
      if (index < count) browser.socket.receive('error', {
        code: 'version_conflict', job_id: recoveryScope.job, request_id: `persist-retry-${index}`,
      });
    }
    assert.equal(browser.api.snapshot().revisionConflict, false);
    assert.equal(browser.api.snapshot().recoveryPending, 1);
    acknowledgeRecovery(browser, { request_id: `persist-retry-${count}`, committed_messages_v: 6 + count });
    const receipt = browser.api.snapshot();
    assert.equal(receipt.revisionConflict, false);
    assert.equal(receipt.recoveryPending, 0);
    assert.equal(receipt.recoveryConflicts.length, count);
    assert.ok(receipt.recoveryConflicts.every(item => item.status === 'resolved'));
    assert.equal(receipt.events.filter(event => event.type === 'recovery_chat_version_refresh').length, count * 2);
    assert.equal(JSON.stringify(receipt).includes('persist-retry-'), false);
  });
}

for (const mismatch of ['missing_fresh_read', 'old_terminal', 'parallel_request', 'duplicate_conflict', 'fourth_conflict']) {
  test(`a completion conflict chain fails closed on ${mismatch}`, async () => {
    const browser = browserHarness(); conflictRecovery(browser);
    await browser.refresh(recoveryScope.chat, 6); sendRecovery(browser, 'persist-retry', 6);
    browser.socket.receive('error', { code: 'version_conflict', job_id: recoveryScope.job, request_id: 'persist-retry' });
    if (mismatch === 'duplicate_conflict') browser.socket.receive('error', {
      code: 'version_conflict', job_id: recoveryScope.job, request_id: 'persist-retry',
    });
    else if (mismatch === 'parallel_request') {
      sendRecovery(browser, 'parallel-request', 7);
      browser.socket.receive('error', { code: 'version_conflict', job_id: recoveryScope.job, request_id: 'parallel-request' });
    } else {
      if (mismatch !== 'missing_fresh_read') await browser.refresh(recoveryScope.chat, 7);
      sendRecovery(browser, 'persist-third', 7);
      if (mismatch === 'fourth_conflict') {
        browser.socket.receive('error', { code: 'version_conflict', job_id: recoveryScope.job, request_id: 'persist-third' });
        await browser.refresh(recoveryScope.chat, 8); sendRecovery(browser, 'persist-fourth', 8);
        browser.socket.receive('error', { code: 'version_conflict', job_id: recoveryScope.job, request_id: 'persist-fourth' });
      } else acknowledgeRecovery(browser, { request_id: mismatch === 'old_terminal' ? 'persist-retry' : 'persist-third', committed_messages_v: 8 });
    }
    assert.equal(browser.api.snapshot().revisionConflict, true);
    assert.equal(browser.api.snapshot().recoveryPending, 1);
  });
}

test('visible revision or error notification is fatal even after matching recovery; notification bodies never persist', async () => {
  for (const revision of [false, true]) {
    const browser = browserHarness(); conflictRecovery(browser);
    await browser.refresh(recoveryScope.chat, 4); sendRecovery(browser, 'persist-retry', 4); acknowledgeRecovery(browser);
    browser.document.notifications = [{ textContent: revision ? 'version_conflict PRIVATE_NOTIFICATION' : 'PRIVATE_NOTIFICATION',
      classList: { contains: name => !revision && name === 'notification-error' } }];
    const receipt = browser.api.snapshot();
    assert.equal(!!receipt.revisionConflict || !!receipt.uiErrorNotification, true);
    assert.equal(JSON.stringify(receipt).includes('PRIVATE_NOTIFICATION'), false);
  }
});

test('output/summary CAS conflicts retain operation/record correlation but stay fatal without a proven supported recovery path', () => {
  for (const type of ['recovery_output_persist_message', 'recovery_output_persist_summary']) {
    const browser = browserHarness();
    browser.socket.send(JSON.stringify({ type, payload: { record_id: 'private-record', request_id: 'output-request',
      encrypted_summary: 'PRIVATE_SUMMARY', expected_metadata_v: 3 } }));
    browser.socket.receive('error', { code: 'version_conflict', job_id: 'private-record', request_id: 'output-request' });
    assert.equal(browser.api.snapshot().revisionConflict, true);
    assert.ok(browser.api.snapshot().recoveryRequests[0].recordId);
    assert.equal(JSON.stringify(browser.api.snapshot()).includes('PRIVATE_SUMMARY'), false);
  }
});

test('metadata jobs require exact job/chat/task/stage/key-version terminal authority and never hide a conflict', () => {
  const job = { job_id: 'metadata-job', chat_id: 'metadata-chat', task_id: 'metadata-task', stage: 'initial', chat_key_version: 1 };
  const browser = browserHarness(); browser.socket.receive('metadata_jobs_available', { jobs: [job] });
  assert.equal(browser.api.snapshot().metadataPending, 1);
  browser.socket.send(JSON.stringify({ type: 'metadata_job_claim', payload: { job_id: job.job_id, request_id: 'metadata-claim' } }));
  browser.socket.receive('metadata_job_claimed', { ...job, request_id: 'metadata-claim', state: 'AVAILABLE' });
  assert.equal(browser.api.snapshot().metadataPending, 1);
  browser.socket.send(JSON.stringify({ type: 'metadata_job_persist', payload: { job_id: job.job_id, request_id: 'metadata-persist',
    wrapped_chat_key: 'PRIVATE_METADATA_KEY', encrypted_metadata: { encrypted_title: 'PRIVATE_METADATA_CIPHERTEXT' } } }));
  browser.socket.receive('metadata_job_persisted', { ...job, request_id: 'metadata-persist', state: 'TERMINAL',
    versions: { metadata_v: 1, title_v: 1 }, encrypted_metadata: { encrypted_title: 'PRIVATE_METADATA_CIPHERTEXT' } });
  assert.equal(browser.api.snapshot().metadataPending, 0); assert.equal(browser.api.snapshot().revisionConflict, false);
  assert.equal(JSON.stringify(browser.api.snapshot()).includes('PRIVATE_METADATA'), false);
  const failed = browserHarness(); failed.socket.receive('metadata_jobs_available', { jobs: [job] });
  failed.socket.send(JSON.stringify({ type: 'metadata_job_persist', payload: { job_id: job.job_id, request_id: 'metadata-persist' } }));
  failed.socket.receive('error', { code: 'version_conflict', job_id: job.job_id, request_id: 'metadata-persist' });
  assert.equal(failed.api.snapshot().revisionConflict, true); assert.equal(failed.api.snapshot().metadataPending, 1);
});


test('an ordinary observed completion persist also requires a terminal receipt before final success', () => {
  const browser = browserHarness(); sendRecovery(browser, 'persist-retry', 4);
  assert.equal(browser.api.snapshot().recoveryPending, 1);
  acknowledgeRecovery(browser);
  assert.equal(browser.api.snapshot().recoveryPending, 0);
  assert.equal(browser.api.snapshot().revisionConflict, false);
});

for (const invalid of ['wrong_chat', 'wrong_task', 'wrong_key_version', 'wrong_stage', 'not_terminal', 'missing_versions', 'invalid_ciphertext_fields']) {
  test(`metadata ${invalid} ACK cannot satisfy final terminal proof`, () => {
    const browser = browserHarness();
    const job = { job_id: 'metadata-job', chat_id: 'metadata-chat', task_id: 'metadata-task', stage: 'initial', chat_key_version: 1 };
    browser.socket.receive('metadata_jobs_available', { jobs: [job] });
    browser.socket.send(JSON.stringify({ type: 'metadata_job_persist', payload: { job_id: job.job_id, request_id: 'metadata-persist' } }));
    const receipt = { ...job, request_id: 'metadata-persist', state: 'TERMINAL',
      versions: { metadata_v: 1, title_v: 1 }, encrypted_metadata: { encrypted_title: 'PRIVATE_METADATA_CIPHERTEXT' } };
    if (invalid === 'wrong_chat') receipt.chat_id = 'other-chat';
    if (invalid === 'wrong_task') receipt.task_id = 'other-task';
    if (invalid === 'wrong_key_version') receipt.chat_key_version = 2;
    if (invalid === 'wrong_stage') receipt.stage = 'postprocessing';
    if (invalid === 'not_terminal') receipt.state = 'AVAILABLE';
    if (invalid === 'missing_versions') delete receipt.versions;
    if (invalid === 'invalid_ciphertext_fields') receipt.encrypted_metadata = { arbitrary: 'PRIVATE_METADATA_CIPHERTEXT' };
    browser.socket.receive('metadata_job_persisted', receipt);
    assert.equal(browser.api.snapshot().revisionConflict, true);
    assert.equal(browser.api.snapshot().metadataPending, 1);
  });
}


test('malformed terminal states fail closed without throwing from the real socket observer', async () => {
  for (const state of [true, {}, undefined]) {
    const browser = browserHarness(); conflictRecovery(browser);
    await browser.refresh(recoveryScope.chat, 4); sendRecovery(browser, 'persist-retry', 4);
    assert.doesNotThrow(() => acknowledgeRecovery(browser, { state }));
    assert.equal(browser.api.snapshot().revisionConflict, true);
  }
});

test('malformed metadata discovery cannot disappear from terminal proof', () => {
  for (const payload of [{ jobs: [null] }, { jobs: {} }]) {
    const browser = browserHarness();
    assert.doesNotThrow(() => browser.socket.receive('metadata_jobs_available', payload));
    assert.equal(browser.api.snapshot().revisionConflict, true);
  }
});

async function continuousBrowser() {
  const browser = browserHarness(), player = new browser.Audio();
  const identity = { chat_id: 'private-chat', message_id: 'turn-response', voice_call_id: 'call-id',
    segment_id: 'd'.repeat(64), kind: 'voice_prose_turn', sequence: 0, attempt_id: 'turn-attempt',
    source_version: 1, execution_version: 2 };
  const members = [0, 1].map(sequence => ({ segment_id: String(sequence + 1).repeat(64), sequence,
    kind: 'voice_prose_clause', source_version: 1 }));
  const receive = (phase, fields = {}) => browser.socket.receive('assistant_speech_audio', {
    ...identity, phase, chunk_index: phase === 'start' || phase === 'chunk' ? 0 : 1,
    ...(phase === 'chunk' ? { audio_data: encodedAudio } : {}), ...fields,
  });
  receive('start'); receive('chunk');
  player.src = browser.createMediaSourceURL();
  await player.play(); await browser.settle(); player.currentTime = 0.2; browser.tick();
  const first = browser.playback()[0];
  const seal = (fields = {}, socket = browser.socket) => socket.receive('assistant_speech_status', {
    ...identity, kind: undefined, segment_id: undefined, status: 'sealed', turn_track_id: identity.segment_id,
    segments: members, ...fields,
  });
  const sendHeard = (completed, active = null, offset = 0) => browser.socket.send(JSON.stringify({
    type: 'chat_message_added', payload: { chat_id: identity.chat_id, message_id: 'next-request', role: 'user',
      voice_heard_boundary: { assistant_message_id: identity.message_id,
        completed_sequences: completed, active_sequence: active, active_offset_ms: offset } },
  }));
  return { browser, player, identity, members, receive, first, seal, sendHeard };
}

test('continuous turn preserves exact byte/native provenance and separates track identity from sealed clauses', async () => {
  const { browser, player, first, receive, seal, members } = await continuousBrowser();
  assert.equal(first.kind, 'voice_prose_turn');
  assert.equal(continuousTurnMetrics(browser.api.state, first).continuousPlaybackComplete, false);
  seal();
  let proof = continuousTurnMetrics(browser.api.state, first);
  assert.equal(proof.semanticMemberCount, 2);
  assert.deepEqual(proof.completedSemanticSequences, [], 'the audio track sequence zero is not heard clause zero');
  browser.tick(); receive('end');
  assert.equal(progressivePlaybackMetrics(browser.api.state, first).playbackBeforeSameSegmentProviderEnd, true);
  assert.equal(responsePlaybackComplete(browser.api.state, first), false, 'provider end is not native playback end');
  player.currentTime = 3; player.finish();
  proof = continuousTurnMetrics(browser.api.state, first);
  assert.equal(proof.continuousSingleNativeSource, true);
  assert.equal(proof.continuousPlaybackComplete, true);
  assert.deepEqual(proof.completedSemanticSequences, members.map(row => row.sequence));
  assert.equal(responsePlaybackComplete(browser.api.state, first), true);
  assert.equal(browser.playback().filter(row => row.type === 'first_progress').length, 1);
  const receipt = JSON.stringify(browser.api.snapshot());
  for (const secret of [encodedAudio, 'audio_data', 'private-chat', 'turn-response', crypto.createHash('sha256')
    .update(Buffer.from(encodedAudio, 'base64')).digest('hex')]) assert.equal(receipt.includes(secret), false);
});

test('unknown turn alignment accepts an explicit empty partial heard boundary and rejects track-as-clause claims', async () => {
  const { browser, first, sendHeard } = await continuousBrowser();
  sendHeard([]);
  assert.equal(validateObservedHeardBoundaries(browser.api.state), true);
  assert.deepEqual(continuousTurnMetrics(browser.api.state, first).completedSemanticSequences, []);
  sendHeard([0]);
  assert.equal(validateObservedHeardBoundaries(browser.api.state), false);
});

test('known immutable timing grants partial heard only after the correlated native clock crosses it', async () => {
  const { browser, player, identity, members, receive, sendHeard, first } = await continuousBrowser();
  for (const member of members) browser.socket.receive('assistant_speech_status', {
    ...identity, ...member, status: 'queued',
  });
  receive('alignment', { clause_timings: members.map((member, index) => ({
    segment_id: member.segment_id, sequence: index, start_ms: index * 1000, end_ms: (index + 1) * 1000,
  })) });
  player.currentTime = 1.2; browser.tick();
  sendHeard([0], 1, 200);
  assert.equal(validateObservedHeardBoundaries(browser.api.state), true);
  assert.deepEqual(continuousTurnMetrics(browser.api.state, first).completedSemanticSequences, [0]);
  player.currentTime = 1.8; browser.tick();
  assert.equal(validateObservedHeardBoundaries(browser.api.state), true, 'later clock samples must not erase exact send-time proof');
  sendHeard([0, 1]);
  assert.equal(validateObservedHeardBoundaries(browser.api.state), false);
});

for (const mismatch of ['track', 'socket', 'source', 'message', 'call', 'failed', 'members', 'unsealed']) {
  test(`continuous native end cannot complete semantic membership for ${mismatch}`, async () => {
    const { browser, player, first, receive, seal } = await continuousBrowser();
    if (mismatch !== 'unsealed') {
      const fields = { track: { turn_track_id: 'wrong-track' }, source: { source_version: 99 },
        message: { message_id: 'other-message' }, call: { voice_call_id: 'other-call' },
        failed: { error: 'Speech is temporarily unavailable.' }, members: { segments: [{ segment_id: 'x', sequence: 0, kind: 'voice_prose_turn', source_version: 1 }] } }[mismatch] ?? {};
      seal(fields, mismatch === 'socket' ? browser.connectSocket() : browser.socket);
    }
    browser.tick(); receive('end'); player.currentTime = 3; player.finish();
    const proof = continuousTurnMetrics(browser.api.state, first);
    assert.equal(proof.continuousPlaybackComplete, false);
    assert.deepEqual(proof.completedSemanticSequences, []);
  });
}

for (const failure of ['provider-error', 'cancelled', 'invalidated']) {
  test(`continuous ${failure} fences completion even with a late clean end and seal`, async () => {
    const { browser, player, first, identity, receive, seal } = await continuousBrowser();
    if (failure === 'provider-error') receive('error');
    else browser.socket.receive('assistant_speech_status', { ...identity, status: failure });
    browser.tick(); receive('end'); seal(); player.currentTime = 2; player.finish();
    assert.equal(continuousTurnMetrics(browser.api.state, first).continuousPlaybackComplete, false);
  });
}

test('continuous native-ended before seal waits for membership and rejects a conflicting later seal', async () => {
  const { browser, player, first, receive, seal, members } = await continuousBrowser();
  browser.tick(); receive('end'); player.currentTime = 2; player.finish();
  assert.equal(responsePlaybackComplete(browser.api.state, first), false);
  seal(); assert.equal(responsePlaybackComplete(browser.api.state, first), true);
  seal({ segments: [members[0]] });
  assert.equal(responsePlaybackComplete(browser.api.state, first), false);
});

test('new response and wrong attempt/version end cannot complete the prior native source', async () => {
  const { browser, player, first, receive, seal } = await continuousBrowser();
  seal();
  for (const fields of [{ message_id: 'next-response' }, { attempt_id: 'stale-attempt' }, { execution_version: 99 }]) {
    receive('end', fields);
  }
  player.currentTime = 2; player.finish();
  assert.equal(responsePlaybackComplete(browser.api.state, first), false);
  assert.equal(progressivePlaybackMetrics(browser.api.state, first).sameSegmentProviderEndMs, null);
});

test('continuous second native source for the same track is not one-source completion', async () => {
  const { browser, player, first, receive, seal } = await continuousBrowser();
  const second = new browser.Audio(); second.src = browser.createMediaSourceURL();
  await second.play(); await browser.settle(); second.currentTime = 0.3; browser.tick();
  receive('end'); seal(); player.currentTime = 2; player.finish(); second.finish();
  assert.equal(continuousTurnMetrics(browser.api.state, first).continuousSingleNativeSource, false);
  assert.equal(responsePlaybackComplete(browser.api.state, first), false);
});

test('missing partial heard coverage after continuous playback began fails closed', async () => {
  const { browser, identity } = await continuousBrowser();
  browser.socket.send(JSON.stringify({ type: 'chat_message_added', payload: {
    chat_id: identity.chat_id, message_id: 'next-request', role: 'user',
  } }));
  assert.equal(validateObservedHeardBoundaries(browser.api.state), false);
});
