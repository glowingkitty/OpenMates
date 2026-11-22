/* eslint-disable @typescript-eslint/no-explicit-any -- the in-page recorder patches untyped browser globals. */
/**
 * Proof videos with sound (owner, 22 Nov 2026).
 *
 * Playwright records video without audio. For voice and audio flows this helper records what
 * the page plays inside the browser and puts it into the proof video, in sync:
 *  - every Web Audio graph connected to its context's speakers (chimes, ambient sounds, call
 *    audio), tapped per AudioContext;
 *  - every playing <audio>/<video> element (the assistant's speech, waiting clips), via
 *    captureStream when play() is called (also for elements outside the document), silent while muted;
 *  - the microphone stream the page gets from getUserMedia, i.e. the caller's side. Chromium's
 *    fake microphone plays TEST_VOICE_WAV (a spoken sentence) with proofAudioLaunchArgs(), or a
 *    scenario's own spoken question (voice-call-real.spec.ts).
 * A recorder mixes these into WebM/Opus segments (one per document) stamped with the wall-clock
 * time they started. When the test ends, the context is closed so the videos are final, every
 * page's video is copied next to the segments with a manifest, and scripts/proof_video_audio.py
 * muxes them (segment offset = segment start - page creation, which is when Playwright's video
 * starts). The muxed `video-with-audio*.webm` is attached to the test, so scripts/ci_evidence.py
 * uploads it like any other proof video. Without ffmpeg or the repository scripts (some sandboxes)
 * the manifest is attached instead and the host muxes it (ci_evidence.py, real-test runners).
 *
 * Use in a spec (default for every voice or audio flow; scripts/audit_playwright_proof_metadata.py
 * asks for it):
 *   const { test: baseTest, expect } = require('./helpers/cookie-audit');
 *   const { withProofAudio, proofAudioLaunchArgs } = require('./helpers/proof-audio');
 *   const test = withProofAudio(baseTest);
 *   test.use({ launchOptions: { args: proofAudioLaunchArgs() } });
 * Scripts that create their own contexts: `const audio = await installProofAudio(context, dir)`
 * before opening pages, then `await audio.finish()` instead of `context.close()`.
 */
import { test as playwrightTest } from '@playwright/test';
import type { BrowserContext, Page, TestInfo, TestType } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';


/** A spoken English sentence (about 5 s, 48 kHz mono) for Chromium's fake microphone. */
export const TEST_VOICE_WAV = path.resolve(__dirname, '../../static/store-examples/transcription-demo-voice-note.wav');
const MUX_SCRIPT = path.resolve(__dirname, '../../../../../scripts/proof_video_audio.py');
const MANIFEST_NAME = 'proof-audio-manifest.json';
const BINDING = '__omProofAudioChunk';
const FLUSH_TIMEOUT_MS = 10_000;

/**
 * Chromium flags for audio proofs: the fake microphone plays ``voiceWav`` (looped); ``null`` keeps
 * Chromium's built-in fake microphone (a short beep each second, silence between), for specs whose
 * voice-activity cases need that silence. ``autoplay``
 * lets audio start without a click; leave it off for product flows, whose autoplay handling is
 * part of what they test (the recorder then starts with the first click or key press).
 */
export function proofAudioLaunchArgs(
  { voiceWav = TEST_VOICE_WAV, autoplay = false }: { voiceWav?: string | null; autoplay?: boolean } = {},
): string[] {
  return [
    '--use-fake-device-for-media-stream',
    '--use-fake-ui-for-media-stream',
    ...(voiceWav ? [`--use-file-for-fake-audio-capture=${voiceWav}`] : []),
    ...(autoplay ? ['--autoplay-policy=no-user-gesture-required'] : []),
  ];
}

/** Runs in every document before the page's own scripts (serialized by addInitScript). */
function inPageRecorder(binding: string): void {
  const w = window as any;
  if (w.__omProofAudio) return;
  const Ctx = w.AudioContext || w.webkitAudioContext;
  if (!Ctx || !w.MediaRecorder) return;
  const errors: string[] = [];
  const note = (where: string, error: unknown) => { if (errors.length < 20) errors.push(`${where}: ${String(error)}`); };
  const master = new Ctx();
  const mix = master.createMediaStreamDestination();
  const connect = AudioNode.prototype.connect as any;
  const disconnect = AudioNode.prototype.disconnect as any;
  // A silent source keeps the mix running, so the recording timeline never skips silent stretches.
  const keepAlive = master.createConstantSource();
  const zero = master.createGain();
  zero.gain.value = 0;
  connect.call(keepAlive, zero);
  connect.call(zero, mix);
  keepAlive.start();

  const segment = Math.random().toString(36).slice(2, 10);
  const pending: Promise<unknown>[] = [];
  let seq = 0;
  let startedAt = 0;
  let recorder: MediaRecorder | null = null;
  let sources = 0;
  const toBase64 = (buffer: ArrayBuffer) => {
    const bytes = new Uint8Array(buffer);
    let text = '';
    for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    return btoa(text);
  };
  const start = () => {
    if (recorder || master.state !== 'running') return;
    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm';
    recorder = new MediaRecorder(mix.stream, { mimeType, audioBitsPerSecond: 128_000 });
    recorder.onstart = () => { startedAt = performance.timeOrigin + performance.now(); };
    recorder.ondataavailable = (event: BlobEvent) => {
      if (!event.data.size) return;
      const index = seq++;
      pending.push(event.data.arrayBuffer().then((buffer) =>
        w[binding]({ segment, seq: index, startedAt, data: toBase64(buffer) })).catch((e: unknown) => note('send', e)));
    };
    recorder.start(250);
  };
  master.onstatechange = start;
  start();
  if (master.state !== 'running') {
    // Without --autoplay-policy=no-user-gesture-required the first click or key starts it.
    const resume = () => { void master.resume(); };
    w.addEventListener('pointerdown', resume, { capture: true });
    w.addEventListener('keydown', resume, { capture: true });
  }

  const seenTracks = new WeakSet<MediaStreamTrack>();
  const addTrack = (track: MediaStreamTrack) => {
    if (track.kind !== 'audio' || seenTracks.has(track)) return;
    seenTracks.add(track);
    try {
      connect.call(master.createMediaStreamSource(new MediaStream([track])), mix);
      sources++;
    } catch (e) { note('source', e); }
  };
  const addStream = (stream: MediaStream) => {
    stream.getAudioTracks().forEach(addTrack);
    stream.addEventListener('addtrack', (event: MediaStreamTrackEvent) => addTrack(event.track));
  };

  // Web Audio: whatever reaches a context's speakers also reaches that context's tap.
  const taps = new WeakMap<BaseAudioContext, MediaStreamAudioDestinationNode>();
  const tapFor = (context: BaseAudioContext) => {
    let tap = taps.get(context);
    if (!tap && context instanceof Ctx && context !== master) {
      tap = (context as AudioContext).createMediaStreamDestination();
      taps.set(context, tap);
      addStream(tap.stream);
    }
    return tap;
  };
  AudioNode.prototype.connect = function (this: AudioNode, destination: any, ...rest: any[]) {
    const result = connect.call(this, destination, ...rest);
    if (destination instanceof AudioDestinationNode && destination.context !== master) {
      try {
        const tap = tapFor(destination.context);
        if (tap) connect.call(this, tap);
      } catch (e) { note('connect', e); }
    }
    return result;
  } as any;
  AudioNode.prototype.disconnect = function (this: AudioNode, ...args: any[]) {
    const result = disconnect.apply(this, args);
    const destination = args[0];
    if (destination instanceof AudioDestinationNode) {
      const tap = taps.get(destination.context);
      if (tap) try { disconnect.call(this, tap); } catch { /* the node was not connected to the tap */ }
    }
    return result;
  } as any;

  // Media elements: captured on play, silent while muted, skipped when routed into Web Audio.
  const elementTracks = new WeakMap<HTMLMediaElement, MediaStreamTrack[]>();
  const routed = new WeakSet<HTMLMediaElement>();
  const createElementSource = (Ctx.prototype as any).createMediaElementSource;
  if (createElementSource) {
    (Ctx.prototype as any).createMediaElementSource = function (element: HTMLMediaElement) {
      routed.add(element);
      (elementTracks.get(element) || []).forEach((track) => { track.enabled = false; });
      return createElementSource.call(this, element);
    };
  }
  const audible = (element: HTMLMediaElement) => !element.muted && element.volume > 0 && !routed.has(element);
  const syncEnabled = (element: HTMLMediaElement) =>
    (elementTracks.get(element) || []).forEach((track) => { track.enabled = audible(element); });
  const captureElement = (element: HTMLMediaElement) => {
    // Chromium only: Firefox's mozCaptureStream would silence the element's own playback.
    if (elementTracks.has(element) || routed.has(element) || !(element as any).captureStream) return;
    try {
      const stream: MediaStream = (element as any).captureStream();
      const tracks: MediaStreamTrack[] = [];
      elementTracks.set(element, tracks);
      const take = (track: MediaStreamTrack) => {
        if (track.kind !== 'audio') return;
        tracks.push(track);
        track.enabled = audible(element);
        addTrack(track);
      };
      stream.getAudioTracks().forEach(take);
      stream.addEventListener('addtrack', (e: MediaStreamTrackEvent) => take(e.track));
      // Detached elements (new Audio(url), as the assistant's speech uses) never reach window listeners.
      element.addEventListener('volumechange', () => syncEnabled(element));
    } catch (e) { note('element', e); }
  };
  const play = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function (this: HTMLMediaElement) {
    captureElement(this);
    return play.call(this);
  };
  // Elements in the document that start by themselves (the autoplay attribute) do not call play().
  w.addEventListener('play', (event: Event) => {
    if (event.target instanceof HTMLMediaElement) captureElement(event.target);
  }, true);

  // Microphone: the same track the page uses, so muting in the app also mutes the recording.
  const getUserMedia = MediaDevices.prototype.getUserMedia;
  MediaDevices.prototype.getUserMedia = async function (this: MediaDevices, constraints?: MediaStreamConstraints) {
    const stream = await getUserMedia.call(this, constraints);
    try { stream.getAudioTracks().forEach(addTrack); } catch (e) { note('microphone', e); }
    return stream;
  };

  w.__omProofAudio = {
    async flush() {
      const active = recorder;
      if (active && active.state === 'recording') {
        await new Promise<void>((resolve) => {
          active.addEventListener('dataavailable', () => resolve(), { once: true });
          active.requestData();
        });
      }
      await Promise.all(pending);
      return { segment, sources, errors, state: master.state };
    },
  };
}

interface Segment { file: string; start_epoch_ms: number; next: number; queued: Map<number, Buffer> }
interface PageAudio { index: number; created_epoch_ms: number; segments: Map<string, Segment>; sources: number; errors: string[] }

/** Records one browser context's audio; finish() closes the context and writes the muxed videos. */
export class ProofAudioRecorder {
  private readonly pages = new Map<Page, PageAudio>();

  private constructor(private readonly context: BrowserContext, readonly dir: string) {}

  static async install(context: BrowserContext, dir: string): Promise<ProofAudioRecorder> {
    fs.mkdirSync(dir, { recursive: true });
    const recorder = new ProofAudioRecorder(context, dir);
    context.pages().forEach((page) => recorder.track(page));
    context.on('page', (page) => recorder.track(page));
    await context.exposeBinding(BINDING, ({ page }, chunk) => recorder.write(page, chunk));
    await context.addInitScript(inPageRecorder, BINDING);
    return recorder;
  }

  private track(page: Page): PageAudio {
    let entry = this.pages.get(page);
    if (!entry) {
      entry = { index: this.pages.size, created_epoch_ms: Date.now(), segments: new Map(), sources: 0, errors: [] };
      this.pages.set(page, entry);
    }
    return entry;
  }

  /** Appends one chunk in sequence order (chunks of a segment may arrive out of order). */
  private write(page: Page, chunk: { segment: string; seq: number; startedAt: number; data: string }): void {
    const entry = this.track(page);
    const id = String(chunk.segment).replace(/[^a-z0-9]/gi, '');
    let segment = entry.segments.get(id);
    if (!segment) {
      segment = { file: `audio-${entry.index}-${id}.webm`, start_epoch_ms: chunk.startedAt, next: 0, queued: new Map() };
      entry.segments.set(id, segment);
    }
    segment.queued.set(chunk.seq, Buffer.from(chunk.data, 'base64'));
    for (let data = segment.queued.get(segment.next); data; data = segment.queued.get(segment.next)) {
      fs.appendFileSync(path.join(this.dir, segment.file), data);
      segment.queued.delete(segment.next++);
    }
  }

  /**
   * Flushes every page, closes the context (videos become final), writes the manifest and muxes.
   * Returns the muxed videos; attaches them (or, when muxing is not possible here, the manifest).
   */
  async finish(testInfo?: TestInfo): Promise<string[]> {
    for (const [page, entry] of this.pages) {
      if (page.isClosed()) continue;
      const result = await Promise.race([
        page.evaluate(() => (window as any).__omProofAudio?.flush()),
        new Promise((resolve) => setTimeout(() => resolve({ errors: ['flush timed out'] }), FLUSH_TIMEOUT_MS)),
      ]).catch((error: Error) => ({ errors: [`flush failed: ${error.message}`] })) as any;
      entry.sources = result?.sources ?? 0;
      entry.errors = result?.errors ?? ['recorder not installed in this document'];
    }
    await this.context.close();
    const pages = [];
    for (const [page, entry] of this.pages) {
      const video = page.video();
      const name = `video-${entry.index}.webm`;
      if (video) await video.saveAs(path.join(this.dir, name));
      pages.push({
        video: video ? name : '', created_epoch_ms: entry.created_epoch_ms, audio_sources: entry.sources,
        errors: entry.errors, segments: [...entry.segments.values()].map(({ file, start_epoch_ms }) => ({ file, start_epoch_ms })),
      });
    }
    const manifest = path.join(this.dir, MANIFEST_NAME);
    fs.writeFileSync(manifest, JSON.stringify({ schema_version: 1, pages }, null, 2));
    const muxed = this.mux(manifest);
    if (testInfo) {
      if (muxed.ok) {
        for (const [i, file] of muxed.files.entries()) {
          await testInfo.attach(i ? `video-with-audio-${i}` : 'video-with-audio', { path: file, contentType: 'video/webm' });
        }
      } else {
        console.warn(`[proof-audio] not muxed in this run (${muxed.reason}); the host muxes ${MANIFEST_NAME}`);
        await testInfo.attach('proof-audio-manifest', { path: manifest, contentType: 'application/json' });
      }
    }
    return muxed.files;
  }

  private mux(manifest: string): { ok: boolean; files: string[]; reason?: string } {
    if (!fs.existsSync(MUX_SCRIPT)) return { ok: false, files: [], reason: 'scripts/proof_video_audio.py not present' };
    const run = spawnSync('python3', [MUX_SCRIPT, 'mux', manifest], { encoding: 'utf8', timeout: 600_000 });
    if (run.status !== 0) return { ok: false, files: [], reason: (run.stderr || String(run.error)).trim().slice(-300) };
    return { ok: true, files: run.stdout.split('\n').filter(Boolean) };
  }
}

export async function installProofAudio(context: BrowserContext, dir: string): Promise<ProofAudioRecorder> {
  return ProofAudioRecorder.install(context, dir);
}

/**
 * ``base`` with its ``context`` fixture wrapped: the recorder is installed before any page opens
 * and finishes after every fixture that uses the context (cookie audit, page) has torn down.
 */
export function withProofAudio<T extends TestType<any, any>>(base: T): T {
  return base.extend({
    context: async ({ context }: { context: BrowserContext }, use: (c: BrowserContext) => Promise<void>, testInfo: TestInfo) => {
      const recorder = await ProofAudioRecorder.install(context, testInfo.outputPath('proof-audio'));
      await use(context);
      await recorder.finish(testInfo);
    },
  }) as unknown as T;
}

/** ``@playwright/test``'s test with proof audio, for specs that do not need the cookie audit. */
export const test = withProofAudio(playwrightTest);
