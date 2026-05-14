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
import { authStore } from '../stores/authStore';

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

interface BuildSavedEmbedConfigOptions {
  appId: string | null;
  skillId: string | null;
  embedId: string;
  decodedContent: Record<string, unknown>;
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

function asString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

function asNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

function formatAppointmentSlot(iso: string | undefined): string {
  if (!iso) return '';
  try {
    const dt = new Date(iso);
    return dt.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })
      + ' | '
      + dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return iso;
  }
}

function getSlotDate(iso: string | undefined): string {
  if (!iso) return '';
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso.split('T')[0] || iso;
  return parsed.toISOString().split('T')[0];
}

function parseEventVenue(content: Record<string, unknown>): string {
  const venue = content.venue;
  if (venue && typeof venue === 'object') {
    const v = venue as Record<string, unknown>;
    return [v.name, v.address, v.city, v.state, v.country]
      .filter((part): part is string => typeof part === 'string' && part.trim().length > 0)
      .join('\n');
  }

  return [content.venue_name, content.venue_address, content.venue_city, content.venue_state, content.venue_country]
    .filter((part): part is string => typeof part === 'string' && part.trim().length > 0)
    .join('\n');
}

function getEventProviderLabel(provider: string | undefined): string {
  switch (provider?.toLowerCase()) {
    case 'meetup': return 'Meetup';
    case 'luma': return 'Luma';
    case 'eventbrite': return 'Eventbrite';
    case 'classictic': return 'Classictic';
    case 'berlin_philharmonic': return 'Berlin Philharmonic';
    case 'bachtrack': return 'Bachtrack';
    default: return provider || '';
  }
}

export function buildSavedEmbedConfigFromDecodedContent({
  appId,
  skillId,
  embedId,
  decodedContent,
}: BuildSavedEmbedConfigOptions): SavedEmbedConfig | null {
  if (!embedId) return null;

  if (appId === 'events' && skillId === 'event') {
    const title = asString(decodedContent.title) || 'Event';
    const provider = asString(decodedContent.provider);
    const eventType = asString(decodedContent.event_type);
    const venueAddress = parseEventVenue(decodedContent);
    return {
      kind: 'event',
      appId: 'events',
      itemType: 'saved_events',
      itemKey: `saved_events.${asString(decodedContent.id) || asString(decodedContent.url) || title}`,
      title,
      reminderDateTime: asString(decodedContent.date_start) || null,
      reminderPromptTitle: title,
      itemValue: {
        embed_id: embedId,
        title,
        provider: getEventProviderLabel(provider) || provider || '',
        url: asString(decodedContent.url) || '',
        date_start: asString(decodedContent.date_start) || '',
        date_end: asString(decodedContent.date_end) || '',
        location: eventType === 'ONLINE' ? 'Online event' : venueAddress,
        notes: '',
      },
    };
  }

  if (appId === 'home' && skillId === 'listing') {
    const title = asString(decodedContent.title) || 'Listing';
    const url = asString(decodedContent.url) || '';
    const size = asNumber(decodedContent.size_sqm);
    const rooms = asNumber(decodedContent.rooms);
    const notes = [
      size ? `${size} m\u00B2` : '',
      rooms ? `${rooms} ${rooms === 1 ? 'room' : 'rooms'}` : '',
      asString(decodedContent.listing_type),
    ].filter(Boolean).join(' | ');
    return {
      kind: 'home_listing',
      appId: 'home',
      itemType: 'saved_listings',
      itemKey: `saved_listings.${url || title}`,
      title,
      reminderDateTime: asString(decodedContent.available_from) || null,
      reminderPromptTitle: title,
      itemValue: {
        embed_id: embedId,
        title,
        url,
        provider: asString(decodedContent.provider) || '',
        price_label: asString(decodedContent.price_label) || '',
        address: asString(decodedContent.address) || '',
        available_from: asString(decodedContent.available_from) || '',
        notes,
      },
    };
  }

  if (appId === 'travel' && (skillId === 'stay' || skillId === 'search_stays')) {
    const title = asString(decodedContent.name) || 'Stay';
    const url = asString(decodedContent.link) || '';
    const currency = asString(decodedContent.currency) || 'EUR';
    const totalPrice = asNumber(decodedContent.extracted_total_rate);
    const nightPrice = asNumber(decodedContent.extracted_rate_per_night);
    const nearbyPlaces = Array.isArray(decodedContent.nearby_places) ? decodedContent.nearby_places : [];
    const amenities = Array.isArray(decodedContent.amenities) ? decodedContent.amenities : [];
    return {
      kind: 'travel_stay',
      appId: 'travel',
      itemType: 'saved_stays',
      itemKey: `saved_stays.${asString(decodedContent.hash) || url || title}`,
      title,
      reminderDateTime: null,
      reminderPromptTitle: title,
      itemValue: {
        embed_id: embedId,
        name: title,
        property_type: asString(decodedContent.property_type) || '',
        url,
        price: totalPrice != null ? `${currency} ${Math.round(totalPrice)}` : (nightPrice != null ? `${currency} ${Math.round(nightPrice)}/night` : ''),
        rating: asNumber(decodedContent.overall_rating),
        location: nearbyPlaces
          .map((place) => place && typeof place === 'object' ? asString((place as Record<string, unknown>).name) : undefined)
          .filter(Boolean)
          .join(', '),
        notes: amenities.filter((item): item is string => typeof item === 'string').slice(0, 8).join(', '),
      },
    };
  }

  if (appId === 'travel' && skillId === 'connection') {
    const title = asString(decodedContent.route_display) || asString(decodedContent.title) || 'Travel connection';
    const legs = Array.isArray(decodedContent.legs) ? decodedContent.legs as Array<Record<string, unknown>> : [];
    const firstLeg = legs[0] || {};
    const lastLeg = legs.length > 0 ? legs[legs.length - 1] : {};
    const bookingUrl = asString(decodedContent.booking_url) || '';
    return {
      kind: 'travel_connection',
      appId: 'travel',
      itemType: 'saved_connections',
      itemKey: `saved_connections.${asString(decodedContent.hash) || bookingUrl || title}`,
      title,
      reminderDateTime: asString(decodedContent.departure) || asString(firstLeg.departure) || null,
      reminderPromptTitle: title,
      itemValue: {
        embed_id: embedId,
        title,
        transport_method: asString(decodedContent.transport_method) || '',
        origin: asString(decodedContent.origin) || asString(firstLeg.origin) || '',
        destination: asString(decodedContent.destination) || asString(lastLeg.destination) || '',
        departure: asString(decodedContent.departure) || asString(firstLeg.departure) || '',
        arrival: asString(decodedContent.arrival) || asString(lastLeg.arrival) || '',
        booking_url: bookingUrl,
        provider: asString(decodedContent.booking_provider) || '',
        notes: [asString(decodedContent.trip_type), asString(decodedContent.price), asString(decodedContent.duration)].filter(Boolean).join(' | '),
      },
    };
  }

  if (appId === 'health' && skillId === 'appointment') {
    const slot = asString(decodedContent.slot_datetime);
    const title = asString(decodedContent.name) || asString(decodedContent.speciality) || 'Appointment';
    const bookingUrl = asString(decodedContent.booking_url) || asString(decodedContent.practice_url) || '';
    return {
      kind: 'health_appointment',
      appId: 'health',
      itemType: 'appointments',
      itemKey: `appointments.${bookingUrl || title}.${slot || ''}`,
      title,
      reminderDateTime: slot,
      reminderPromptTitle: `${title}${slot ? ` at ${formatAppointmentSlot(slot)}` : ''}`,
      itemValue: {
        embed_id: embedId,
        title: slot ? formatAppointmentSlot(slot) : title,
        appointment_type: 'doctor_visit',
        where: [asString(decodedContent.name), asString(decodedContent.speciality)].filter(Boolean).join(' | '),
        date: getSlotDate(slot),
        notes: [asString(decodedContent.address), bookingUrl].filter(Boolean).join('\n'),
      },
    };
  }

  return null;
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
  if (!get(authStore).isAuthenticated) return;
  if (isEmbedMemorySaved(config)) return;

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
