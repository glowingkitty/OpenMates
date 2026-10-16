/** Local-only, fail-open microphone upload gate. Audio never waits for model loading. */
export interface VoiceDetectorCallbacks {
  onResult: (probability: number, samples: number) => void;
  onFailure: () => void;
}

export interface VoiceDetector {
  push: (samples: Float32Array) => void;
  reset: () => void;
  stop: () => void;
}

interface GateOptions {
  onAudio: (data: string) => void;
  onAudioEnd: () => void;
  onState: (state: { inputIdle: boolean; userSpeaking: boolean }) => void;
  /** Fatal input/startup overflow only. Detector failures recover continuous upload. */
  onError: () => void;
  createDetector?: (callbacks: VoiceDetectorCallbacks, signal: AbortSignal) => Promise<VoiceDetector>;
}

interface Chunk { data: string; samples: number }
const RATE = 16_000;
const STARTUP_SAMPLES = RATE * 10;
const RING_SAMPLES = RATE * 0.4;
const SILENCE_SAMPLES = RATE * 5;
const MAX_PENDING_SAMPLES = RATE * 0.256;
const RESULT_TIMEOUT_MS = 250;

function unpack(data: string): { pcm: Float32Array; samples: number } {
  const bytes = atob(data);
  if (bytes.length % 2) throw new Error('Invalid PCM16');
  const pcm = new Float32Array(bytes.length / 2);
  for (let i = 0; i < pcm.length; i++) {
    const value = bytes.charCodeAt(i * 2) | (bytes.charCodeAt(i * 2 + 1) << 8);
    pcm[i] = (value >= 0x8000 ? value - 0x10000 : value) / 0x8000;
  }
  return { pcm, samples: pcm.length };
}

export class VoiceCallAudioGate {
  private started = false;
  private stopped = false;
  private live = false;
  private muted = false;
  private generation = 0;
  private loading = false;
  private loadAbort: AbortController | null = null;
  private disabled = false;
  private detector: VoiceDetector | null = null;
  private startup: Chunk[] = [];
  private startupSamples = 0;
  private ring: Chunk[] = [];
  private ringSamples = 0;
  private pendingSamples = 0;
  private lastResultAt = 0;
  private silenceSamples = 0;
  private quietSpeakingSamples = 0;
  private idle = false;
  private speaking = false;
  private streamOpen = false;
  private loadTimer: ReturnType<typeof setTimeout> | null = null;
  private healthTimer: ReturnType<typeof setInterval> | null = null;

  constructor(private options: GateOptions) {}

  /** Synchronous: importing, fetching, compiling and warming all happen in the background. */
  start(): void {
    if (this.stopped) return;
    this.started = true;
    this.loadDetector();
  }

  setLive(live: boolean): void {
    if (this.stopped || live === this.live) return;
    this.live = live;
    if (!live) {
      this.clearAudio();
      this.resetDetection();
      return;
    }
    const startup = this.startup;
    this.startup = [];
    this.startupSamples = 0;
    if (!this.muted) for (const chunk of startup) this.send(chunk.data);
    this.loadDetector();
  }

  push(data: string): void {
    if (this.stopped || this.muted) return;
    // Bound malformed/oversized input before allocating a decoded PCM array.
    if (data.length > Math.ceil(STARTUP_SAMPLES * 2 / 3) * 4) {
      this.fatal();
      return;
    }
    let decoded: ReturnType<typeof unpack>;
    try { decoded = unpack(data); }
    catch { this.fatal(); return; }
    const { samples, pcm } = decoded;
    if (!samples) return;
    if (!this.live) {
      if (this.startupSamples + samples > STARTUP_SAMPLES) { this.fatal(); return; }
      this.startup.push({ data, samples });
      this.startupSamples += samples;
      return;
    }

    // Fail open before adding audio to the ring if detector latency could exceed its history.
    if (this.detector && (samples > MAX_PENDING_SAMPLES || this.pendingSamples + samples > MAX_PENDING_SAMPLES)) {
      this.detectorFailed();
    }
    if (this.idle) this.remember({ data, samples });
    else this.send(data);
    if (this.detector) {
      if (!this.pendingSamples) this.lastResultAt = Date.now();
      this.pendingSamples += samples;
      try { this.detector.push(pcm); }
      catch { this.detectorFailed(); }
    }
  }

  setMuted(muted: boolean): void {
    if (this.stopped || muted === this.muted) return;
    this.muted = muted;
    this.clearAudio();
    this.resetDetection();
    if (muted) this.endStream();
  }

  stop(): void {
    if (this.stopped) return;
    this.stopped = true;
    this.generation++;
    this.clearTimers();
    this.loadAbort?.abort();
    this.loadAbort = null;
    this.detector?.stop();
    this.detector = null;
    this.clearAudio();
    this.setState(false, false);
  }

  private send(data: string): void {
    if (!this.live || this.muted || this.stopped) return;
    this.streamOpen = true;
    this.options.onAudio(data);
  }

  private endStream(): void {
    if (!this.streamOpen) return;
    this.streamOpen = false;
    this.options.onAudioEnd();
  }

  private setState(inputIdle: boolean, userSpeaking: boolean): void {
    if (this.idle === inputIdle && this.speaking === userSpeaking) return;
    this.idle = inputIdle;
    this.speaking = userSpeaking;
    this.options.onState({ inputIdle, userSpeaking });
  }

  private remember(chunk: Chunk): void {
    this.ring.push(chunk);
    this.ringSamples += chunk.samples;
    while (this.ringSamples > RING_SAMPLES) {
      const first = this.ring[0];
      const trim = Math.min(first.samples, this.ringSamples - RING_SAMPLES);
      this.ringSamples -= trim;
      if (trim === first.samples) this.ring.shift();
      else {
        this.ring[0] = { data: btoa(atob(first.data).slice(trim * 2)), samples: first.samples - trim };
      }
    }
  }

  private resume(): void {
    this.setState(false, this.speaking);
    const ring = this.ring;
    this.ring = [];
    this.ringSamples = 0;
    for (const chunk of ring) this.send(chunk.data);
  }

  private result(probability: number, samples: number): void {
    if (!this.detector || !this.live || this.muted) return;
    if (!Number.isFinite(probability) || probability < 0 || probability > 1 || samples !== 512 || samples > this.pendingSamples) {
      this.detectorFailed();
      return;
    }
    this.pendingSamples -= samples;
    this.lastResultAt = Date.now();
    // Ambiguous frames never count as verified silence. No minimum utterance duration:
    // a single positive 32 ms frame resumes uploads, including very short "yes"/"stop".
    if (probability >= 0.35) {
      this.silenceSamples = 0;
      this.quietSpeakingSamples = 0;
      this.setState(this.idle, true);
      if (this.idle) this.resume();
      return;
    }
    if (probability > 0.2) {
      // Uncertain frames interrupt consecutive verified quiet without declaring
      // speech or clearing an existing speaking indication. Only <= .2 is quiet.
      this.silenceSamples = 0;
      this.quietSpeakingSamples = 0;
      return;
    }
    this.silenceSamples += samples;
    this.quietSpeakingSamples += samples;
    if (this.quietSpeakingSamples >= RATE * 0.16 && this.speaking) this.setState(this.idle, false);
    if (!this.idle && this.silenceSamples >= SILENCE_SAMPLES) {
      this.setState(true, false);
      this.endStream();
    }
  }

  private loadDetector(): void {
    if (!this.started || !this.live || this.stopped || this.loading || this.detector || this.disabled) return;
    this.loading = true;
    const generation = this.generation;
    const abort = new AbortController();
    this.loadAbort = abort;
    const valid = () => !this.stopped && !this.disabled && generation === this.generation;
    this.loadTimer = setTimeout(() => { if (valid()) this.detectorFailed(); }, 30_000);
    const factory = this.options.createDetector ?? (async (callbacks: VoiceDetectorCallbacks, signal: AbortSignal) => {
      const { createVoiceCallDetector } = await import('./voiceCallDetector');
      return createVoiceCallDetector(callbacks, signal);
    });
    void Promise.resolve().then(() => factory({
      onResult: (probability, samples) => { if (valid()) this.result(probability, samples); },
      onFailure: () => { if (valid()) this.detectorFailed(); },
    }, abort.signal)).then((detector) => {
      if (!valid()) { detector.stop(); return; }
      if (this.loadTimer) clearTimeout(this.loadTimer);
      this.loadTimer = null;
      this.loading = false;
      this.detector = detector;
      this.resetDetection();
      if (!this.detector) return;
      this.healthTimer = setInterval(() => {
        if (this.pendingSamples >= 512 && Date.now() - this.lastResultAt >= RESULT_TIMEOUT_MS) this.detectorFailed();
      }, 50);
    }).catch(() => { if (valid()) this.detectorFailed(); });
  }

  private resetDetection(): void {
    this.pendingSamples = 0;
    this.silenceSamples = 0;
    this.quietSpeakingSamples = 0;
    this.lastResultAt = Date.now();
    this.setState(false, false);
    try { this.detector?.reset(); }
    catch { this.detectorFailed(); }
  }

  private detectorFailed(): void {
    if (this.disabled || this.stopped) return;
    this.disabled = true;
    this.loading = false;
    this.clearTimers();
    this.loadAbort?.abort();
    this.loadAbort = null;
    this.detector?.stop();
    this.detector = null;
    this.pendingSamples = 0;
    this.silenceSamples = 0;
    this.setState(this.idle, false);
    this.resume();
    console.warn('[VoiceCall] Local speech detection unavailable; continuing microphone upload');
  }

  private clearTimers(): void {
    if (this.loadTimer) clearTimeout(this.loadTimer);
    if (this.healthTimer) clearInterval(this.healthTimer);
    this.loadTimer = null;
    this.healthTimer = null;
  }

  private clearAudio(): void {
    this.startup = [];
    this.startupSamples = 0;
    this.ring = [];
    this.ringSamples = 0;
  }

  private fatal(): void {
    this.stop();
    this.options.onError();
  }
}
