// Display-only spoken progress for the assistant reply answering a voice call.
//
// While a call is live, the reply's text renders dimmed as it streams and each
// word becomes fully visible once playback reaches it. Progress comes from the
// provider's word estimates on the turn track (`assistantSpeechQueue`); it
// never grants heard coverage. A reply is released to full opacity, for good,
// when playback settles (end, interrupt, failure, blocked autoplay), when the
// user starts speaking again, when the call ends, or when generation finished
// without speech ever starting.
import { readable, type Readable } from 'svelte/store';
import type { VoiceCallState } from './voiceCall';

export interface SpokenWordProgressSource {
  readonly spokenWordProgress: { responseId: string; words: number; began: boolean; settled: boolean } | null;
}

export interface VoiceCallSpokenProgress {
  messageId: string;
  /** Leading words already spoken; the rest renders dimmed. */
  words: number;
}

/** Speech may start after a short reply finished generating. */
export const SPOKEN_PROGRESS_START_GRACE_MS = 15_000;
const MAX_RELEASED_MESSAGES = 50;

export function createVoiceCallSpokenProgress(
  call: Readable<VoiceCallState>,
  speech: SpokenWordProgressSource,
  frames: { request(callback: () => void): number; cancel(handle: number): void; now(): number } = {
    request: (callback) => requestAnimationFrame(callback),
    cancel: (handle) => cancelAnimationFrame(handle),
    now: () => performance.now(),
  },
): Readable<VoiceCallSpokenProgress | null> {
  return readable<VoiceCallSpokenProgress | null>(null, (set) => {
    const released = new Set<string>();
    let state: VoiceCallState | null = null;
    let current: VoiceCallSpokenProgress | null = null;
    let generationEndedAt: { messageId: string; at: number } | null = null;
    let frame: number | null = null;

    const publish = (next: VoiceCallSpokenProgress | null) => {
      if (next?.messageId === current?.messageId && next?.words === current?.words) return;
      current = next;
      set(next);
    };
    const release = (messageId: string) => {
      released.add(messageId);
      if (released.size > MAX_RELEASED_MESSAGES) released.delete(released.values().next().value!);
    };
    const evaluate = (): boolean => {
      const messageId = state?.status === 'live' ? state.assistantMessageId ?? null : null;
      if (!state || !messageId || released.has(messageId)) { publish(null); return false; }
      // The user talking again (or a new turn) ends the previous reply's progress.
      if (state.liveTranscript) { release(messageId); publish(null); return false; }
      const progress = speech.spokenWordProgress;
      const ours = progress?.responseId === messageId ? progress : null;
      if (ours?.settled) { release(messageId); publish(null); return false; }
      if (!ours?.began && !state.assistantGenerating) {
        if (generationEndedAt?.messageId !== messageId) generationEndedAt = { messageId, at: frames.now() };
        if (frames.now() - generationEndedAt.at >= SPOKEN_PROGRESS_START_GRACE_MS) {
          release(messageId); publish(null); return false;
        }
      }
      publish({ messageId, words: ours?.began ? ours.words : 0 });
      return true;
    };
    const loop = () => {
      frame = null;
      if (evaluate()) frame = frames.request(loop);
    };
    const unsubscribe = call.subscribe((next) => {
      state = next;
      const active = evaluate();
      if (active && frame === null) frame = frames.request(loop);
      if (!active && frame !== null) { frames.cancel(frame); frame = null; }
    });
    return () => {
      unsubscribe();
      if (frame !== null) frames.cancel(frame);
    };
  });
}

