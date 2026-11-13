/**
 * Event sounds: short, quiet, generated cues for a few important moments
 * (message accepted, new notification, error, reply finished while away).
 *
 * Rules (specifications/features/notifications, notifications.sounds.*):
 * - After a cue there is always a quiet window; a cue that falls into it is
 *   dropped, never queued or delayed.
 * - Silent mode (device-local) turns off cues and vibrations.
 * - The first cue ever played shows a one-time notice with a one-click opt-out.
 *
 * Platform feedback only: no protocol, sync or retry logic lives here.
 */
import { get, writable, type Readable } from "svelte/store";

export type EventCue = "accepted" | "notification" | "error" | "reply_finished";
export type EventCueOutcome = "played" | "silent_mode" | "quiet_window" | "audio_locked";

interface CueNote { frequency: number; offset: number; duration: number }

/** Note tables are exported for tests and the settings preview. */
export const EVENT_CUE_NOTES: Readonly<Record<EventCue, readonly CueNote[]>> = {
  accepted: [{ frequency: 659.25, offset: 0, duration: 0.07 }, { frequency: 987.77, offset: 0.08, duration: 0.1 }],
  notification: [{ frequency: 783.99, offset: 0, duration: 0.09 }, { frequency: 1046.5, offset: 0.11, duration: 0.14 }],
  error: [{ frequency: 329.63, offset: 0, duration: 0.11 }, { frequency: 246.94, offset: 0.13, duration: 0.16 }],
  reply_finished: [
    { frequency: 523.25, offset: 0, duration: 0.08 },
    { frequency: 659.25, offset: 0.09, duration: 0.08 },
    { frequency: 783.99, offset: 0.18, duration: 0.14 },
  ],
};

/** Silence that always follows a cue; cues inside it are dropped. */
export const EVENT_CUE_QUIET_WINDOW_MS = 3000;
export const SILENT_MODE_STORAGE_KEY = "openmates_silent_mode";
export const EVENT_SOUND_NOTICE_STORAGE_KEY = "openmates_event_sound_notice_shown";
/** Fired on window for every cue request, with its outcome. */
export const EVENT_CUE_EVENT = "openmates:event-cue";

const CUE_PEAK = 0.05;
const ATTACK = 0.008;
const RELEASE = 0.03;
const CUE_VIBRATION_MS: Readonly<Record<EventCue, number | number[]>> = {
  accepted: 20,
  notification: 30,
  error: [40, 60, 40],
  reply_finished: 30,
};
const LOCAL_SEND_LIMIT = 64;

function readFlag(key: string): boolean {
  try {
    return typeof localStorage !== "undefined" && localStorage.getItem(key) === "true";
  } catch {
    // Storage can be blocked (private mode, embedded contexts): default applies.
    return false;
  }
}

function writeFlag(key: string, value: boolean): void {
  try {
    if (typeof localStorage === "undefined") return;
    if (value) localStorage.setItem(key, "true");
    else localStorage.removeItem(key);
  } catch {
    // Storage blocked: the choice still holds for this page session.
  }
}

const silentModeStore = writable<boolean>(readFlag(SILENT_MODE_STORAGE_KEY));

/** Device-local silent mode: true turns off event sounds and vibrations. */
export const silentMode: Readable<boolean> = { subscribe: silentModeStore.subscribe };

export function setSilentMode(silent: boolean): void {
  writeFlag(SILENT_MODE_STORAGE_KEY, silent);
  silentModeStore.set(silent);
}

function cueLength(cue: EventCue): number {
  return Math.max(...EVENT_CUE_NOTES[cue].map((note) => note.offset + note.duration)) * 1000;
}

/**
 * Decides whether a cue may sound. Pure and clock-injected so the quiet-window
 * rule is unit tested without audio.
 */
export class EventCueGate {
  private quietUntil = 0;

  admit(cue: EventCue, now: number): boolean {
    if (now < this.quietUntil) return false;
    this.quietUntil = now + cueLength(cue) + EVENT_CUE_QUIET_WINDOW_MS;
    return true;
  }
}

const gate = new EventCueGate();
let context: AudioContext | null = null;
let unlockInstalled = false;
let noticeHandler: (() => void) | null = null;

/** Browsers only allow audio after a user gesture; open the output on the first one. */
function unlockAudio(): void {
  if (context || typeof AudioContext === "undefined") return;
  try {
    context = new AudioContext();
    if (context.state === "suspended") void context.resume().catch(() => undefined);
  } catch {
    // No audio output available on this device: cues stay silent.
    context = null;
  }
}

/** Call once at app start. Safe to call repeatedly and on the server. */
export function installEventSounds(showFirstCueNotice: () => void): void {
  noticeHandler = showFirstCueNotice;
  if (unlockInstalled || typeof window === "undefined") return;
  unlockInstalled = true;
  const options = { capture: true, passive: true } as const;
  window.addEventListener("pointerdown", unlockAudio, options);
  window.addEventListener("keydown", unlockAudio, options);
}

function schedule(audio: AudioContext, cue: EventCue): void {
  const start = audio.currentTime + 0.01;
  for (const note of EVENT_CUE_NOTES[cue]) {
    const oscillator = audio.createOscillator();
    const gain = audio.createGain();
    const at = start + note.offset;
    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(note.frequency, at);
    gain.gain.setValueAtTime(0, at);
    gain.gain.linearRampToValueAtTime(CUE_PEAK, at + ATTACK);
    gain.gain.setValueAtTime(CUE_PEAK, at + note.duration - RELEASE);
    gain.gain.linearRampToValueAtTime(0, at + note.duration);
    oscillator.connect(gain);
    gain.connect(audio.destination);
    oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); };
    oscillator.start(at);
    oscillator.stop(at + note.duration);
  }
}

function report(cue: EventCue, outcome: EventCueOutcome): EventCueOutcome {
  if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
    window.dispatchEvent(new CustomEvent(EVENT_CUE_EVENT, { detail: { cue, outcome } }));
  }
  return outcome;
}

/**
 * Play a cue if silent mode is off, audio is unlocked and no quiet window is
 * running. A refused cue is dropped for good.
 */
export function playEventCue(cue: EventCue): EventCueOutcome {
  if (get(silentModeStore)) return report(cue, "silent_mode");
  const audio = context;
  if (!audio || audio.state !== "running") return report(cue, "audio_locked");
  if (!gate.admit(cue, Date.now())) return report(cue, "quiet_window");
  schedule(audio, cue);
  if (typeof navigator !== "undefined" && navigator.vibrate) navigator.vibrate(CUE_VIBRATION_MS[cue]);
  if (!readFlag(EVENT_SOUND_NOTICE_STORAGE_KEY)) {
    writeFlag(EVENT_SOUND_NOTICE_STORAGE_KEY, true);
    noticeHandler?.();
  }
  return report(cue, "played");
}

/** Vibration for direct touch feedback (long press, refused send); off in silent mode. */
export function vibrateDevice(pattern: number | number[]): void {
  if (get(silentModeStore)) return;
  if (typeof navigator !== "undefined" && navigator.vibrate) navigator.vibrate(pattern);
}

const localSends = new Set<string>();

/** Remember a message this device sent, so only its own acceptance makes a sound. */
export function noteLocalSend(messageId: string): void {
  if (!messageId) return;
  localSends.add(messageId);
  if (localSends.size > LOCAL_SEND_LIMIT) {
    const oldest = localSends.values().next().value;
    if (oldest !== undefined) localSends.delete(oldest);
  }
}

/** The server admitted a message for processing: the user may leave the tab now. */
export function messageAccepted(messageId: string): void {
  if (localSends.delete(messageId)) playEventCue("accepted");
}

/** A reply finished; it only makes a sound when the user is not looking at the tab. */
export function replyFinished(): void {
  if (typeof document !== "undefined" && document.hidden) playEventCue("reply_finished");
}
