/**
 * frontend/packages/ui/src/components/embeds/videos/videoTimelineModel.ts
 *
 * Pure model of the stored timeline of a videos.generate video: normalization
 * of the stored content, the pending-edit model of edit mode and the follow-up
 * texts that extend and edit send. Nothing here fetches, renders or sends: the
 * only outgoing action of the timeline UI is the ordinary result follow-up
 * built from these texts (spec videos-generate.change.edit-mode).
 */
import type { VideoManifest } from '../../../utils/remotionTimelineParser';

export type VideoMadeBy = 'generative' | 'composed';
export type VideoTrackKind = 'visual' | 'text' | 'audio';
export type VideoPartKind = 'scene' | 'clip' | 'text' | 'image';

export interface VideoPartText { id: string; value: string }
export interface VideoPart {
  id: string;
  label: string;
  /** First frame of the part on the video's timeline. */
  from: number;
  durationInFrames: number;
  kind: VideoPartKind;
  texts: VideoPartText[];
}
export type VideoAudioEntryKind = 'speech' | 'sound' | 'music';
/** One generated sound on the timeline: narration line, sound effect or music bed. */
export interface VideoAudioEntry {
  id: string;
  kind: VideoAudioEntryKind;
  label: string;
  from: number;
  durationInFrames: number;
  /** The narration line of a speech entry. */
  text?: string;
}
export const VIDEO_AUDIO_ENTRY_KINDS: readonly VideoAudioEntryKind[] = ['speech', 'sound', 'music'];
export interface VideoTrack { id: string; name: string; kind: VideoTrackKind; parts: VideoPart[] }
export interface VideoTimelineModel {
  fps: number;
  durationInFrames: number;
  width: number;
  height: number;
  madeBy: VideoMadeBy;
  tracks: VideoTrack[];
  /** Generated sound of a composed video; read-only. */
  audio?: VideoAudioEntry[];
}

/** Edits are made in steps of half a second; a part never gets shorter than one step. */
export const TRIM_STEP_SECONDS = 0.5;
export const DEFAULT_FPS = 30;

export interface TextEdit { partId: string; textId: string; value: string }
export interface TrimEdit { partId: string; fromStartFrames: number; fromEndFrames: number }
export interface PendingEdits { texts: TextEdit[]; trims: TrimEdit[]; removed: string[] }
export const EMPTY_EDITS: PendingEdits = { texts: [], trims: [], removed: [] };

/** Translator: message key and values to text (the shell passes its `$text`). */
export type Translate = (key: string, values?: Record<string, string | number>) => string;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function positiveInt(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? Math.round(value) : undefined;
}
function nonNegativeInt(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? Math.round(value) : undefined;
}

function normalizePart(raw: unknown): VideoPart | undefined {
  if (!isRecord(raw) || typeof raw.id !== 'string') return undefined;
  const from = nonNegativeInt(raw.from);
  const duration = positiveInt(raw.duration_in_frames);
  if (from === undefined || duration === undefined) return undefined;
  const kind: VideoPartKind = raw.kind === 'clip' || raw.kind === 'text' || raw.kind === 'image' ? raw.kind : 'scene';
  const texts = Array.isArray(raw.texts)
    ? raw.texts.filter((t): t is Record<string, unknown> => isRecord(t) && typeof t.id === 'string' && typeof t.value === 'string')
        .map((t) => ({ id: String(t.id), value: String(t.value) }))
    : [];
  return { id: raw.id, label: typeof raw.label === 'string' && raw.label ? raw.label : raw.id, from, durationInFrames: duration, kind, texts };
}

function normalizeAudio(raw: unknown): VideoAudioEntry[] {
  if (!Array.isArray(raw)) return [];
  const entries: VideoAudioEntry[] = [];
  for (const item of raw) {
    if (!isRecord(item) || typeof item.id !== 'string') continue;
    const kind = VIDEO_AUDIO_ENTRY_KINDS.find((k) => k === item.kind);
    const from = nonNegativeInt(item.from);
    const duration = positiveInt(item.durationInFrames ?? item.duration_in_frames);
    if (!kind || from === undefined || duration === undefined) continue;
    entries.push({
      id: item.id, kind, from, durationInFrames: duration,
      label: typeof item.label === 'string' && item.label ? item.label : item.id,
      text: typeof item.text === 'string' && item.text ? item.text : undefined,
    });
  }
  return entries.sort((a, b) => a.from - b.from);
}

/** The stored timeline of decoded embed content, or undefined when there is none (older videos). */
export function normalizeTimeline(content: Record<string, unknown>): VideoTimelineModel | undefined {
  const raw = content.timeline;
  if (!isRecord(raw) || !Array.isArray(raw.tracks)) return undefined;
  const fps = positiveInt(raw.fps) ?? DEFAULT_FPS;
  const tracks: VideoTrack[] = [];
  for (const track of raw.tracks) {
    if (!isRecord(track) || typeof track.id !== 'string') continue;
    const kind: VideoTrackKind = track.kind === 'text' || track.kind === 'audio' ? track.kind : 'visual';
    const parts = (Array.isArray(track.parts) ? track.parts : [])
      .map(normalizePart).filter((p): p is VideoPart => !!p).sort((a, b) => a.from - b.from);
    if (parts.length > 0) tracks.push({ id: track.id, name: typeof track.name === 'string' ? track.name : track.id, kind, parts });
  }
  if (tracks.length === 0) return undefined;
  const audio = normalizeAudio(raw.audio);
  const end = Math.max(...tracks.flatMap((t) => t.parts.map((p) => p.from + p.durationInFrames)), ...audio.map((a) => a.from + a.durationInFrames));
  return {
    fps,
    durationInFrames: Math.max(positiveInt(raw.duration_in_frames) ?? 0, end),
    width: positiveInt(raw.width) ?? positiveInt(content.width) ?? 0,
    height: positiveInt(raw.height) ?? positiveInt(content.height) ?? 0,
    madeBy: madeByOf(content),
    tracks,
    audio: audio.length > 0 ? audio : undefined,
  };
}

/** Videos without `made_by` were made by one generative model call. */
export function madeByOf(content: Record<string, unknown>): VideoMadeBy {
  return content.made_by === 'composed' ? 'composed' : 'generative';
}

/** One-clip timeline of an older video without a stored timeline, from the loaded duration. */
export function synthesizeTimeline(durationSeconds: number, label: string, size: { width?: number; height?: number } = {}): VideoTimelineModel {
  const frames = Math.max(1, Math.round(durationSeconds * DEFAULT_FPS));
  return {
    fps: DEFAULT_FPS, durationInFrames: frames, width: size.width ?? 0, height: size.height ?? 0, madeBy: 'generative',
    tracks: [{ id: 'video', name: label, kind: 'visual',
      parts: [{ id: 'clip-1', label, from: 0, durationInFrames: frames, kind: 'clip', texts: [] }] }],
  };
}

/** Read-only adapter for the code-video (Remotion) manifest of the legacy create embed. */
export function timelineFromManifest(manifest: VideoManifest): VideoTimelineModel {
  const tracks: VideoTrack[] = manifest.tracks
    .map((track, index): VideoTrack => ({
      id: `track-${index + 1}`,
      name: track.name,
      kind: track.type === 'audio' ? 'audio' : track.type === 'text' ? 'text' : 'visual',
      parts: track.items.map((item): VideoPart => ({
        id: item.id, label: item.label, from: item.from, durationInFrames: Math.max(1, item.durationInFrames),
        kind: track.type === 'text' ? 'text' : 'scene', texts: [],
      })).sort((a, b) => a.from - b.from),
    }))
    .filter((track) => track.parts.length > 0);
  return {
    fps: manifest.meta.fps || DEFAULT_FPS, durationInFrames: Math.max(1, manifest.meta.durationInFrames),
    width: manifest.meta.width, height: manifest.meta.height, madeBy: 'composed', tracks,
  };
}

export function framesToSeconds(frames: number, fps: number): number {
  return frames / fps;
}

/** "8 s", "1:05" style length for labels. */
export function formatSeconds(seconds: number): string {
  const rounded = Math.round(seconds * 10) / 10;
  if (rounded >= 60) {
    const m = Math.floor(rounded / 60);
    const s = Math.round(rounded - m * 60);
    return `${m}:${String(s).padStart(2, '0')}`;
  }
  return Number.isInteger(rounded) ? `${rounded} s` : `${rounded.toFixed(1)} s`;
}

export function findPart(timeline: VideoTimelineModel, partId: string): VideoPart | undefined {
  for (const track of timeline.tracks) {
    const part = track.parts.find((p) => p.id === partId);
    if (part) return part;
  }
  return undefined;
}

/** The track whose parts make up the video's length: the first visual track, else the first. */
export function mainTrack(timeline: VideoTimelineModel): VideoTrack {
  return timeline.tracks.find((t) => t.kind === 'visual') ?? timeline.tracks[0];
}

export function trimOf(edits: PendingEdits, partId: string): TrimEdit {
  return edits.trims.find((t) => t.partId === partId) ?? { partId, fromStartFrames: 0, fromEndFrames: 0 };
}

export function isRemoved(edits: PendingEdits, partId: string): boolean {
  return edits.removed.includes(partId);
}

export function textValue(edits: PendingEdits, partId: string, textId: string, original: string): string {
  return edits.texts.find((t) => t.partId === partId && t.textId === textId)?.value ?? original;
}

/** Frames of the part that remain after its pending trims. */
export function remainingFrames(part: VideoPart, edits: PendingEdits): number {
  const trim = trimOf(edits, part.id);
  return Math.max(0, part.durationInFrames - trim.fromStartFrames - trim.fromEndFrames);
}

export function stepFrames(fps: number): number {
  return Math.round(TRIM_STEP_SECONDS * fps);
}

/** Change one text; setting it back to the original drops the edit. */
export function withText(edits: PendingEdits, timeline: VideoTimelineModel, partId: string, textId: string, value: string): PendingEdits {
  const original = findPart(timeline, partId)?.texts.find((t) => t.id === textId)?.value;
  const rest = edits.texts.filter((t) => !(t.partId === partId && t.textId === textId));
  return { ...edits, texts: value === original ? rest : [...rest, { partId, textId, value }] };
}

/** Shorten a part from one side by `deltaSteps` half seconds (negative gives time back); clamped to what is possible. */
export function withTrimStep(edits: PendingEdits, timeline: VideoTimelineModel, partId: string, side: 'start' | 'end', deltaSteps: number): PendingEdits {
  const part = findPart(timeline, partId);
  if (!part) return edits;
  const step = stepFrames(timeline.fps);
  const current = trimOf(edits, partId);
  const key = side === 'start' ? 'fromStartFrames' : 'fromEndFrames';
  const other = side === 'start' ? current.fromEndFrames : current.fromStartFrames;
  const maxForSide = Math.floor((part.durationInFrames - other - step) / step) * step;
  const next = Math.min(Math.max(0, current[key] + deltaSteps * step), Math.max(0, maxForSide));
  const trim: TrimEdit = { ...current, [key]: next };
  const rest = edits.trims.filter((t) => t.partId !== partId);
  return { ...edits, trims: trim.fromStartFrames === 0 && trim.fromEndFrames === 0 ? rest : [...rest, trim] };
}

export function canShorten(edits: PendingEdits, timeline: VideoTimelineModel, partId: string, side: 'start' | 'end'): boolean {
  const key = side === 'start' ? 'fromStartFrames' : 'fromEndFrames';
  return trimOf(withTrimStep(edits, timeline, partId, side, 1), partId)[key] > trimOf(edits, partId)[key];
}

/** A part can be removed unless it is the last remaining part of the video's main track. */
export function canRemovePart(edits: PendingEdits, timeline: VideoTimelineModel, partId: string): boolean {
  if (timeline.madeBy !== 'composed') return false;
  const main = mainTrack(timeline);
  if (!main.parts.some((p) => p.id === partId)) return true;
  return main.parts.filter((p) => !isRemoved(edits, p.id) && p.id !== partId).length > 0;
}

export function toggleRemoved(edits: PendingEdits, timeline: VideoTimelineModel, partId: string): PendingEdits {
  if (isRemoved(edits, partId)) return { ...edits, removed: edits.removed.filter((id) => id !== partId) };
  if (!canRemovePart(edits, timeline, partId)) return edits;
  return { ...edits, removed: [...edits.removed, partId] };
}

/** Number of pending changes: each changed text, each trimmed side-pair of a part and each removed part. */
export function countEdits(edits: PendingEdits): number {
  return edits.texts.length + edits.trims.length + edits.removed.length;
}

/** Length of the video after the pending edits, in frames. */
export function resultingDurationFrames(timeline: VideoTimelineModel, edits: PendingEdits): number {
  let frames = timeline.durationInFrames;
  for (const part of mainTrack(timeline).parts) {
    frames -= isRemoved(edits, part.id) ? part.durationInFrames : part.durationInFrames - remainingFrames(part, edits);
  }
  return Math.max(1, frames);
}

export function buildExtendRequestText(side: 'start' | 'end', description: string): string {
  // The marker line is English on purpose: the assistant's instructions recognise it exactly.
  const marker = side === 'end' ? 'Extend this video at the end:' : 'Extend this video at the start:';
  return `${marker} ${description.trim()}`;
}

const q = (value: string) => `"${value.replace(/"/g, '\\"')}"`;

/** Message that asks the assistant to apply all pending edits as one change of the video. */
export function buildEditRequestText(edits: PendingEdits, timeline: VideoTimelineModel, t: Translate): string {
  const lines: string[] = [];
  const seconds = (frames: number) => (frames / timeline.fps).toFixed(1);
  const generative = timeline.madeBy === 'generative';
  for (const edit of edits.texts) {
    const part = findPart(timeline, edit.partId);
    if (!part) continue;
    const original = part.texts.find((x) => x.id === edit.textId)?.value ?? '';
    lines.push(`- ${t('embeds.video_generate.request_change_text', { label: q(part.label), id: part.id, text: q(edit.textId), from: q(original), to: q(edit.value) })}`);
  }
  for (const trim of edits.trims) {
    const part = findPart(timeline, trim.partId);
    if (!part) continue;
    if (generative) {
      const key = trim.fromStartFrames > 0 && trim.fromEndFrames > 0 ? 'request_trim_video'
        : trim.fromStartFrames > 0 ? 'request_trim_video_start' : 'request_trim_video_end';
      lines.push(`- ${t(`embeds.video_generate.${key}`, { start: seconds(trim.fromStartFrames), end: seconds(trim.fromEndFrames) })}`);
      continue;
    }
    if (isRemoved(edits, part.id)) continue;
    if (trim.fromStartFrames > 0) lines.push(`- ${t('embeds.video_generate.request_shorten_start', { label: q(part.label), id: part.id, seconds: seconds(trim.fromStartFrames) })}`);
    if (trim.fromEndFrames > 0) lines.push(`- ${t('embeds.video_generate.request_shorten_end', { label: q(part.label), id: part.id, seconds: seconds(trim.fromEndFrames) })}`);
  }
  for (const id of edits.removed) {
    const part = findPart(timeline, id);
    if (part) lines.push(`- ${t('embeds.video_generate.request_remove_part', { label: q(part.label), id })}`);
  }
  return `Apply these edits to this video:\n${lines.join('\n')}`;
}
