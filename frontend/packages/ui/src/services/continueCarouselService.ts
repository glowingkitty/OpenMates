// frontend/packages/ui/src/services/continueCarouselService.ts
//
// Builds the priority layer for the welcome-screen "Continue where you left off"
// carousel. The sidebar keeps using its existing chronological/pinned sorting;
// these helpers only classify chats and saved embeds that have near-term reminder
// or date relevance so the welcome screen can explain why they are promoted.
//

export type ContinuePriorityReason =
  | 'reminder_due'
  | 'reminder_soon'
  | 'upcoming_saved_item'
  | 'ongoing_saved_item';

export interface ContinuePriority {
  reason: ContinuePriorityReason;
  label: string;
  timestamp: number;
}

export interface ActiveReminderForContinue {
  reminder_id: string;
  prompt_preview?: string;
  trigger_at: number;
  trigger_at_formatted?: string;
  target_type: string;
  target_chat_id?: string | null;
  target_embed_id?: string | null;
  status: string;
}

export interface SavedEmbedContinueCandidate {
  kind: 'embed';
  embedId: string;
  appId: string;
  title: string;
  summary: string | null;
  icon: string;
  category: string | null;
  itemValue: Record<string, unknown>;
  priority: ContinuePriority;
}

interface DecryptedMemoryEntryLike {
  id: string;
  item_key: string;
  item_value: Record<string, unknown>;
  settings_group: string;
}

interface AppSettingsMemoriesStateLike {
  entriesByApp: Map<string, Record<string, DecryptedMemoryEntryLike[]>>;
}

const HOUR_MS = 60 * 60 * 1000;
const UPCOMING_WINDOW_MS = 24 * HOUR_MS;
const RECENT_WINDOW_MS = 12 * HOUR_MS;

function asString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function parseTime(value: unknown): number | null {
  const raw = asString(value);
  if (!raw) return null;

  const parsed = new Date(raw).getTime();
  return Number.isNaN(parsed) ? null : parsed;
}

function formatRelativeLabel(prefix: string, timestamp: number, nowMs: number): string {
  const diffMs = timestamp - nowMs;
  const absMinutes = Math.max(1, Math.round(Math.abs(diffMs) / 60_000));

  if (absMinutes < 60) {
    return diffMs >= 0 ? `${prefix} in ${absMinutes}m` : `${prefix} ${absMinutes}m ago`;
  }

  const hours = Math.max(1, Math.round(absMinutes / 60));
  if (hours < 24) {
    return diffMs >= 0 ? `${prefix} in ${hours}h` : `${prefix} ${hours}h ago`;
  }

  const days = Math.max(1, Math.round(hours / 24));
  return diffMs >= 0 ? `${prefix} in ${days}d` : `${prefix} ${days}d ago`;
}

export function buildReminderPriority(
  reminder: ActiveReminderForContinue,
  nowMs: number = Date.now(),
): ContinuePriority | null {
  const triggerMs = reminder.trigger_at * 1000;
  if (!Number.isFinite(triggerMs) || triggerMs <= 0) return null;

  if (triggerMs <= nowMs) {
    if (nowMs - triggerMs > RECENT_WINDOW_MS && reminder.status !== 'pending') return null;
    return {
      reason: 'reminder_due',
      label: formatRelativeLabel('Reminder', triggerMs, nowMs),
      timestamp: triggerMs,
    };
  }

  if (triggerMs - nowMs > UPCOMING_WINDOW_MS) return null;
  return {
    reason: 'reminder_soon',
    label: formatRelativeLabel('Reminder', triggerMs, nowMs),
    timestamp: triggerMs,
  };
}

function getSavedItemTimeWindow(itemValue: Record<string, unknown>): { startMs: number | null; endMs: number | null } {
  const startMs =
    parseTime(itemValue.date_start) ??
    parseTime(itemValue.departure) ??
    parseTime(itemValue.start_time) ??
    parseTime(itemValue.starts_at) ??
    parseTime(itemValue.datetime) ??
    parseTime(itemValue.appointment_time) ??
    parseTime(itemValue.available_from);

  const endMs =
    parseTime(itemValue.date_end) ??
    parseTime(itemValue.arrival) ??
    parseTime(itemValue.end_time) ??
    parseTime(itemValue.ends_at) ??
    parseTime(itemValue.checkout) ??
    parseTime(itemValue.available_until);

  return { startMs, endMs };
}

function getSavedItemPriority(
  itemValue: Record<string, unknown>,
  nowMs: number,
  itemLabel: string,
): ContinuePriority | null {
  const { startMs, endMs } = getSavedItemTimeWindow(itemValue);

  if (endMs && endMs >= nowMs && (!startMs || startMs <= nowMs)) {
    return {
      reason: 'ongoing_saved_item',
      label: `${itemLabel} ongoing`,
      timestamp: endMs,
    };
  }

  if (!startMs) return null;

  const startedRecently = startMs <= nowMs && nowMs - startMs <= RECENT_WINDOW_MS;
  const startsSoon = startMs > nowMs && startMs - nowMs <= UPCOMING_WINDOW_MS;
  if (!startedRecently && !startsSoon) return null;

  return {
    reason: 'upcoming_saved_item',
    label: formatRelativeLabel(itemLabel, startMs, nowMs),
    timestamp: startMs,
  };
}

function getSavedItemPresentation(
  appId: string,
  groupName: string,
  itemValue: Record<string, unknown>,
): { icon: string; category: string | null; itemLabel: string; summary: string | null } {
  if (appId === 'travel' || groupName.includes('connection')) {
    return {
      icon: 'plane',
      category: 'travel',
      itemLabel: 'Trip',
      summary: [asString(itemValue.origin), asString(itemValue.destination), asString(itemValue.notes)].filter(Boolean).join(' · ') || null,
    };
  }

  if (appId === 'events' || groupName.includes('event')) {
    return {
      icon: 'calendar-days',
      category: 'events',
      itemLabel: 'Event',
      summary: [asString(itemValue.location), asString(itemValue.provider)].filter(Boolean).join(' · ') || null,
    };
  }

  if (appId === 'health') {
    return {
      icon: 'stethoscope',
      category: 'health',
      itemLabel: 'Appointment',
      summary: asString(itemValue.notes) || null,
    };
  }

  if (appId === 'home') {
    return {
      icon: 'house',
      category: 'home',
      itemLabel: 'Listing',
      summary: [asString(itemValue.location), asString(itemValue.notes)].filter(Boolean).join(' · ') || null,
    };
  }

  return {
    icon: 'bookmark',
    category: null,
    itemLabel: 'Saved item',
    summary: asString(itemValue.notes) || null,
  };
}

export function getReminderByTargetChatId(
  reminders: ActiveReminderForContinue[],
  nowMs: number = Date.now(),
): Map<string, { reminder: ActiveReminderForContinue; priority: ContinuePriority }> {
  const byChat = new Map<string, { reminder: ActiveReminderForContinue; priority: ContinuePriority }>();

  for (const reminder of reminders) {
    const chatId = asString(reminder.target_chat_id);
    if (!chatId) continue;
    const priority = buildReminderPriority(reminder, nowMs);
    if (!priority) continue;

    const existing = byChat.get(chatId);
    if (!existing || compareContinuePriority(priority, existing.priority, nowMs) < 0) {
      byChat.set(chatId, { reminder, priority });
    }
  }

  return byChat;
}

export function getReminderByTargetEmbedId(
  reminders: ActiveReminderForContinue[],
  nowMs: number = Date.now(),
): Map<string, { reminder: ActiveReminderForContinue; priority: ContinuePriority }> {
  const byEmbed = new Map<string, { reminder: ActiveReminderForContinue; priority: ContinuePriority }>();

  for (const reminder of reminders) {
    const embedId = asString(reminder.target_embed_id);
    if (!embedId) continue;
    const priority = buildReminderPriority(reminder, nowMs);
    if (!priority) continue;

    const existing = byEmbed.get(embedId);
    if (!existing || compareContinuePriority(priority, existing.priority, nowMs) < 0) {
      byEmbed.set(embedId, { reminder, priority });
    }
  }

  return byEmbed;
}

export function getSavedEmbedContinueCandidates(
  state: AppSettingsMemoriesStateLike,
  remindersByEmbedId: Map<string, { reminder: ActiveReminderForContinue; priority: ContinuePriority }> = new Map(),
  nowMs: number = Date.now(),
): SavedEmbedContinueCandidate[] {
  const candidates: SavedEmbedContinueCandidate[] = [];

  for (const [appId, groups] of Array.from(state.entriesByApp.entries())) {
    for (const [groupName, entries] of Object.entries(groups) as Array<[string, DecryptedMemoryEntryLike[]]>) {
      for (const entry of entries) {
        const itemValue = entry.item_value || {};
        const embedId = asString(itemValue.embed_id);
        if (!embedId) continue;

        const presentation = getSavedItemPresentation(appId, groupName, itemValue);
        const reminderMatch = remindersByEmbedId.get(embedId);
        const priority = reminderMatch?.priority ?? getSavedItemPriority(itemValue, nowMs, presentation.itemLabel);
        if (!priority) continue;

        candidates.push({
          kind: 'embed',
          embedId,
          appId,
          title: asString(itemValue.title) || asString(itemValue.name) || presentation.itemLabel,
          summary: presentation.summary,
          icon: presentation.icon,
          category: presentation.category,
          itemValue,
          priority,
        });
      }
    }
  }

  return sortContinuePriorityItems(candidates, nowMs);
}

function priorityRank(priority: ContinuePriority): number {
  switch (priority.reason) {
    case 'reminder_due':
      return 0;
    case 'reminder_soon':
      return 1;
    case 'ongoing_saved_item':
      return 2;
    case 'upcoming_saved_item':
      return 3;
  }
}

export function compareContinuePriority(
  a: ContinuePriority,
  b: ContinuePriority,
  nowMs: number = Date.now(),
): number {
  const rankDiff = priorityRank(a) - priorityRank(b);
  if (rankDiff !== 0) return rankDiff;

  if (a.reason === 'reminder_due') {
    return Math.abs(nowMs - a.timestamp) - Math.abs(nowMs - b.timestamp);
  }

  return Math.abs(a.timestamp - nowMs) - Math.abs(b.timestamp - nowMs);
}

export function sortContinuePriorityItems<T extends { priority: ContinuePriority }>(items: T[], nowMs: number = Date.now()): T[] {
  return [...items].sort((a, b) => compareContinuePriority(a.priority, b.priority, nowMs));
}
