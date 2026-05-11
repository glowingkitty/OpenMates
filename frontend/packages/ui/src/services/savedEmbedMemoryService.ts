// frontend/packages/ui/src/services/savedEmbedMemoryService.ts
//
// Shared save flow for embed fullscreen CTAs.
// Stores selected embed results in the app settings/memories store and schedules
// passive reminders through the Reminder app. The data remains zero-knowledge:
// memory entries are encrypted by appSettingsMemoriesStore before sync.
//
// Used by event, travel, home, and health fullscreen embeds.

import { get } from 'svelte/store';
import { getApiUrl } from '../config/api';
import { notificationStore } from '../stores/notificationStore';
import { appSettingsMemoriesStore } from '../stores/appSettingsMemoriesStore';
import { userProfile } from '../stores/userProfile';

export type SavedEmbedKind =
  | 'event'
  | 'travel_connection'
  | 'travel_stay'
  | 'home_listing'
  | 'health_appointment';

export function getEmbedIdFromContentRef(contentRef: unknown): string {
  return typeof contentRef === 'string' && contentRef.startsWith('embed:')
    ? contentRef.slice('embed:'.length)
    : '';
}

export interface SavedEmbedConfig {
  kind: SavedEmbedKind;
  appId: string;
  itemType: string;
  itemKey: string;
  title: string;
  itemValue: Record<string, unknown>;
  reminderDateTime?: string | null;
  reminderPromptTitle?: string;
}

interface SavedMemoryEntry {
  id: string;
  item_key: string;
  item_value: Record<string, unknown>;
  settings_group: string;
}

interface AppSettingsMemoriesStateLike {
  entriesByApp: Map<string, Record<string, SavedMemoryEntry[]>>;
}

const DEFAULT_OFFSETS_MINUTES: Record<SavedEmbedKind, number[]> = {
  event: [7 * 24 * 60, 12 * 60, 60],
  travel_connection: [30 * 24 * 60, 7 * 24 * 60, 24 * 60, 3 * 60],
  travel_stay: [24 * 60, 7 * 24 * 60],
  home_listing: [24 * 60, 3 * 24 * 60],
  health_appointment: [7 * 24 * 60, 24 * 60, 3 * 60],
};

function getTimezone(): string {
  return get(userProfile).timezone || Intl.DateTimeFormat().resolvedOptions().timeZone;
}

function getReminderOffsets(kind: SavedEmbedKind): number[] {
  const reminderGroups = get(appSettingsMemoriesStore).entriesByApp.get('reminder');
  const defaults = reminderGroups?.saved_item_reminder_defaults || [];
  const matchingDefault = defaults.find((entry) => entry.item_value.item_kind === kind);
  const rawOffsets = matchingDefault?.item_value.offsets_minutes;

  if (typeof rawOffsets !== 'string') return DEFAULT_OFFSETS_MINUTES[kind];

  const parsed = rawOffsets
    .split(',')
    .map((value) => Number(value.trim()))
    .filter((value) => Number.isFinite(value) && value > 0);

  return parsed.length > 0 ? parsed : DEFAULT_OFFSETS_MINUTES[kind];
}

function getTriggerDateTimes(dateTime: string | null | undefined, kind: SavedEmbedKind): string[] {
  if (!dateTime && (kind === 'home_listing' || kind === 'travel_stay')) {
    const now = Date.now();
    return getReminderOffsets(kind)
      .map((offsetMinutes) => new Date(now + offsetMinutes * 60 * 1000).toISOString());
  }

  if (!dateTime) return [];

  const target = new Date(dateTime);
  if (Number.isNaN(target.getTime())) return [];

  const now = Date.now();
  return getReminderOffsets(kind)
    .map((offsetMinutes) => new Date(target.getTime() - offsetMinutes * 60 * 1000))
    .filter((trigger) => trigger.getTime() > now + 60 * 1000)
    .map((trigger) => trigger.toISOString());
}

export function getSavedEmbedId(config: SavedEmbedConfig): string {
  const embedId = config.itemValue.embed_id;
  return typeof embedId === 'string' ? embedId : '';
}

export function findSavedEmbedMemoryEntry(
  state: AppSettingsMemoriesStateLike,
  config: SavedEmbedConfig,
): SavedMemoryEntry | undefined {
  const appGroups = state.entriesByApp.get(config.appId);
  const entries = appGroups?.[config.itemType] || [];
  const embedId = getSavedEmbedId(config);

  return entries.find((entry) => {
    if (entry.item_key === config.itemKey) return true;
    const entryEmbedId = entry.item_value?.embed_id;
    return !!embedId && typeof entryEmbedId === 'string' && entryEmbedId === embedId;
  });
}

export function isEmbedMemorySaved(config: SavedEmbedConfig): boolean {
  return !!findSavedEmbedMemoryEntry(get(appSettingsMemoriesStore), config);
}

async function scheduleReminder(config: SavedEmbedConfig, prompt: string, triggerDatetime: string): Promise<void> {
  const embedId = getSavedEmbedId(config);
  if (!embedId) {
    throw new Error('Saved embed reminder requires an embed id');
  }

  const response = await fetch(`${getApiUrl()}/v1/apps/reminder/skills/set-reminder`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({
      prompt,
      trigger_type: 'specific',
      trigger_datetime: triggerDatetime,
      timezone: getTimezone(),
      target_type: 'embed',
      target_embed_id: embedId,
      target_embed_app_id: config.appId,
      target_embed_title: config.title,
      response_type: 'simple',
    }),
  });

  if (!response.ok) {
    throw new Error(`Reminder scheduling failed with status ${response.status}`);
  }

  const result = await response.json();
  const skillData = result.data || result;
  if (skillData.success === false) {
    throw new Error(skillData.error || 'Reminder scheduling failed');
  }
}

async function scheduleDefaultReminders(config: SavedEmbedConfig): Promise<number> {
  if (!getSavedEmbedId(config)) return 0;

  const triggerDateTimes = getTriggerDateTimes(config.reminderDateTime, config.kind);
  const reminderTitle = config.reminderPromptTitle || config.title;
  let scheduledCount = 0;
  const errors: unknown[] = [];

  for (const triggerDatetime of triggerDateTimes) {
    try {
      await scheduleReminder(config, `Reminder: ${reminderTitle}`, triggerDatetime);
      scheduledCount += 1;
    } catch (error) {
      errors.push(error);
    }
  }

  if (errors.length > 0) {
    console.warn('[savedEmbedMemoryService] Some saved embed reminders could not be scheduled:', errors);
  }

  return scheduledCount;
}

export async function forgetEmbedMemory(config: SavedEmbedConfig): Promise<void> {
  const entry = findSavedEmbedMemoryEntry(get(appSettingsMemoriesStore), config);
  if (!entry) return;

  await appSettingsMemoriesStore.deleteEntry(entry.id, config.appId);
  notificationStore.success(`Forgot "${config.title}".`);

  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('savedEmbedMemoryForgotten', {
      detail: {
        appId: config.appId,
        itemType: config.itemType,
        itemKey: config.itemKey,
        title: config.title,
        embedId: getSavedEmbedId(config),
      },
    }));
  }
}

export async function saveEmbedMemory(config: SavedEmbedConfig): Promise<void> {
  await appSettingsMemoriesStore.createEntry(config.appId, {
    item_key: config.itemKey,
    item_value: config.itemValue,
    settings_group: config.itemType,
  });

  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('savedEmbedMemorySaved', {
      detail: {
        appId: config.appId,
        itemType: config.itemType,
        itemKey: config.itemKey,
        title: config.title,
      },
    }));
  }

  const scheduledCount = await scheduleDefaultReminders(config);
  notificationStore.success(
    scheduledCount > 0
      ? `Saved "${config.title}" and created ${scheduledCount} reminder${scheduledCount === 1 ? '' : 's'}.`
      : `Saved "${config.title}".`,
  );
}

export function promptToSaveEmbedMemory(config: SavedEmbedConfig): void {
  let notificationId = '';
  notificationId = notificationStore.addNotificationWithOptions('info', {
    title: 'Save this item?',
    message: `Want to save "${config.title}" to memories?`,
    duration: 0,
    dismissible: true,
    actionLabel: 'Save',
    onAction: () => {
      if (notificationId) notificationStore.removeNotification(notificationId);
      saveEmbedMemory(config).catch((error) => {
        console.error('[savedEmbedMemoryService] Failed to save item:', error);
        notificationStore.error('Failed to save item.');
      });
    },
    secondaryActionLabel: 'No thanks',
    onSecondaryAction: () => {
      if (notificationId) notificationStore.removeNotification(notificationId);
    },
  });
}
