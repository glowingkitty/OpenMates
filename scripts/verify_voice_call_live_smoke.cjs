#!/usr/bin/env node
'use strict';
/**
 * Opt-in deployed-dev REAL inference smoke. Never run in provider-fixture CI.
 * Requires Playwright + Chromium, an explicitly supplied disposable account,
 * an already isolated disposable Project, and two local WAV/MP3 utterances.
 * The caller owns account/Project provisioning, runtime leases and cleanup.
 *
 * VOICE_SMOKE_EMAIL=... VOICE_SMOKE_PASSWORD=... VOICE_SMOKE_TOTP_SECRET=... \
 * node scripts/verify_voice_call_live_smoke.cjs \
 *   --url https://app.dev.openmates.org --project-id UUID \
 *   --input-first /private/first.wav --input-second /private/second.mp3 \
 *   --output-dir /private/voice-smoke-run
 *
 * Optional: --silence-ms 45000 --min-call-ms 60000 --turn-timeout-ms 300000
 *           --latency-limit-ms N --headed
 * No .env/shared account lookup, model selection, mocked endpoints, synthetic
 * server events, text injection, assistant-text assertion, tracing, HAR or PCM
 * persistence. Inputs must themselves contain no model-routing instructions.
 *
 * Video records the actual app UI; only login input contents are concealed.
 * Use ONLY a disposable test account/Project and public synthetic input: its
 * transcripts and assistant responses will be visible in the video. The JSON
 * receipt contains timings and anonymous identities, never conversation text.
 * Native HTMLAudioElement currentTime advancement proves browser playback;
 * provider 'ready' alone never counts. No physical speaker loopback is tested.
 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');

function check(condition, code) { if (!condition) throw new Error(code); }
function argumentsForRun() {
  const args = {};
  const known = new Set(['url', 'project-id', 'input-first', 'input-second', 'output-dir',
    'silence-ms', 'min-call-ms', 'turn-timeout-ms', 'latency-limit-ms']);
  for (let i = 2; i < process.argv.length; i++) {
    const name = process.argv[i].replace(/^--/, '');
    check(process.argv[i].startsWith('--') && !(name in args), 'invalid_arguments');
    if (name === 'headed') { args.headed = true; continue; }
    check(known.has(name) && process.argv[i + 1] && !process.argv[i + 1].startsWith('--'), 'invalid_arguments');
    args[name] = process.argv[++i];
  }
  for (const name of ['url', 'project-id', 'input-first', 'input-second', 'output-dir']) check(args[name], 'missing_' + name);
  const url = new URL(args.url);
  check(url.origin === 'https://app.dev.openmates.org' && url.pathname === '/' && !url.search && !url.hash
    && !url.username && !url.password, 'deployed_dev_origin_required');
  args.url = url.origin;
  check(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(args['project-id']), 'invalid_project_id');
  for (const [key, fallback, min, max] of [
    ['silence-ms', 45000, 45000, 600000], ['min-call-ms', 60000, 60000, 1200000],
    ['turn-timeout-ms', 300000, 30000, 600000], ['latency-limit-ms', null, 1, 600000],
  ]) {
    args[key] = args[key] === undefined ? fallback : Number(args[key]);
    check(args[key] === null || Number.isSafeInteger(args[key]) && args[key] >= min && args[key] <= max, 'invalid_' + key);
  }
  return args;
}

function totp(secret) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  const normalized = secret.toUpperCase().replace(/[\s=]/g, '');
  check(/^[A-Z2-7]{16,}$/.test(normalized), 'invalid_totp_secret');
  let bits = ''; const bytes = [];
  for (const char of normalized) {
    bits += alphabet.indexOf(char).toString(2).padStart(5, '0');
    while (bits.length >= 8) { bytes.push(parseInt(bits.slice(0, 8), 2)); bits = bits.slice(8); }
  }
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const digest = crypto.createHmac('sha1', Buffer.from(bytes)).update(counter).digest();
  return String((digest.readUInt32BE(digest[19] & 15) & 0x7fffffff) % 1000000).padStart(6, '0');
}

function prepareOutput(target) {
  const repo = path.resolve(__dirname, '..');
  const common = execFileSync('git', ['rev-parse', '--path-format=absolute', '--git-common-dir'],
    { cwd: repo, encoding: 'utf8' }).trim();
  const canonical = path.dirname(common);
  const output = path.resolve(target);
  const outside = (root, candidate) => candidate !== root && !candidate.startsWith(root + path.sep);
  check(outside(repo, output) && outside(canonical, output), 'output_must_be_outside_repository');
  fs.mkdirSync(output, { recursive: true, mode: 0o700 });
  const real = fs.realpathSync(output);
  check(outside(fs.realpathSync(repo), real) && outside(fs.realpathSync(canonical), real), 'output_symlink_inside_repository');
  check(fs.readdirSync(real).length === 0, 'output_directory_must_be_empty');
  fs.chmodSync(real, 0o700);
  return real;
}

/** Runs before any page/product script. Never exports message bodies or IDs. */
function installObservation({ inputs }) {
  const state = {
    events: [], playback: [], inputs: [], captureRequests: 0, microphoneFrames: 0,
    expectedHangup: false, hangupRequested: false, callSeen: false, unexpectedEnd: false, revisionConflict: false,
    stage: 'login', nativeErrors: 0,
  };
  const ids = new Map();
  const id = value => {
    if (typeof value !== 'string' || !value || value.length > 256) return undefined;
    if (!ids.has(value)) ids.set(value, `identity-${ids.size + 1}`);
    return ids.get(value);
  };
  const now = () => performance.now();
  const word = value => typeof value === 'string' && /^[a-z_]{1,64}$/.test(value) ? value : undefined;
  const add = event => { if (state.events.length < 5000) state.events.push({ atMs: now(), ...event }); };
  const interesting = new Set(['start', 'ready', 'transcript', 'chat_message_added', 'chat_message_confirmed',
    'assistant_speech_status', 'ai_message_update', 'audio.interrupted', 'stop', 'ended', 'error',
    'ai_task_failed', 'ai_task_completed', 'cancel_ai_task', 'ai_task_cancel_requested', 'hangup', 'call_message_confirmed']);
  const segments = new Map();
  const NativeSocket = window.WebSocket;
  window.WebSocket = new Proxy(NativeSocket, { construct(Target, args) {
    const socket = Reflect.construct(Target, args);
    const pathname = new URL(String(args[0]), location.href).pathname;
    if (!['/v1/voice-call', '/v1/ws'].includes(pathname)) return socket;
    const observe = (data, direction) => {
      if (typeof data !== 'string') return;
      let event; try { event = JSON.parse(data); } catch { return; }
      if (!event || typeof event !== 'object') return;
      const payload = event.payload ?? event;
      if (direction === 'sent' && pathname === '/v1/voice-call' && event.type === 'hangup') {
        // Intent is established only by the real successful outgoing UI frame.
        state.expectedHangup = state.hangupRequested && !state.unexpectedEnd;
      }
      if (['version_conflict', 'call_message_revision_conflict', 'revision_conflict'].includes(payload.code)
        || ['version_conflict', 'call_message_revision_conflict', 'revision_conflict'].includes(payload.outcome)) state.revisionConflict = true;
      if (direction === 'sent' && event.type === 'mic_audio') { state.microphoneFrames++; return; }
      if (!interesting.has(event.type)) return;
      const message = payload.message ?? payload;
      const frame = { direction, path: pathname, type: event.type,
        messageId: id(payload.message_id ?? message.message_id), userMessageId: id(payload.user_message_id),
        assistantMessageId: id(payload.assistant_message_id), callId: id(payload.call_id ?? payload.voice_call_id),
        turnId: id(payload.turn_id), role: ['user', 'assistant'].includes(message.role) ? message.role : undefined };
      if (event.type === 'transcript') frame.final = payload.final === true;
      if (event.type === 'chat_message_added') Object.assign(frame, {
        voiceMode: message.voice_mode === true, autoSpeak: message.auto_speak_response === true,
        forcedModel: !!(message.model || message.provider || message.model_id || message.provider_id),
        heardBoundary: !!message.voice_heard_boundary,
      });
      if (event.type === 'ai_message_update') frame.final = payload.is_final_chunk === true && !payload.awaiting_async_skill_continuation;
      if (event.type === 'error') Object.assign(frame, { code: word(payload.code) ?? 'unknown', stage: word(payload.stage) });
      if (event.type === 'assistant_speech_status') {
        const statuses = Array.isArray(payload.segments) ? payload.segments : [payload];
        for (const status of statuses) {
          const item = { ...frame, segmentId: id(status.segment_id), speechStatus: word(status.status ?? payload.status),
            kind: word(status.kind ?? payload.kind) };
          if (item.segmentId) segments.set(item.segmentId, { ...segments.get(item.segmentId),
            ...Object.fromEntries(Object.entries(item).filter(([, value]) => value !== undefined)) });
          add(item);
        }
        return;
      }
      add(frame);
    };
    const send = socket.send.bind(socket);
    socket.send = data => { send(data); observe(data, 'sent'); };
    socket.addEventListener('message', event => observe(event.data, 'received'));
    socket.addEventListener('close', event => {
      add({ type: 'socket_closed', path: pathname, code: event.code, intentional: state.expectedHangup });
      if (pathname === '/v1/voice-call' && !state.expectedHangup) state.unexpectedEnd = true;
    });
    socket.addEventListener('error', () => add({ type: 'socket_error', path: pathname }));
    return socket;
  } });

  const media = new Set(); const observations = new WeakMap(); let nextMedia = 0;
  const play = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function (...args) {
    if (!(this instanceof HTMLAudioElement)) return play.apply(this, args);
    const audio = this;
    let observation = observations.get(audio);
    if (!observation) {
      observation = { mediaId: ++nextMedia, generation: null, nextGeneration: 0, interval: null, sourceSegments: new Map() };
      observations.set(audio, observation); media.add(audio);
      const inspect = ended => {
        const generation = observation.generation;
        if (!generation || audio.src !== generation.source) return;
        const current = audio.currentTime;
        if (current > generation.lastTime + 0.001 && !audio.paused && !audio.ended) {
          generation.firstProgress ??= { atMs: now(), currentTimeSeconds: current };
        }
        // play() precedes Svelte's active-waveform DOM update. Never bind the
        // preceding clip's segment to the new source, even if time has advanced.
        if (!generation.binding && generation.domSettled) {
          const raw = document.querySelector('[data-testid="assistant-speech-waveform"]')?.getAttribute('data-segment-id');
          const activeId = id(raw), segment = segments.get(activeId);
          if (generation.candidate !== activeId) generation.candidate = activeId;
          else if (segment?.speechStatus === 'ready' && audio.src.startsWith('blob:')
            && (!generation.sourceChanged || activeId !== generation.previousSegmentId)) {
            const known = observation.sourceSegments.get(generation.source);
            if (!known || known === activeId) {
              generation.binding = { ...segment };
              observation.sourceSegments.set(generation.source, activeId);
            }
          }
        }
        const binding = generation.binding;
        if (binding && generation.firstProgress && !generation.reported) {
          state.playback.push({ ...generation.firstProgress, type: 'first_progress', mediaId: observation.mediaId,
            generation: generation.ordinal, sourceId: id(generation.source), segmentId: binding.segmentId,
            messageId: binding.messageId, kind: binding.kind });
          generation.reported = true;
        }
        if (ended) {
          if (binding) state.playback.push({ atMs: now(), type: 'ended', mediaId: observation.mediaId,
            generation: generation.ordinal, segmentId: binding.segmentId, messageId: binding.messageId,
            sourceId: id(generation.source), kind: binding.kind, currentTimeSeconds: current, progressed: !!generation.reported });
          else add({ type: 'media_correlation_failed', mediaId: observation.mediaId, generation: generation.ordinal });
          generation.ended = true;
          clearInterval(observation.interval); observation.interval = null;
        }
        generation.lastTime = current;
      };
      observation.inspect = inspect;
      audio.addEventListener('timeupdate', () => inspect(false));
      // Capture runs before the queue's ended handler synchronously changes src
      // and calls play() for the next clip on this SAME element.
      audio.addEventListener('ended', () => inspect(true), { capture: true });
      audio.addEventListener('error', () => add({ type: 'media_error', mediaId: observation.mediaId, code: audio.error?.code }));
    }
    const previous = observation.generation;
    if (!previous || previous.source !== audio.src || previous.ended) {
      observation.generation = { source: audio.src, ordinal: ++observation.nextGeneration,
        sourceChanged: !!previous && previous.source !== audio.src,
        previousSegmentId: previous?.binding?.segmentId ?? previous?.candidate,
        lastTime: audio.currentTime, domSettled: false, ended: false };
      clearInterval(observation.interval);
      observation.interval = setInterval(() => { if (!audio.ended) observation.inspect(false); }, 50);
    }
    const generation = observation.generation;
    const promise = play.apply(audio, args);
    Promise.resolve(promise).then(() => {
      requestAnimationFrame(() => requestAnimationFrame(() => {
        if (observation.generation === generation && audio.src === generation.source) {
          generation.domSettled = true; observation.inspect(false);
        }
      }));
    }, () => {}); // Native play rejection remains owned by the real queue.
    return promise;
  };

  const nativeCapture = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  let playInput;
  navigator.mediaDevices.getUserMedia = async constraints => {
    if (!constraints?.audio) return nativeCapture(constraints);
    const microphone = await nativeCapture(constraints);
    state.captureRequests++;
    const audio = new AudioContext(); await audio.resume();
    const output = audio.createMediaStreamDestination();
    const nativeSource = audio.createMediaStreamSource(microphone);
    const quiet = audio.createGain(); quiet.gain.value = 0;
    nativeSource.connect(quiet); quiet.connect(output);
    const buffers = await Promise.all(inputs.map(async encoded => {
      const bytes = Uint8Array.from(atob(encoded), char => char.charCodeAt(0));
      return audio.decodeAudioData(bytes.buffer);
    }));
    if (buffers.some(buffer => buffer.duration < 1 || buffer.duration > 90)) throw new Error('input_duration_outside_1_to_90_seconds');
    state.inputDurationsSeconds = buffers.map(buffer => buffer.duration);
    let active = null; let stopped = false;
    playInput = index => {
      if (stopped || active || !buffers[index]) throw new Error('input_not_ready');
      const source = audio.createBufferSource(); source.buffer = buffers[index]; source.connect(output);
      active = source;
      const record = { ordinal: index + 1, startMs: now(), durationSeconds: source.buffer.duration };
      state.inputs.push(record);
      source.onended = () => { record.endMs = now(); source.disconnect(); active = null; };
      // Full file, real AudioContext cadence. No accelerated provider snippet.
      source.start();
    };
    const cleanup = () => {
      if (stopped) return; stopped = true;
      state.inputStopped = true;
      if (active) { active.stop(); active.disconnect(); }
      nativeSource.disconnect(); quiet.disconnect();
      microphone.getTracks().forEach(track => track.stop());
      void audio.close();
    };
    output.stream.getTracks().forEach(track => {
      const stop = track.stop.bind(track); track.stop = () => { stop(); cleanup(); };
    });
    state.inputReady = true;
    return output.stream;
  };
  window.addEventListener('error', () => state.nativeErrors++);
  window.addEventListener('unhandledrejection', () => state.nativeErrors++);

  // Conceal only credential inputs before typing. Actual call UI stays visible.
  // Opacity preserves genuine UI hit testing, focus and native input handling.
  const style = document.createElement('style');
  style.textContent = '[data-testid="login-email-input"],[data-testid="login-password-input"],[data-testid="login-otp-input"]{opacity:0!important}';
  const mount = () => {
    if (!document.documentElement) return;
    if (!style.isConnected) document.documentElement.prepend(style);
  };
  new MutationObserver(mount).observe(document, { childList: true, subtree: true }); mount();
  setInterval(() => {
    const bar = document.querySelector('[data-testid="voice-call-bar"]');
    if (bar && bar.getAttribute('aria-busy') === 'false') state.callSeen = true;
    if (state.callSeen && !state.expectedHangup && (!bar || document.querySelector('[data-testid="voice-call-error"]'))) state.unexpectedEnd = true;
    // Only known static failure text is inspected; arbitrary notification text
    // never leaves the page. Protocol conflict codes are observed above too.
    if ([...document.querySelectorAll('[data-testid="notification"]')].some(node =>
      /call_message_revision_conflict|version_conflict|revision_conflict|revision conflict/i.test(node.textContent ?? ''))) state.revisionConflict = true;
  }, 100);
  window.__voiceLiveSmoke = {
    state, playInput: index => playInput(index),
    stage: value => { state.stage = value; },
    snapshot: () => ({ ...state, snapshotMs: now(), activeMedia: [...media].filter(audio => !audio.paused && !audio.ended).length,
      callActive: !!document.querySelector('[data-testid="voice-call-bar"]'),
      callError: !!document.querySelector('[data-testid="voice-call-error"]'),
      playerStatus: word(document.querySelector('[data-testid="assistant-speech-player"]')?.getAttribute('data-status')),
      userRowIds: [...document.querySelectorAll('[data-testid="message-user"]')].map(row => id(row.getAttribute('data-message-id'))),
      assistantRowIds: [...document.querySelectorAll('[data-testid="message-assistant"]')].map(row => id(row.getAttribute('data-message-id'))),
    }),
  };
}

async function cleanupRealCall(page, snapshot) {
  const before = await snapshot();
  check(!before.unexpectedEnd && !before.callError && before.callActive, 'unexpected_call_end_before_hangup');
  const hangup = page.locator('[data-testid="voice-call-hangup"]:visible');
  check(await hangup.count() === 1, 'visible_hangup_button_required');
  await page.evaluate(() => { window.__voiceLiveSmoke.state.hangupRequested = true;
    window.__voiceLiveSmoke.stage('intentional_cleanup_hangup'); });
  await hangup.click({ timeout: 10000 });
  await page.waitForFunction(() => {
    const state = window.__voiceLiveSmoke.state;
    return !document.querySelector('[data-testid="voice-call-bar"]') && state.expectedHangup === true
      && state.inputStopped === true && !state.unexpectedEnd && !state.revisionConflict
      && state.events.some(event => event.direction === 'sent' && event.path === '/v1/voice-call' && event.type === 'hangup');
  }, null, { timeout: 10000 });
}

async function login(page, origin, credentials) {
  await page.goto(origin, { waitUntil: 'load' });
  const open = page.locator('[data-testid="banner-signup-button"]:visible,[data-testid="header-login-signup-btn"]:visible').first();
  await open.click();
  await page.getByTestId('tab-login').click();
  await page.getByTestId('login-email-input').fill(credentials.email);
  const stay = page.locator('#stayLoggedIn');
  if (await stay.count() && !await stay.isChecked()) await page.locator('label.toggle[for="stayLoggedIn"],label.toggle:has(#stayLoggedIn)').click();
  await page.getByTestId('login-continue-button').click();
  await page.getByTestId('login-password-input').fill(credentials.password);
  await page.getByTestId('login-submit-button').click();
  await page.waitForFunction(() => document.querySelector('[data-authenticated="true"]') ||
    [...document.querySelectorAll('[data-testid="login-otp-input"]')].some(input => input.getClientRects().length), null, { timeout: 45000 });
  const otp = page.getByTestId('login-otp-input');
  if (await otp.isVisible()) {
    await otp.fill(totp(credentials.secret));
    const submit = page.getByTestId('login-submit-button');
    if (await submit.isVisible()) await submit.click();
  }
  await page.locator('[data-authenticated="true"]').waitFor({ state: 'visible', timeout: 45000 });
}

async function main() {
  const args = argumentsForRun();
  const credentials = { email: process.env.VOICE_SMOKE_EMAIL, password: process.env.VOICE_SMOKE_PASSWORD,
    secret: process.env.VOICE_SMOKE_TOTP_SECRET };
  check(credentials.email && credentials.password && credentials.secret, 'explicit_voice_smoke_credentials_required');
  totp(credentials.secret); // Validate before a browser or login request is opened.
  const inputs = ['input-first', 'input-second'].map(key => {
    check(/\.(wav|mp3)$/i.test(args[key]), 'wav_or_mp3_input_required');
    const stats = fs.statSync(args[key]);
    check(stats.isFile() && stats.size > 44 && stats.size <= 32 * 1024 * 1024, 'input_size_invalid');
    return fs.readFileSync(args[key]).toString('base64');
  });
  const output = prepareOutput(args['output-dir']);
  const { chromium } = require('playwright');
  const result = { schemaVersion: 1, startedUtc: new Date().toISOString(), status: 'running',
    realInference: true, automaticRoutingRequired: true, videoContent: 'actual_app_ui_with_auth_input_masking',
    configuration: { silenceMs: args['silence-ms'], minCallMs: args['min-call-ms'],
      turnTimeoutMs: args['turn-timeout-ms'], firstAudioLimitMs: args['latency-limit-ms'] }, turns: [] };
  let browser, context, page, stage = 'launch';
  let interrupted = false;
  const onSignal = () => { interrupted = true; };
  process.on('SIGINT', onSignal); process.on('SIGTERM', onSignal);
  const stageTo = async value => { stage = value; await page.evaluate(value => window.__voiceLiveSmoke.stage(value), value); };
  const snapshot = () => page.evaluate(() => window.__voiceLiveSmoke.snapshot());
  const wait = async (predicate, timeout, failure, permitEnded = false) => {
    const until = Date.now() + timeout;
    while (Date.now() < until) {
      check(!interrupted, 'intentional_operator_interruption');
      const state = await snapshot();
      check(permitEnded || !state.unexpectedEnd, 'unexpected_call_end');
      check(!state.revisionConflict, 'revision_conflict_observed');
      check(!state.events.some(event => event.type === 'error' || event.type === 'socket_error' || event.type === 'media_error'
        || event.type === 'media_correlation_failed' || event.type === 'ai_task_failed'), 'transport_or_media_error');
      if (predicate(state)) return state;
      await page.waitForTimeout(200);
    }
    throw new Error(failure);
  };
  const finals = state => state.events.filter(event => event.direction === 'received' && event.path === '/v1/voice-call'
    && event.type === 'transcript' && event.final && event.role === 'user');
  const sends = state => state.events.filter(event => event.direction === 'sent' && event.type === 'chat_message_added');
  const assertTurns = (state, count) => {
    const transcripts = finals(state), canonical = sends(state);
    check(transcripts.length === count && new Set(transcripts.map(event => event.messageId)).size === count,
      'duplicate_or_missing_final_transcript');
    check(canonical.length === count && new Set(canonical.map(event => event.messageId)).size === count,
      'duplicate_or_missing_canonical_turn');
    check(canonical.every(event => event.messageId && transcripts.some(turn => turn.messageId === event.messageId)
      && event.voiceMode && event.autoSpeak && event.forcedModel === false), 'canonical_routing_or_identity_invalid');
    check(state.captureRequests === 1, 'microphone_restarted');
    check(state.events.filter(event => event.type === 'start' && event.direction === 'sent' && event.path === '/v1/voice-call').length === 1,
      'call_restarted');
    check(state.events.filter(event => event.type === 'ready' && event.direction === 'received' && event.path === '/v1/voice-call').length === 1,
      'call_session_restarted');
  };
  try {
    browser = await chromium.launch({ headless: !args.headed,
      args: ['--no-sandbox', '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
    context = await browser.newContext({ viewport: { width: 1280, height: 800 }, permissions: ['microphone'],
      recordVideo: { dir: output, size: { width: 1280, height: 800 } } });
    await context.addInitScript(installObservation, { inputs });
    page = await context.newPage(); page.setDefaultTimeout(30000);
    // Count only: browser console may contain credentials, transcript or URLs.
    page.on('console', message => { if (message.type() === 'error') result.consoleErrorCount = (result.consoleErrorCount ?? 0) + 1; });
    stage = 'login'; await login(page, args.url, credentials);
    await stageTo('isolated_project_new_chat');
    await page.goto(`${args.url}/#project-id=${args['project-id']}`, { waitUntil: 'domcontentloaded' });
    await page.getByTestId('project-workspace-header').waitFor({ state: 'visible' });
    await page.getByTestId('project-tab-folders').click();
    await page.getByTestId('project-folder-create-menu-button').click();
    await page.getByTestId('project-create-chat').click();
    await page.getByTestId('message-editor').waitFor({ state: 'visible' });
    await page.getByTestId('message-editor').click();
    await page.waitForFunction(() => {
      const selectors = [...document.querySelectorAll('[data-testid="composer-model-selector"]')].filter(node => node.getClientRects().length);
      return selectors.length === 1 && !selectors[0].disabled && selectors[0].getAttribute('data-loading') === 'false';
    }, null, { timeout: 30000 });
    result.uiAutomaticRouting = await page.evaluate(() => {
      const selector = [...document.querySelectorAll('[data-testid="composer-model-selector"]')].find(node => node.getClientRects().length);
      return !!selector && /^auto(?: select)?$/i.test(selector.querySelector('[data-testid="composer-model-selector-label"]')?.textContent?.trim() ?? '')
        && !selector.querySelector('[data-testid="composer-model-selector-icon"]');
    });
    check(result.uiAutomaticRouting, 'existing_ui_model_selector_must_be_auto');
    check(await page.getByTestId('message-user').count() === 0 && await page.getByTestId('message-assistant').count() === 0,
      'fresh_isolated_chat_required');
    await stageTo('real_ui_call_start_and_consent');
    await page.locator('[data-testid="voice-call-start"]:visible').click();
    await page.waitForFunction(() => document.querySelector('[data-testid="voice-call-bar"]') ||
      [...document.querySelectorAll('[data-testid="notification"]')].some(node => node.textContent.includes('Before your first voice call')),
    null, { timeout: 45000 });
    const notice = page.getByTestId('notification').filter({ hasText: 'Before your first voice call' });
    if (await notice.count()) { await notice.getByRole('button', { name: 'Continue', exact: true }).click(); result.consent = 'accepted_via_ui'; }
    else result.consent = 'previously_acknowledged';
    const connected = await wait(state => state.inputReady && state.events.some(event => event.path === '/v1/voice-call'
      && event.direction === 'received' && event.type === 'ready'), 60000, 'call_ready_timeout');
    const ready = connected.events.find(event => event.path === '/v1/voice-call' && event.type === 'ready');
    check(ready.callId, 'missing_real_call_identity');
    result.callReadyMs = ready.atMs;
    for (let ordinal = 1; ordinal <= 2; ordinal++) {
      await stageTo(`utterance_${ordinal}_full_native_audio`);
      await page.evaluate(index => window.__voiceLiveSmoke.playInput(index), ordinal - 1);
      let state = await wait(state => finals(state).length >= ordinal && sends(state).length >= ordinal,
        args['turn-timeout-ms'], 'final_transcript_or_canonical_send_timeout');
      assertTurns(state, ordinal);
      const transcript = finals(state)[ordinal - 1], canonical = sends(state).find(event => event.messageId === transcript.messageId);
      const turn = { ordinal, messageId: transcript.messageId, finalTranscriptMs: transcript.atMs, canonicalSendMs: canonical.atMs };
      result.turns.push(turn);
      await stageTo(`utterance_${ordinal}_await_real_response_playback`);
      state = await wait(state => {
        const done = state.events.find(event => event.type === 'ai_message_update' && event.final && event.userMessageId === transcript.messageId);
        const assistantId = done?.messageId;
        return assistantId && state.inputs[ordinal - 1]?.endMs !== undefined
          && state.playback.some(event => event.messageId === assistantId && event.kind === 'voice_prose_clause'
          && event.type === 'first_progress') && state.playerStatus === 'completed' && state.activeMedia === 0;
      }, args['turn-timeout-ms'], 'canonical_response_or_real_playback_timeout');
      const done = state.events.find(event => event.type === 'ai_message_update' && event.final && event.userMessageId === transcript.messageId);
      const firstAudio = state.playback.find(event => event.type === 'first_progress' && event.messageId === done.messageId && event.kind === 'voice_prose_clause');
      const firstAnySpeech = state.playback.find(event => event.type === 'first_progress' && event.messageId === done.messageId);
      const speech = state.events.filter(event => event.type === 'assistant_speech_status' && event.messageId === done.messageId && event.kind === 'voice_prose_clause');
      Object.assign(turn, { assistantMessageId: done.messageId, canonicalResponseCompleteMs: done.atMs,
        speechQueuedMs: speech.find(event => event.speechStatus === 'queued')?.atMs ?? null,
        speechReadyMs: speech.find(event => event.speechStatus === 'ready')?.atMs ?? null,
        firstActualPlaybackMs: firstAudio.atMs,
        firstActualPlaybackKind: 'voice_prose_clause',
        firstAnySpeechPlaybackMs: firstAnySpeech?.atMs ?? null,
        firstAnySpeechPlaybackKind: firstAnySpeech?.kind ?? null,
        finalTranscriptToFirstAudioMs: firstAudio.atMs - transcript.atMs,
        canonicalSendToFirstAudioMs: firstAudio.atMs - canonical.atMs,
        playbackEndedMs: state.playback.filter(event => event.type === 'ended' && event.messageId === done.messageId).at(-1)?.atMs ?? null,
      });
      check(turn.finalTranscriptToFirstAudioMs >= 0 && turn.canonicalSendToFirstAudioMs >= 0, 'playback_turn_correlation_invalid');
      check(turn.speechQueuedMs !== null && turn.speechReadyMs !== null && turn.playbackEndedMs !== null,
        'missing_speech_generation_or_playback_end_evidence');
      assertTurns(state, ordinal);
      if (ordinal === 1) {
        await stageTo('same_call_45_seconds_quiet_after_completed_playback');
        const quietStart = await page.evaluate(() => performance.now());
        result.quietStartedMs = quietStart;
        await wait(state => {
          check(state.activeMedia === 0 && !state.playback.some(event => event.atMs > quietStart), 'silence_interrupted_by_playback');
          return state.snapshotMs >= quietStart + args['silence-ms'];
        }, args['silence-ms'] + 15000, 'silence_window_timeout');
        result.quietEndedMs = await page.evaluate(() => performance.now());
        // The entire wait remained in this same call. Recheck exact turn count.
        assertTurns(await snapshot(), 1);
      }
    }
    await stageTo('same_call_minimum_duration');
    await wait(state => state.snapshotMs - ready.atMs >= args['min-call-ms'], args['min-call-ms'] + 10000, 'minimum_call_duration_timeout');
    let state = await snapshot(); assertTurns(state, 2);
    check(state.microphoneFrames > 0, 'no_real_microphone_upload_frames');
    check(!state.nativeErrors, 'browser_native_error_observed');
    check(state.userRowIds.length === 2 && new Set(state.userRowIds).size === 2
      && finals(state).every(turn => state.userRowIds.includes(turn.messageId)), 'duplicate_or_missing_user_rows');
    check(state.assistantRowIds.length === 2 && new Set(state.assistantRowIds).size === 2
      && result.turns.every(turn => state.assistantRowIds.includes(turn.assistantMessageId)), 'duplicate_or_missing_assistant_rows');
    result.callDurationMs = await page.evaluate(start => performance.now() - start, ready.atMs);
    result.measuredSilenceMs = result.quietEndedMs - result.quietStartedMs;
    result.latencyAssessment = args['latency-limit-ms'] === null ? 'measured_no_performance_threshold' :
      result.turns.every(turn => turn.finalTranscriptToFirstAudioMs <= args['latency-limit-ms']) ? 'within_configured_threshold' : 'exceeded_configured_threshold';
    check(result.latencyAssessment !== 'exceeded_configured_threshold', 'configured_first_audio_threshold_exceeded');
    result.status = 'passed';
  } catch (error) {
    result.status = interrupted ? 'interrupted' : 'failed';
    result.failureStage = stage;
    // Never serialize raw Playwright errors: locators can include rendered text,
    // URLs or credentials. Controlled error codes are safe; others are classified.
    result.failureCode = /^[a-z][a-z0-9_-]{1,100}$/.test(error.message) ? error.message : 'browser_operation_failed';
    result.failureClass = ['Error', 'TimeoutError', 'TypeError'].includes(error.name) ? error.name : 'OtherError';
  } finally {
    if (page && !page.isClosed()) {
      result.observation = await snapshot().catch(() => ({ unavailable: true }));
      try {
        await cleanupRealCall(page, snapshot);
        result.cleanupHangup = 'real_ui_hangup_frame_and_capture_stopped';
      } catch (error) {
        result.cleanupHangup = 'failed';
        if (result.status === 'passed') {
          result.status = 'failed'; result.failureStage = 'cleanup';
          result.failureCode = /^[a-z][a-z0-9_-]{1,100}$/.test(error.message) ? error.message : 'real_ui_hangup_cleanup_failed';
        }
      }
      result.cleanupObservation = await snapshot().catch(() => ({ unavailable: true }));
      const video = page.video();
      await page.close().catch(() => {});
      if (video) result.videoFile = path.basename(await video.path().catch(() => 'unavailable'));
    }
    if (context) await context.close().catch(() => {});
    if (browser) await browser.close().catch(() => {});
    result.finishedUtc = new Date().toISOString();
    for (const file of fs.readdirSync(output)) if (fs.statSync(path.join(output, file)).isFile()) fs.chmodSync(path.join(output, file), 0o600);
    fs.writeFileSync(path.join(output, 'metrics.json'), JSON.stringify(result, null, 2), { mode: 0o600 });
    process.off('SIGINT', onSignal); process.off('SIGTERM', onSignal);
  }
  console.log(JSON.stringify({ status: result.status, failureStage: result.failureStage, failureCode: result.failureCode,
    latencyAssessment: result.latencyAssessment, turns: result.turns.map(turn => ({ ordinal: turn.ordinal,
      finalTranscriptToFirstAudioMs: turn.finalTranscriptToFirstAudioMs,
      canonicalSendToFirstAudioMs: turn.canonicalSendToFirstAudioMs })) }));
  if (result.status !== 'passed') process.exitCode = 1;
}

module.exports = { installObservation, cleanupRealCall };
if (require.main === module) main().catch(error => {
  console.error(/^[a-z][a-z0-9_-]{1,100}$/.test(error.message) ? error.message : 'voice_smoke_setup_failed');
  process.exitCode = 1;
});
