import type { Page } from '@playwright/test';

export type VoiceSpeechIdentity = { callId: string; chatId: string; messageId: string; trackId: string };
type Signal = { first: number; last: number; samples: number };
type OutputSignal = Signal & { source: string; since: number; currentTime: number };

export interface RealVoicePlayback {
  playQuestion(): Promise<void>;
  snapshot(): {
    sampleRate: number; input: Signal | null; output: OutputSignal[];
    turns: { callId: string; messageId: string }[];
    cueSources: { callId: string; source: string }[];
    proseSources: { source: string; identity: VoiceSpeechIdentity }[];
    stt: { callId: string; provider: string; model: string }[];
    observerErrorCount: number;
  };
}

const METER_PATH = '/__openmates_voice_proof_meter.js';
const METER_SOURCE = `
registerProcessor('openmates-voice-proof-meter', class extends AudioWorkletProcessor {
  process(inputs) {
    const signal = inputs[0]?.[0];
    if (!signal) return true;
    let energy = 0, first = -1, last = -1;
    for (let i = 0; i < signal.length; i++) {
      const value = signal[i];
      energy += value * value;
      if (Math.abs(value) >= 0.009) {
        if (first < 0) first = i;
        last = i;
      }
    }
    if (first >= 0 && energy / signal.length > 0.000064) {
      this.port.postMessage({ first: currentFrame + first, last: currentFrame + last,
        samples: signal.length });
    }
    return true;
  }
});

`;

/** Both the microphone and playback use the same browser audio sample clock. */
export async function installRealVoicePlayback(page: Page, capitalFlac: Buffer): Promise<void> {
  // Only the meter is supplied by the test. App routes and provider traffic are real.
  await page.route(url => url.pathname === METER_PATH, route => route.fulfill({
    contentType: 'text/javascript', body: METER_SOURCE,
  }));
  await page.addInitScript(({ encodedFixture, meterPath }) => {
    const decode = (encoded: string) => Uint8Array.from(atob(encoded), char => char.charCodeAt(0));
    const audio = new AudioContext();
    const silent = audio.createGain();
    silent.gain.value = 0;
    silent.connect(audio.destination);
    let observerErrorCount = 0;
    let input: Signal | null = null;
    const output = new Map<string, OutputSignal>();
    const cueSources: ReturnType<RealVoicePlayback['snapshot']>['cueSources'] = [];
    const turns: ReturnType<RealVoicePlayback['snapshot']>['turns'] = [];
    const stt: ReturnType<RealVoicePlayback['snapshot']>['stt'] = [];
    const starts = new Set<string>();
    const wireSamples = new Map<string, VoiceSpeechIdentity | null>();
    const appendHashes = new Map<string, Set<string>>();
    let microphone: MediaStreamAudioDestinationNode | null = null;
    let played = false;

    // Observe samples in the render graph, not play() promises, incoming bytes,
    // a timer, or a playback event with a silent priming buffer.
    const meterReady = audio.audioWorklet.addModule(meterPath);
    void meterReady.catch(() => { observerErrorCount++; });
    const attach = (track: MediaStreamTrack, onSignal: (signal: Signal) => void) => {
      if (track.kind !== 'audio') return;
      void meterReady.then(() => {
        if (track.readyState !== 'live') return;
        const source = audio.createMediaStreamSource(new MediaStream([track]));
        const meter = new AudioWorkletNode(audio, 'openmates-voice-proof-meter');
        meter.port.onmessage = (event: MessageEvent<Signal>) => onSignal(event.data);
        source.connect(meter).connect(silent);
        track.addEventListener('ended', () => {
          meter.port.close();
          meter.disconnect();
          source.disconnect();
        }, { once: true });
      }).catch(() => { observerErrorCount++; });
    };

    // Retain a genuine successful browser permission request and use exactly the
    // checked-in recording for this one synthetic microphone utterance.
    const nativeCapture = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async (constraints) => {
      if (!constraints?.audio || constraints.video) return nativeCapture(constraints);
      const permission = await nativeCapture(constraints);
      permission.getAudioTracks().forEach(track => track.stop());
      if (microphone) throw new Error('Voice proof accepts one microphone setup');
      await meterReady;
      await audio.resume();
      microphone = audio.createMediaStreamDestination();
      for (const track of microphone.stream.getAudioTracks()) attach(track, (samples) => {
        if (!played) return;
        input = input ? { ...input, last: samples.last, samples: input.samples + samples.samples } : samples;
      });
      return microphone.stream;
    };

    const mediaUrls = new WeakMap<MediaSource, string>();
    const sourceOwners = new WeakMap<SourceBuffer, MediaSource>();
    const createObjectURL = URL.createObjectURL.bind(URL);
    URL.createObjectURL = (source) => {
      const url = createObjectURL(source);
      if (source instanceof MediaSource) mediaUrls.set(source, url);
      return url;
    };
    const addSourceBuffer = MediaSource.prototype.addSourceBuffer;
    MediaSource.prototype.addSourceBuffer = function (type) {
      const buffer = addSourceBuffer.call(this, type);
      sourceOwners.set(buffer, this);
      return buffer;
    };
    const digest = async (bytes: Uint8Array<ArrayBuffer>) =>
      Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), byte =>
        byte.toString(16).padStart(2, '0')).join('');
    const append = SourceBuffer.prototype.appendBuffer;
    SourceBuffer.prototype.appendBuffer = function (data) {
      const owner = sourceOwners.get(this);
      const url = owner && mediaUrls.get(owner);
      const bytes = ArrayBuffer.isView(data)
        ? new Uint8Array(data.buffer, data.byteOffset, data.byteLength).slice() : new Uint8Array(data).slice();
      append.call(this, data);
      if (!url || bytes.byteLength > 128 * 1024) return;
      void digest(bytes).then((hash) => {
        const hashes = appendHashes.get(url) ?? new Set<string>();
        if (hashes.size >= 256) return;
        hashes.add(hash);
        appendHashes.set(url, hashes);
      }).catch(() => { observerErrorCount++; });
    };

    const safePath = (value: string) => {
      const url = new URL(value, window.location.href);
      return url.origin === location.origin && url.pathname.startsWith('/audio/assistant-acknowledgements/')
        ? url.pathname : null;
    };
    const NativeSocket = window.WebSocket;
    window.WebSocket = new Proxy(NativeSocket, { construct(Target, args) {
      const socket: WebSocket = Reflect.construct(Target, args);
      const path = new URL(String(args[0]), location.href).pathname;
      if (path !== '/v1/voice-call' && path !== '/v1/ws') return socket;
      socket.addEventListener('message', ({ data }) => {
        if (typeof data !== 'string' || data.length > 256 * 1024) return;
        let event;
        try { event = JSON.parse(data); } catch { return; }
        try {
          if (path === '/v1/voice-call' && event.type === 'ready') {
            stt.push({ callId: event.call_id, provider: event.provider, model: event.model });
          }
          if (path === '/v1/voice-call' && event.type === 'transcript' && event.final && event.role === 'user') {
            turns.push({ callId: event.call_id, messageId: event.message_id });
          }
          if (path === '/v1/voice-call' && event.type === 'voice_feedback' && typeof event.clip?.asset_url === 'string') {
            const source = safePath(event.clip.asset_url);
            if (source) cueSources.push({ callId: event.call_id, source });
          }
          if (path !== '/v1/ws') return;
          if (event.type === 'assistant_speech_acknowledgement' &&
              typeof event.payload?.voice_call_id === 'string' && typeof event.payload?.audio_url === 'string') {
            const source = safePath(event.payload.audio_url);
            if (source) cueSources.push({ callId: event.payload.voice_call_id, source });
          }
          if (event.type !== 'assistant_speech_audio') return;
          const frame = event.payload;
          if (frame?.kind !== 'voice_prose_turn') return;
          const identity = { callId: frame.voice_call_id, chatId: frame.chat_id,
            messageId: frame.message_id, trackId: frame.segment_id };
          if (!Object.values(identity).every(id => typeof id === 'string' && id.length > 0 && id.length <= 128)) return;
          const key = JSON.stringify(identity);
          if (frame.phase === 'start') starts.add(key);
          if (frame.phase === 'chunk' && starts.has(key) && typeof frame.audio_data === 'string') {
            void digest(decode(frame.audio_data)).then((hash) => {
              const earlier = wireSamples.get(hash);
              if (earlier === null || earlier && JSON.stringify(earlier) !== key) wireSamples.set(hash, null);
              else if (wireSamples.size < 256) wireSamples.set(hash, identity);
            }).catch(() => { observerErrorCount++; });
          }
        } catch { observerErrorCount++; }
      });
      return socket;
    } });

    const media = new WeakSet<HTMLMediaElement>();
    const audibleSince = new WeakMap<HTMLMediaElement, number>();
    const nativePlay = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function () {
      if (this instanceof HTMLAudioElement && !media.has(this)) {
        media.add(this);
        this.addEventListener('playing', () => audibleSince.set(this, Math.round(audio.currentTime * audio.sampleRate)));
        this.addEventListener('emptied', () => audibleSince.delete(this));
        try {
          const stream = (this as HTMLAudioElement & { captureStream(): MediaStream }).captureStream();
          const inspect = (track: MediaStreamTrack) => attach(track, (samples) => {
            const since = audibleSince.get(this);
            if (since === undefined || samples.last < since || this.muted || this.volume === 0 || this.paused) return;
            const url = this.currentSrc;
            const source = url.startsWith('blob:') ? url : safePath(url);
            if (!source) return;
            const previous = output.get(source);
            output.set(source, { source, since: previous?.since ?? since, currentTime: this.currentTime,
              first: previous?.first ?? Math.max(samples.first, since),
              last: samples.last, samples: (previous?.samples ?? 0) + samples.samples });
          });
          stream.getAudioTracks().forEach(inspect);
          stream.addEventListener('addtrack', (event) => inspect(event.track));
        } catch { observerErrorCount++; }
      }
      return nativePlay.call(this);
    };

    const probe: RealVoicePlayback = {
      async playQuestion() {
        if (!microphone || played || audio.state !== 'running') throw new Error('Microphone is not ready');
        const clip = audio.createBufferSource();
        clip.buffer = await audio.decodeAudioData(decode(encodedFixture).buffer);
        clip.connect(microphone);
        // Include the approved synthetic utterance in the proof video only.
        clip.connect(audio.destination);
        played = true;
        clip.start();
      },
      snapshot() {
        const proseSources: ReturnType<RealVoicePlayback['snapshot']>['proseSources'] = [];
        for (const [source, hashes] of appendHashes) {
          const linked = [...hashes].map(hash => wireSamples.get(hash));
          const identity = linked.find(value => value !== undefined);
          if (identity && linked.every(value => value && JSON.stringify(value) === JSON.stringify(identity))) {
            proseSources.push({ source, identity });
          }
        }
        return { sampleRate: audio.sampleRate, input, output: [...output.values()], turns, cueSources,
          proseSources, stt, observerErrorCount };
      },
    };
    Object.assign(window, { __omRealVoicePlayback: probe });
  }, { encodedFixture: capitalFlac.toString('base64'), meterPath: METER_PATH });
}

export function qualifiedVoiceTiming(
  proof: Awaited<ReturnType<RealVoicePlayback['snapshot']>>,
  owner: { callId: string; chatId: string; messageId: string },
): { cueMs: number | null; substantiveMs: number; sampleRate: number } | null {
  if (proof.observerErrorCount || !proof.input || proof.input.samples < proof.sampleRate * 0.12) return null;
  const inputEnd = proof.input.last;
  const heard = proof.output.filter(span =>
    span.first >= inputEnd && span.samples >= proof.sampleRate * 0.018 && span.currentTime > 0);
  const matches = proof.proseSources.filter(({ identity }) =>
    identity.callId === owner.callId && identity.chatId === owner.chatId && identity.messageId === owner.messageId);
  const substantive = heard.filter(span => matches.some(({ source }) => source === span.source));
  if (substantive.length !== 1) return null;
  const cues = heard.filter(span => proof.cueSources.some(({ source, callId }) =>
    source === span.source && callId === owner.callId));
  const ms = (frame: number) => Math.round((frame - inputEnd) * 1000 / proof.sampleRate);
  return {
    cueMs: cues.length ? ms(Math.min(...cues.map(span => span.first))) : null,
    substantiveMs: ms(substantive[0].first), sampleRate: proof.sampleRate,
  };
}
