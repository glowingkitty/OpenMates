/**
 * Browser side of the voice-call waiting state: ready-made lines (voice and
 * chat text, no inference, no credits) and replay of the stored last answer.
 * Whether a call waits is decided by the server (hold button or the decision
 * model's spoken intent); this module only presents it.
 */
import { get, type Readable } from 'svelte/store';
import { locale as appLocale } from 'svelte-i18n';
import { text as translate } from '../i18n/translations';

export type VoiceCallWaitingLine = 'waiting_start' | 'waiting_resume';
export const VOICE_CALL_WAITING_LINES: readonly VoiceCallWaitingLine[] = ['waiting_start', 'waiting_resume'];
/** Locales with a pre-generated system clip; other languages show text only. */
const CLIP_LOCALES: Readonly<Record<string, string>> = { en: 'en-US', de: 'de-DE', es: 'es-ES', fr: 'fr-FR' };
const CLIP_ROOT = '/audio/assistant-acknowledgements/system';

export function isWaitingLine(value: unknown): value is VoiceCallWaitingLine {
  return typeof value === 'string' && (VOICE_CALL_WAITING_LINES as readonly string[]).includes(value);
}

/** Static clip URL of a line for the app language, or null without a clip. */
export function waitingLineClipUrl(line: VoiceCallWaitingLine, language: string | null | undefined): string | null {
  const clipLocale = CLIP_LOCALES[(language ?? 'en').split('-')[0].toLowerCase()];
  return clipLocale ? `${CLIP_ROOT}/${clipLocale}/${line}-1.mp3` : null;
}

export function waitingLineText(line: VoiceCallWaitingLine): string {
  return get(translate)(`voicecall.${line}`);
}

type ClipPlayer = (url: string) => Promise<void>;
const playClip: ClipPlayer = async url => {
  const audio = new Audio(url);
  await audio.play();
};

/** Play a line's clip; resolves false when it has no clip or playback is refused. */
export async function playWaitingLine(line: VoiceCallWaitingLine, player: ClipPlayer = playClip): Promise<boolean> {
  const url = waitingLineClipUrl(line, get(appLocale));
  if (!url) {
    console.warn(`[voiceCallWaiting] no clip for line "${line}" in language "${get(appLocale)}"; text only`);
    return false;
  }
  try { await player(url); return true; } catch (error) {
    console.warn(`[voiceCallWaiting] clip for line "${line}" could not play`, error);
    return false;
  }
}

interface ReplayableSpeech {
  player: Readable<{ hasReplayableTracks: boolean; status?: string }>;
  play(): Promise<void>;
}

/** Replay the stored last answer without any new request; false when none is stored. */
export async function replayLastAnswer(speech: ReplayableSpeech): Promise<boolean> {
  if (!get(speech.player).hasReplayableTracks) return false;
  await speech.play();
  // A live call's streamed answer is consumed once; the queue then reports
  // "completed" without any audio, which must not count as a replay.
  return get(speech.player).status !== 'completed';
}
