// frontend/packages/ui/src/services/savedEmbedService.ts
//
// Save / Saved state for result embeds (events, stays, connections, listings,
// appointments). Saving sets an encrypted `saved` flag (plus `saved_at`) on the
// embed's own content through the normal client-encrypted embed revision path
// (commitEmbedContentRevision). No memory entry is created and no plaintext
// leaves the device.
//
// Used by the embed fullscreen CTAs, the chat message context menu, the
// saved-preview action and the continue-where-you-left-off section.
// Contract: specifications/features/app-memories (app-memories.saved-items.not-memories).

import { get, writable } from 'svelte/store';
import { embedStore } from './embedStore';
import { decodeToonContent } from './embedResolver';
import { commitEmbedContentRevision } from './embedDiffStore';
import { notificationStore } from '../stores/notificationStore';
import { scheduleSavedEmbedReminders, type SavedReminderKind } from './savedEmbedReminders';

export type SavedEmbedKind = SavedReminderKind;

/** Apps whose result embeds can be saved. */
export const SAVEABLE_EMBED_APP_IDS = ['events', 'travel', 'home', 'health'] as const;

export const SAVED_EMBED_CHANGED_EVENT = 'savedEmbedChanged';

/** A saved embed with the fields the continue section and lists need. */
export interface SavedEmbed {
  embedId: string;
  appId: string;
  kind: SavedEmbedKind | null;
  title: string;
  savedAt: number;
  /** Start/end/location fields in the shape continueCarouselService reads. */
  itemValue: Record<string, unknown>;
}

/** Reactive set of embed ids known to be saved on this device. */
export const savedEmbedIds = writable<Set<string>>(new Set());

export function getEmbedIdFromContentRef(contentRef: unknown): string {
  return typeof contentRef === 'string' && contentRef.startsWith('embed:')
    ? contentRef.slice('embed:'.length)
    : '';
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

export function isContentSaved(content: Record<string, unknown> | null | undefined): boolean {
  return content?.saved === true || content?.saved === 'true';
}

function setKnownSaved(embedId: string, saved: boolean): void {
  savedEmbedIds.update((ids) => {
    if (ids.has(embedId) === saved) return ids;
    const next = new Set(ids);
    if (saved) next.add(embedId); else next.delete(embedId);
    return next;
  });
}

export function isEmbedSaved(embedId: string): boolean {
  return get(savedEmbedIds).has(embedId);
}

interface LoadedEmbed {
  appId: string;
  skillId: string;
  chatId: string;
  version: number;
  content: Record<string, unknown>;
}

async function loadEmbed(embedId: string): Promise<LoadedEmbed | null> {
  const stored = await embedStore.get(`embed:${embedId}`);
  if (!stored || typeof stored !== 'object') return null;
  const record = stored as Record<string, unknown>;
  const decoded = typeof record.content === 'string'
    ? await decodeToonContent(record.content)
    : record.content;
  if (!decoded || typeof decoded !== 'object' || Array.isArray(decoded)) return null;
  const content = decoded as Record<string, unknown>;
  return {
    appId: asString(record.app_id) || asString(content.app_id),
    skillId: asString(record.skill_id) || asString(content.skill_id),
    chatId: asString(record.chat_id) || asString(content.chat_id),
    version: Number(record.version_number ?? content.version_number ?? 1) || 1,
    content,
  };
}

/** Read the persisted saved flag of an embed and publish it to `savedEmbedIds`. */
export async function loadEmbedSaved(embedId: string): Promise<boolean> {
  if (!embedId) return false;
  const loaded = await loadEmbed(embedId);
  const saved = isContentSaved(loaded?.content);
  setKnownSaved(embedId, saved);
  return saved;
}

/**
 * Set or clear the encrypted saved flag on an embed. Throws when the embed is
 * unknown or not writable on this device.
 */
export async function setEmbedSaved(
  embedId: string,
  saved: boolean,
  options: { scheduleReminders?: boolean } = {},
): Promise<boolean> {
  if (!embedId) throw new Error('Saving requires an embed id');
  const loaded = await loadEmbed(embedId);
  if (!loaded) throw new Error('Embed is not available on this device yet');
  if (isContentSaved(loaded.content) === saved) {
    setKnownSaved(embedId, saved);
    return false;
  }

  const next: Record<string, unknown> = { ...loaded.content };
  if (saved) {
    next.saved = true;
    next.saved_at = Math.floor(Date.now() / 1000);
  } else {
    delete next.saved;
    delete next.saved_at;
  }
  await commitEmbedContentRevision(embedId, JSON.stringify(next), {
    currentVersion: loaded.version,
    currentContent: JSON.stringify(loaded.content),
    buildRestoredContent: (restored, newVersion) => ({
      ...(JSON.parse(restored) as Record<string, unknown>),
      version_number: newVersion,
    }),
  });

  setKnownSaved(embedId, saved);
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(SAVED_EMBED_CHANGED_EVENT, { detail: { embedId, saved } }));
  }
  if (saved && options.scheduleReminders !== false) {
    // Items with an actual date and time keep scheduling reminders when saved.
    const count = await scheduleSavedEmbedReminders(embedId,
      kindFor(loaded.appId, loaded.skillId), loaded.appId, loaded.content, loaded.chatId)
      .catch((error) => {
        console.warn('[savedEmbedService] Saved item reminders failed:', error);
        return 0;
      });
    if (count > 0) notificationStore.success(`Saved and created ${count} reminder${count === 1 ? '' : 's'}.`);
  }
  return true;
}

/** Toggle Save / Saved; surfaces failures as an error notification. */
export async function toggleEmbedSaved(embedId: string): Promise<boolean> {
  const target = !isEmbedSaved(embedId) && !(await loadEmbedSaved(embedId));
  try {
    await setEmbedSaved(embedId, target);
    return target;
  } catch (error) {
    console.error('[savedEmbedService] Failed to toggle saved state:', error);
    notificationStore.error(error instanceof Error ? error.message : 'Failed to update saved item.');
    return !target;
  }
}

export function kindFor(appId: string, skillId: string): SavedEmbedKind | null {
  if (appId === 'events') return 'event';
  if (appId === 'home') return 'home_listing';
  if (appId === 'health') return 'health_appointment';
  if (appId === 'travel') {
    return skillId === 'connection' || skillId === 'search_connections' ? 'travel_connection' : 'travel_stay';
  }
  return null;
}

/** Map decoded embed content onto the date fields the continue section reads. */
export function buildSavedItemValue(kind: SavedEmbedKind | null, content: Record<string, unknown>): Record<string, unknown> {
  const legs = Array.isArray(content.legs) ? content.legs as Array<Record<string, unknown>> : [];
  const first = legs[0] || {};
  const last = legs.length > 0 ? legs[legs.length - 1] : {};
  switch (kind) {
    case 'event':
      return { title: content.title, provider: content.provider, location: content.location,
        date_start: content.date_start, date_end: content.date_end };
    case 'travel_connection':
      return { title: content.route_display || content.title,
        origin: content.origin || first.origin, destination: content.destination || last.destination,
        departure: content.departure || first.departure, arrival: content.arrival || last.arrival };
    case 'travel_stay':
      return { title: content.name, date_start: content.check_in || content.check_in_date,
        date_end: content.check_out || content.check_out_date };
    case 'home_listing':
      return { title: content.title, available_from: content.available_from, location: content.address };
    case 'health_appointment':
      return { title: content.name || content.speciality, appointment_time: content.slot_datetime };
    default:
      return { title: content.title || content.name };
  }
}

/** List every saved embed available on this device (newest save first). */
export async function listSavedEmbeds(): Promise<SavedEmbed[]> {
  const saved: SavedEmbed[] = [];
  for (const appId of SAVEABLE_EMBED_APP_IDS) {
    for (const entry of await embedStore.getEmbedsByAppId(appId)) {
      const embedId = asString((entry as unknown as Record<string, unknown>).embed_id);
      if (!embedId) continue;
      const loaded = await loadEmbed(embedId);
      if (!loaded || !isContentSaved(loaded.content)) continue;
      const kind = kindFor(loaded.appId || appId, loaded.skillId);
      const itemValue = buildSavedItemValue(kind, loaded.content);
      saved.push({
        embedId, appId: loaded.appId || appId, kind,
        title: asString(itemValue.title) || asString(loaded.content.title) || asString(loaded.content.name),
        savedAt: Number(loaded.content.saved_at) || 0, itemValue,
      });
    }
  }
  const ids = new Set(saved.map((item) => item.embedId));
  savedEmbedIds.set(ids);
  return saved.sort((a, b) => b.savedAt - a.savedAt);
}

function startMs(item: SavedEmbed): number | null {
  const v = item.itemValue;
  for (const raw of [v.date_start, v.departure, v.appointment_time, v.available_from]) {
    if (typeof raw !== 'string' || !raw) continue;
    const parsed = new Date(raw).getTime();
    if (!Number.isNaN(parsed)) return parsed;
  }
  return null;
}

/**
 * Upcoming saved events, connections and stays: a start date in the future,
 * soonest first. Items without a parseable start are excluded.
 */
export function selectUpcomingSavedEmbeds(items: SavedEmbed[], nowMs: number = Date.now()): SavedEmbed[] {
  return items
    .filter((item) => item.kind === 'event' || item.kind === 'travel_connection' || item.kind === 'travel_stay')
    .map((item) => ({ item, start: startMs(item) }))
    .filter((entry): entry is { item: SavedEmbed; start: number } => entry.start !== null && entry.start > nowMs)
    .sort((a, b) => a.start - b.start)
    .map((entry) => entry.item);
}
