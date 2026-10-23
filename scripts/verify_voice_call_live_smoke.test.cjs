'use strict';
// contract-test-file: tooling
// Engineering regression for the real observer, without network or inference.
// Run: node --test scripts/verify_voice_call_live_smoke.test.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const { installObservation, cleanupRealCall, progressivePlaybackMetrics } = require('./verify_voice_call_live_smoke.cjs');

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
    play() { this.paused = false; return Promise.resolve(); }
    finish() { this.ended = true; this.paused = true; this.dispatch('ended'); }
  }
  class Audio extends Media {}
  class MediaSource {}
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
  const window = { WebSocket: Socket, addEventListener() {} };
  const sandbox = { window, document, navigator: { mediaDevices: { getUserMedia: async () => {} } },
    HTMLMediaElement: Media, HTMLAudioElement: Audio, MediaSource, URL: BrowserURL, Promise, location: { href: 'https://app.dev.openmates.org/' },
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
    createMediaSourceURL: () => BrowserURL.createObjectURL(new MediaSource()),
    waveform(value) { waveform = value; },
    tick() { time += 50; for (const callback of [...timers.values()]) callback(); },
    frame() { time += 16; for (const callback of frames.splice(0)) callback(); },
    ready(segment, message, kind) { socket.receive('assistant_speech_status', {
      message_id: message, segment_id: segment, status: 'ready', kind,
    }); return api.state.events.at(-1); },
    playback() { return JSON.parse(JSON.stringify(api.state.playback)); },
    async settle() { await Promise.resolve(); this.frame(); this.frame(); },
  };
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
  audio.src = browser.createMediaSourceURL(); browser.waveform('stream-segment');
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
  browser.socket.receive('assistant_speech_audio', { message_id: 'response-stream', segment_id: 'stream-segment', phase: 'end', attempt_id: 'attempt-1' });
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
