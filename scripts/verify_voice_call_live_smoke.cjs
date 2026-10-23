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
 *           --latency-limit-ms N --require-progressive --headed
 * --require-progressive requires native MSE playback before that same provider
 * attempt ends and rejects generated audio asset publication for live clauses.
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
 * A completion CAS is handled only after its same-socket, exact-owner version
 * refresh, one matching retry and authoritative terminal ACK within 30 seconds.
 * UI errors and every other/unresolved revision conflict remain fatal. Every
 * observed metadata job must also have an exact terminal receipt before passing.
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
    if (name === 'headed' || name === 'require-progressive') { args[name] = true; continue; }
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
  // Only a completion CAS with the exact refresh/retry/terminal receipt can
  // recover. Other conflicts (including metadata/output CAS) remain fatal.
  state.recoveryRequests = []; state.recoveryConflicts = []; state.metadataJobs = [];
  const requests = new Map(), conflicts = new Map(), metadataJobs = new Map();
  let nextSocket = 0, mainSocketId = null, mainApiOrigin = null, nextRefresh = 0;
  const validId = value => typeof value === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(value);
  const version = value => Number.isSafeInteger(value) && value >= 0;
  const fatalRecovery = code => { state.revisionConflict = true; state.recoveryFailureCode ??= code; };
  const expireRecovery = () => {
    for (const conflict of conflicts.values()) if (conflict.view.status === 'pending' && now() > conflict.deadline) {
      conflict.view.status = 'failed'; fatalRecovery('recovery_conflict_unresolved');
    }
  };
  const operations = {
    recovery_job_claim: ['claim_completion', 'recovery_job_claimed'],
    recovery_job_persist: ['persist_terminal', 'recovery_job_persisted'],
    recovery_output_get: ['refresh_output', 'recovery_output_ready'],
    recovery_output_persist_message: ['persist_output_message', 'recovery_output_persisted'],
    recovery_output_persist_summary: ['persist_output_summary', 'recovery_output_summary_persisted'],
    metadata_job_claim: ['claim_metadata', 'metadata_job_claimed'],
    metadata_job_persist: ['persist_metadata', 'metadata_job_persisted'],
  };
  const recoveryAcks = new Set(Object.values(operations).map(value => value[1]));
  const observeRecovery = (type, payload, direction, socketId) => {
    expireRecovery();
    if (direction === 'received' && type === 'metadata_jobs_available') {
      if (!Array.isArray(payload.jobs) || payload.jobs.length > 100) { fatalRecovery('metadata_job_scope_unavailable'); return {}; }
      for (const job of payload.jobs) {
        if (!job || typeof job !== 'object' || Array.isArray(job) || !validId(job.job_id) || !validId(job.chat_id) || !validId(job.task_id)
          || !['initial', 'postprocessing'].includes(job.stage) || !version(job.chat_key_version)) {
          fatalRecovery('metadata_job_scope_unavailable'); continue;
        }
        const prior = metadataJobs.get(job.job_id);
        if (prior && (prior.chat !== job.chat_id || prior.task !== job.task_id || prior.stage !== job.stage
          || prior.keyVersion !== job.chat_key_version)) { fatalRecovery('metadata_job_scope_changed'); continue; }
        if (!prior) {
          const view = { jobId: id(job.job_id), chatId: id(job.chat_id), taskId: id(job.task_id),
            stage: job.stage, keyVersion: job.chat_key_version, terminal: false };
          metadataJobs.set(job.job_id, { chat: job.chat_id, task: job.task_id, stage: job.stage,
            keyVersion: job.chat_key_version, view }); state.metadataJobs.push(view);
        }
      }
    }
    if (direction === 'sent' && operations[type]) {
      const [operation, ack] = operations[type];
      const message = payload.encrypted_assistant_message ?? payload.encrypted_user_message;
      const job = payload.job_id ?? payload.record_id;
      const metadata = metadataJobs.get(job);
      const chat = message?.chat_id ?? metadata?.chat;
      const view = { requestId: id(payload.request_id), jobId: id(payload.job_id), recordId: id(payload.record_id),
        chatId: id(chat), messageId: id(message?.client_message_id), operation, atMs: now(), socketId,
        expectedVersion: version(payload.expected_messages_v) ? payload.expected_messages_v
          : version(payload.expected_metadata_v) ? payload.expected_metadata_v : undefined, acknowledged: false };
      if (!validId(payload.request_id) || !validId(job) || requests.has(payload.request_id) || requests.size >= 256) {
        fatalRecovery('recovery_request_identity_invalid'); return {};
      }
      const request = { job, chat, message: message?.client_message_id, type, ack, socketId, view };
      requests.set(payload.request_id, request); state.recoveryRequests.push(view);
      const pending = [...conflicts.values()].filter(item => item.view.status === 'pending' && item.request.job === job);
      for (const conflict of pending) {
        if (conflict.retry || type !== 'recovery_job_persist' || request.type !== conflict.request.type
          || request.socketId !== conflict.request.socketId || request.socketId !== mainSocketId || request.chat !== conflict.request.chat
          || request.message !== conflict.request.message || !conflict.refresh
          || view.expectedVersion !== conflict.refresh.version) {
          fatalRecovery('recovery_retry_scope_mismatch'); continue;
        }
        conflict.retry = payload.request_id; conflict.view.retryRequestId = view.requestId;
        conflict.view.retryExpectedVersion = view.expectedVersion;
      }
      return { ...view };
    }
    if (direction === 'received' && type === 'error' && payload.code === 'version_conflict') {
      const request = requests.get(payload.request_id);
      if (!request || request.socketId !== socketId || socketId !== mainSocketId || request.type !== 'recovery_job_persist'
        || payload.job_id !== request.job || !validId(request.chat) || !validId(request.message)
        || !version(request.view.expectedVersion)
        || [...conflicts.values()].some(item => item.request.job === request.job)) {
        fatalRecovery('recovery_conflict_unscoped'); return {};
      }
      const view = { conflictId: id(payload.request_id), jobId: id(request.job), chatId: id(request.chat),
        messageId: id(request.message), operation: 'persist_terminal', requestId: request.view.requestId,
        expectedVersion: request.view.expectedVersion, atMs: now(), status: 'pending' };
      conflicts.set(payload.request_id, { request, view, deadline: now() + 30000 }); state.recoveryConflicts.push(view);
      return { recoveryConflictId: view.conflictId, ...view };
    }
    if (direction === 'received' && recoveryAcks.has(type)) {
      const request = requests.get(payload.request_id);
      const identity = payload.job_id ?? payload.record_id;
      const related = [...conflicts.values()].find(item => item.request.job === identity);
      const fields = { requestId: id(payload.request_id), jobId: id(payload.job_id), recordId: id(payload.record_id),
        chatId: id(payload.chat_id ?? payload.target_chat_id), operation: request?.view.operation, state: typeof payload.state === 'string' ? word(payload.state.toLowerCase()) : undefined,
        committedVersion: version(payload.committed_messages_v) ? payload.committed_messages_v
          : version(payload.committed_metadata_v) ? payload.committed_metadata_v : undefined,
        metadataVersion: version(payload.versions?.metadata_v) ? payload.versions.metadata_v : undefined,
        titleVersion: version(payload.versions?.title_v) ? payload.versions.title_v : undefined,
        taskId: id(payload.task_id), stage: ['initial', 'postprocessing'].includes(payload.stage) ? payload.stage : undefined,
        keyVersion: version(payload.chat_key_version) ? payload.chat_key_version : undefined };
      if (!request || request.ack !== type || request.job !== identity || request.socketId !== socketId || socketId !== mainSocketId) {
        if (request || related || type.startsWith('metadata_job_') || type === 'recovery_job_persisted'
          && [...conflicts.values()].some(item => item.view.status === 'pending')) fatalRecovery('recovery_ack_identity_mismatch');
        return fields;
      }
      request.view.acknowledged = true;
      if (type === 'recovery_job_persisted') {
        const valid = payload.state === 'TERMINAL' && version(payload.committed_messages_v)
          && payload.committed_messages_v >= request.view.expectedVersion
          && (payload.chat_id === undefined || payload.chat_id === request.chat);
        if (!valid) fatalRecovery('recovery_ack_not_terminal');
        if (related) {
          if (!valid || related.view.status !== 'pending' || related.retry !== payload.request_id || !related.refresh) {
            fatalRecovery('recovery_ack_wrong_retry');
          } else {
            related.view.status = 'resolved'; related.view.resolvedAtMs = now();
            related.view.committedVersion = payload.committed_messages_v;
          }
        }
      }
      if (type === 'recovery_output_persisted' || type === 'recovery_output_summary_persisted') {
        const committed = type === 'recovery_output_persisted' ? payload.committed_messages_v : payload.committed_metadata_v;
        if (payload.state !== 'ACKNOWLEDGED' || !version(committed)) fatalRecovery('recovery_output_ack_not_terminal');
      }
      if (type.startsWith('metadata_job_')) {
        const metadata = metadataJobs.get(identity);
        const matches = metadata && payload.chat_id === metadata.chat && payload.task_id === metadata.task
          && payload.stage === metadata.stage && payload.chat_key_version === metadata.keyVersion;
        if (!matches) fatalRecovery('metadata_ack_scope_mismatch');
        else if (payload.state === 'TERMINAL') {
          if (type === 'metadata_job_persisted' && (!version(payload.versions?.metadata_v)
            || !version(payload.versions?.title_v) || !payload.encrypted_metadata
            || typeof payload.encrypted_metadata !== 'object' || Array.isArray(payload.encrypted_metadata)
            || !Object.keys(payload.encrypted_metadata).length
            || Object.entries(payload.encrypted_metadata).some(([field, value]) =>
              !['encrypted_title', 'encrypted_chat_summary', 'encrypted_category', 'encrypted_icon'].includes(field)
              || typeof value !== 'string' || !value))) fatalRecovery('metadata_ack_not_authoritative');
          else { metadata.view.terminal = true; metadata.view.terminalAtMs = now(); }
        } else if (type === 'metadata_job_persisted') fatalRecovery('metadata_ack_not_terminal');
      }
      return fields;
    }
    return {};
  };
  // The completion retry refresh is a real first-party authorized HTTP read.
  // Inspect only identity/version from the JSON actually consumed by the app.
  if (typeof window.fetch === 'function') {
    const nativeFetch = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const url = new URL(typeof input === 'string' || input instanceof URL ? String(input) : input.url, location.href);
      const match = /^\/v1\/chats\/([A-Za-z0-9_-]+)\/messages\/window$/.exec(url.pathname);
      const candidates = match && url.origin === mainApiOrigin && String(init?.method ?? input?.method ?? 'GET').toUpperCase() === 'GET'
        && init?.credentials === 'include' && init?.cache === 'no-store' && [...url.searchParams.keys()].length === 2
        && url.searchParams.get('limit') === '1'
        && url.searchParams.get('respect_compression_boundary') === 'false'
        ? [...conflicts.values()].filter(item => item.view.status === 'pending' && item.request.chat === match[1]) : [];
      const conflict = candidates.length === 1 ? candidates[0] : null;
      const refreshId = conflict ? `refresh-${++nextRefresh}` : null;
      if (candidates.length > 1) fatalRecovery('recovery_refresh_ambiguous');
      if (conflict) add({ type: 'recovery_chat_version_refresh', direction: 'sent', operation: 'refresh_chat_version',
        refreshId, jobId: conflict.view.jobId, chatId: conflict.view.chatId });
      const response = await nativeFetch(input, init);
      if (conflict) {
        const json = response.json.bind(response);
        response.json = async () => {
          const body = await json(); expireRecovery();
          if (!response.ok || body?.chat_id !== conflict.request.chat || !version(body?.messages_v)
            || conflict.view.status !== 'pending' || mainSocketId !== conflict.request.socketId) {
            fatalRecovery('recovery_refresh_not_authoritative');
          } else {
            conflict.refresh = { version: body.messages_v, refreshId };
            conflict.view.refreshId = refreshId; conflict.view.refreshVersion = body.messages_v;
          }
          add({ type: 'recovery_chat_version_refresh', direction: 'received', operation: 'refresh_chat_version',
            refreshId, jobId: conflict.view.jobId, chatId: conflict.view.chatId,
            successful: response.ok && body?.chat_id === conflict.request.chat && version(body?.messages_v),
            messagesVersion: version(body?.messages_v) ? body.messages_v : undefined });
          return body;
        };
      }
      return response;
    };
  }
  const interesting = new Set(['start', 'ready', 'transcript', 'chat_message_added', 'chat_message_confirmed',
    'assistant_speech_status', 'assistant_speech_audio', 'ai_message_update', 'audio.interrupted', 'stop', 'ended', 'error',
    'ai_task_failed', 'ai_task_completed', 'cancel_ai_task', 'ai_task_cancel_requested', 'hangup', 'call_message_confirmed', 'metadata_jobs_available', ...Object.keys(operations), ...recoveryAcks]);
  const segments = new Map(), streamSegments = new Map(), mediaSourceUrls = new Set();
  const createObjectURL = URL.createObjectURL;
  if (createObjectURL) URL.createObjectURL = function (object) {
    const url = createObjectURL.call(this, object);
    if (typeof MediaSource !== 'undefined' && object instanceof MediaSource) mediaSourceUrls.add(url);
    return url;
  };
  const NativeSocket = window.WebSocket;
  window.WebSocket = new Proxy(NativeSocket, { construct(Target, args) {
    const socket = Reflect.construct(Target, args);
    const pathname = new URL(String(args[0]), location.href).pathname;
    const socketId = ++nextSocket;
    if (pathname === '/v1/ws') { mainSocketId = socketId; mainApiOrigin = new URL(String(args[0])).origin.replace(/^ws/, 'http'); }
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
      const recovery = pathname === '/v1/ws' ? observeRecovery(event.type, payload, direction, socketId) : {};
      if ((['version_conflict', 'call_message_revision_conflict', 'revision_conflict'].includes(payload.code)
        || ['version_conflict', 'call_message_revision_conflict', 'revision_conflict'].includes(payload.outcome))
        && !recovery.recoveryConflictId) state.revisionConflict = true;
      if (direction === 'sent' && event.type === 'mic_audio') { state.microphoneFrames++; return; }
      if (!interesting.has(event.type)) return;
      const message = payload.message ?? payload;
      const frame = { direction, path: pathname, type: event.type, socketId,
        jobId: id(payload.job_id), recordId: id(payload.record_id), requestId: id(payload.request_id),
        chatId: id(payload.chat_id ?? message.chat_id), operation: requests.get(payload.request_id)?.view.operation, ...recovery,
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
      if (event.type === 'assistant_speech_audio') {
        const item = { ...frame, segmentId: id(payload.segment_id), kind: word(payload.kind),
          phase: ['start', 'chunk', 'end', 'error'].includes(payload.phase) ? payload.phase : undefined,
          attemptId: id(payload.attempt_id), chunkIndex: Number.isSafeInteger(payload.chunk_index) ? payload.chunk_index : undefined,
          sourceVersion: Number.isSafeInteger(payload.source_version) ? payload.source_version : undefined,
          executionVersion: Number.isSafeInteger(payload.execution_version) ? payload.execution_version : undefined,
          sequence: Number.isSafeInteger(payload.sequence) ? payload.sequence : undefined };
        // Never copy, decode or persist audio_data, URLs, transcripts or keys.
        if (item.segmentId && item.phase === 'start') streamSegments.set(item.segmentId, item);
        add(item); return;
      }
      if (event.type === 'assistant_speech_status') {
        const statuses = Array.isArray(payload.segments) ? payload.segments : [payload];
        for (const status of statuses) {
          const item = { ...frame, segmentId: id(status.segment_id), speechStatus: word(status.status ?? payload.status),
            kind: word(status.kind ?? payload.kind), generatedAssetPresent: !!status.generated_asset_id };
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
  // Exact public cue from AssistantSpeechQueue.primeForAutoplay(). This silent
  // gesture-unlock clip precedes any response and has no segment identity.
  // Do not exempt arbitrary data URLs, blob URLs or uncorrelated real audio.
  const silentAutoplayPrime = 'data:audio/wav;base64,UklGRnQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YVAAAACAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgA==';
  const play = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function (...args) {
    if (!(this instanceof HTMLAudioElement)) return play.apply(this, args);
    if (this.src === silentAutoplayPrime) {
      state.ignoredSilentAutoplayPrimes = (state.ignoredSilentAutoplayPrimes ?? 0) + 1;
      return play.apply(this, args);
    }
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
          const activeId = id(raw), segment = { ...streamSegments.get(activeId), ...segments.get(activeId) };
          if (generation.candidate !== activeId) generation.candidate = activeId;
          else if ((segment.speechStatus === 'ready' || mediaSourceUrls.has(audio.src) && streamSegments.has(activeId))
            && audio.src.startsWith('blob:')
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
            messageId: binding.messageId, kind: binding.kind, attemptId: binding.attemptId,
            sourceKind: mediaSourceUrls.has(generation.source) ? 'media_source' : 'stored_blob' });
          generation.reported = true;
        }
        if (ended) {
          if (binding) state.playback.push({ atMs: now(), type: 'ended', mediaId: observation.mediaId,
            generation: generation.ordinal, segmentId: binding.segmentId, messageId: binding.messageId,
            sourceId: id(generation.source), kind: binding.kind, currentTimeSeconds: current, progressed: !!generation.reported,
            sourceKind: mediaSourceUrls.has(generation.source) ? 'media_source' : 'stored_blob' });
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
  const inspectUi = () => {
    expireRecovery();
    const bar = document.querySelector('[data-testid="voice-call-bar"]');
    if (bar && bar.getAttribute('aria-busy') === 'false') state.callSeen = true;
    if (state.callSeen && !state.expectedHangup && (!bar || document.querySelector('[data-testid="voice-call-error"]'))) state.unexpectedEnd = true;
    // Only known static failure text is inspected; arbitrary notification text
    // never leaves the page. Protocol conflict codes are observed above too.
    const notifications = [...document.querySelectorAll('[data-testid="notification"]')];
    if (notifications.some(node => node.classList?.contains('notification-error'))) state.uiErrorNotification = true;
    if (notifications.some(node =>
      /call_message_revision_conflict|version_conflict|revision_conflict|revision conflict/i.test(node.textContent ?? ''))) state.revisionConflict = true;
  };
  setInterval(inspectUi, 100);
  window.__voiceLiveSmoke = {
    state, playInput: index => playInput(index),
    stage: value => { state.stage = value; },
    snapshot: () => { inspectUi(); return ({ ...state, snapshotMs: now(),
      recoveryPending: new Set([
        ...[...conflicts.values()].filter(item => item.view.status !== 'resolved').map(item => item.request.job),
        ...[...requests.entries()].filter(([requestId, request]) =>
          ['recovery_job_persist', 'recovery_output_persist_message', 'recovery_output_persist_summary'].includes(request.type)
          && !request.view.acknowledged && !conflicts.has(requestId)).map(([, request]) => request.job),
      ]).size,
      metadataPending: state.metadataJobs.filter(item => !item.terminal).length, activeMedia: [...media].filter(audio => !audio.paused && !audio.ended).length,
      callActive: !!document.querySelector('[data-testid="voice-call-bar"]'),
      callError: !!document.querySelector('[data-testid="voice-call-error"]'),
      playerStatus: word(document.querySelector('[data-testid="assistant-speech-player"]')?.getAttribute('data-status')),
      userRowIds: [...document.querySelectorAll('[data-testid="message-user"]')].map(row => id(row.getAttribute('data-message-id'))),
      assistantRowIds: [...document.querySelectorAll('[data-testid="message-assistant"]')].map(row => id(row.getAttribute('data-message-id'))),
    }); },
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

function progressivePlaybackMetrics(state, firstAudio) {
  const sameSegment = state.events.filter(event => event.segmentId === firstAudio.segmentId
    && event.messageId === firstAudio.messageId
    && (event.type !== 'assistant_speech_audio' || !firstAudio.attemptId || event.attemptId === firstAudio.attemptId));
  const ready = sameSegment.find(event => event.type === 'assistant_speech_status' && event.speechStatus === 'ready');
  const chunk = sameSegment.find(event => event.type === 'assistant_speech_audio' && event.phase === 'chunk');
  const end = sameSegment.find(event => event.type === 'assistant_speech_audio' && event.phase === 'end');
  return {
    firstActualPlaybackSegmentId: firstAudio.segmentId,
    firstActualPlaybackSourceKind: firstAudio.sourceKind,
    speechReadyMs: ready?.atMs ?? null,
    sameSegmentFirstAudioChunkMs: chunk?.atMs ?? null,
    sameSegmentProviderEndMs: end?.atMs ?? null,
    playbackBeforeSameSegmentProviderEnd: !!end && !!chunk && firstAudio.sourceKind === 'media_source'
      && chunk.atMs <= firstAudio.atMs && firstAudio.atMs < end.atMs,
    sameSegmentPlaybackLeadMs: end ? end.atMs - firstAudio.atMs : null,
    generatedCallAssetStatusCount: state.events.filter(event => event.type === 'assistant_speech_status'
      && event.messageId === firstAudio.messageId && event.generatedAssetPresent).length,
  };
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
      turnTimeoutMs: args['turn-timeout-ms'], firstAudioLimitMs: args['latency-limit-ms'],
      requireProgressive: args['require-progressive'] === true }, turns: [] };
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
      check(!state.uiErrorNotification, 'ui_error_notification_observed');
      check(!state.events.some(event => event.type === 'error' && !event.recoveryConflictId || event.type === 'socket_error' || event.type === 'media_error'
        || event.type === 'media_correlation_failed' || event.type === 'ai_task_failed'
        || event.type === 'assistant_speech_audio' && event.phase === 'error'), 'transport_or_media_error');
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
      const speech = state.events.filter(event => event.type === 'assistant_speech_status' && event.messageId === done.messageId
        && event.segmentId === firstAudio.segmentId && event.kind === 'voice_prose_clause');
      Object.assign(turn, { assistantMessageId: done.messageId, canonicalResponseCompleteMs: done.atMs,
        speechQueuedMs: speech.find(event => event.speechStatus === 'queued')?.atMs ?? null,
        ...progressivePlaybackMetrics(state, firstAudio),
        firstActualPlaybackMs: firstAudio.atMs,
        firstActualPlaybackKind: 'voice_prose_clause',
        firstAnySpeechPlaybackMs: firstAnySpeech?.atMs ?? null,
        firstAnySpeechPlaybackKind: firstAnySpeech?.kind ?? null,
        finalTranscriptToFirstAudioMs: firstAudio.atMs - transcript.atMs,
        canonicalSendToFirstAudioMs: firstAudio.atMs - canonical.atMs,
        playbackEndedMs: state.playback.filter(event => event.type === 'ended' && event.messageId === done.messageId).at(-1)?.atMs ?? null,
      });
      check(turn.finalTranscriptToFirstAudioMs >= 0 && turn.canonicalSendToFirstAudioMs >= 0, 'playback_turn_correlation_invalid');
      const streamed = state.events.some(event => event.type === 'assistant_speech_audio'
        && event.segmentId === firstAudio.segmentId && event.phase === 'start');
      check(turn.speechQueuedMs !== null && (streamed ? turn.sameSegmentProviderEndMs !== null : turn.speechReadyMs !== null)
        && turn.playbackEndedMs !== null,
        'missing_speech_generation_or_playback_end_evidence');
      if (args['require-progressive']) {
        check(turn.playbackBeforeSameSegmentProviderEnd, 'actual_playback_did_not_precede_same_segment_provider_end');
        check(turn.generatedCallAssetStatusCount === 0, 'live_call_published_generated_audio_asset');
      }
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
    await stageTo('recovery_terminal_receipts');
    await wait(state => state.recoveryPending === 0 && state.metadataPending === 0, 30000, 'recovery_terminal_receipt_timeout');
    let state = await snapshot(); assertTurns(state, 2);
    check(state.recoveryConflicts.every(item => item.status === 'resolved') && state.metadataJobs.every(item => item.terminal),
      'unresolved_recovery_or_metadata_job');
    if (args['require-progressive']) {
      check(!state.events.some(event => event.type === 'assistant_speech_status'
        && event.kind === 'voice_prose_clause' && event.generatedAssetPresent), 'live_call_published_generated_audio_asset');
      const playedSegments = state.playback.filter(event => event.type === 'first_progress' && event.kind === 'voice_prose_clause')
        .map(event => event.segmentId);
      check(new Set(playedSegments).size === playedSegments.length, 'live_call_clause_played_more_than_once');
    }
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
      if (result.status === 'passed' && (result.cleanupObservation.revisionConflict || result.cleanupObservation.uiErrorNotification
        || result.cleanupObservation.recoveryPending !== 0 || result.cleanupObservation.metadataPending !== 0)) {
        result.status = 'failed'; result.failureStage = 'cleanup'; result.failureCode = 'unresolved_recovery_or_ui_error';
      }
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

module.exports = { installObservation, cleanupRealCall, progressivePlaybackMetrics };
if (require.main === module) main().catch(error => {
  console.error(/^[a-z][a-z0-9_-]{1,100}$/.test(error.message) ? error.message : 'voice_smoke_setup_failed');
  process.exitCode = 1;
});
