// frontend/packages/ui/src/services/savedEmbedReminders.ts
//
// Reminder-on-save for result embeds. Saving an event, stay, connection, home
// listing or health appointment that carries an actual date (and time) schedules
// passive reminders through the Reminder app, exactly like the former memory
// based save flow. Items without a parseable date never get a reminder.
//
// Offsets are constants for now; user-configurable offsets move to the Reminder
// app settings in a later slice (typed memories no longer exist).

import { get } from 'svelte/store';
import { getApiUrl } from '../config/api';
import { userProfile } from '../stores/userProfile';
import {
  buildReminderNotificationContext,
  captureReminderThumbnail,
  reminderTimeZone,
  type ReminderNotificationContext,
} from '../utils/reminderNotificationContext';
import { buildWorkBody, workClient, workDecide, type WorkRequest } from './work/workRust';

// Flag-on builds decide the plan, trigger instants and set-reminder body of the
// async scheduleSavedEmbedReminders in the shared Rust core Worker (`work` op,
// web_work/reminders.rs); the constant folds to false otherwise, so flag-off
// keeps the original code. The page keeps fetch, the thumbnail, the response
// handling, every Date parse, the locale slot label and the Intl zone check.
// The synchronous buildSavedReminderPlan / getReminderTriggerDateTimes and
// buildReminderNotificationContext (SettingsReminders) stay TypeScript.
const RUST_WORK = import.meta.env.VITE_OPENMATES_RUST_CORE === '1';

/** Content members whose strings the Rust op reads as dates (start and end candidates). */
const REMINDER_DATE_KEYS = [
  'date_start', 'available_from', 'check_in', 'check_in_date', 'departure', 'slot_datetime',
  'appointment_time', 'date_end', 'arrival', 'check_out', 'check_out_date',
] as const;

export type SavedReminderKind =
  | 'event'
  | 'travel_connection'
  | 'travel_stay'
  | 'home_listing'
  | 'health_appointment';

const DAY = 24 * 60;

/** Minutes before the item's start at which a reminder fires, per kind. */
export const SAVED_ITEM_REMINDER_OFFSETS_MINUTES: Record<SavedReminderKind, number[]> = {
  event: [7 * DAY, 12 * 60, 60],
  travel_connection: [30 * DAY, 7 * DAY, DAY, 3 * 60],
  travel_stay: [DAY, 7 * DAY],
  home_listing: [DAY, 3 * DAY],
  health_appointment: [7 * DAY, DAY, 3 * 60],
};

export interface SavedReminderPlan {
  /** Item start (ISO or date string); reminders are offsets before it. */
  reminderDateTime: string;
  promptTitle: string;
  title: string;
  notificationContext: ReminderNotificationContext;
  sourceChatId?: string;
  thumbnailUrl?: string;
}

function str(value: unknown): string | undefined {
  return typeof value === 'string' && value ? value : undefined;
}

function formatAppointmentSlot(iso: string): string {
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return iso;
  return dt.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })
    + ' | ' + dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function eventVenue(content: Record<string, unknown>): string {
  const venue = content.venue;
  const parts = venue && typeof venue === 'object'
    ? (['name', 'address', 'city', 'state', 'country'] as const).map((k) => (venue as Record<string, unknown>)[k])
    : [content.venue_name, content.venue_address, content.venue_city, content.venue_state, content.venue_country];
  return parts.filter((p): p is string => typeof p === 'string' && p.trim().length > 0).join('\n');
}

/** Extract the reminder plan for a saved embed, or null when it has no concrete date. */
export function buildSavedReminderPlan(
  kind: SavedReminderKind | null,
  appId: string,
  content: Record<string, unknown>,
  chatId?: string,
): SavedReminderPlan | null {
  if (!kind) return null;
  const legs = Array.isArray(content.legs) ? content.legs as Array<Record<string, unknown>> : [];
  let title: string;
  let when: string | undefined;
  let promptTitle: string | undefined;
  const fields: Record<string, unknown> = { ...content };
  switch (kind) {
    case 'event':
      title = str(content.title) || 'Event';
      when = str(content.date_start);
      fields.location = eventVenue(content) || (content.event_type === 'ONLINE' ? 'Online event' : '');
      break;
    case 'home_listing':
      title = str(content.title) || 'Listing';
      when = str(content.available_from);
      break;
    case 'travel_stay':
      title = str(content.name) || 'Stay';
      when = str(content.check_in) || str(content.check_in_date);
      break;
    case 'travel_connection':
      title = str(content.route_display) || str(content.title) || 'Travel connection';
      when = str(content.departure) || str(legs[0]?.departure);
      break;
    case 'health_appointment': {
      title = str(content.name) || str(content.speciality) || 'Appointment';
      when = str(content.slot_datetime);
      if (when) promptTitle = `${title} at ${formatAppointmentSlot(when)}`;
      break;
    }
  }
  if (!when || Number.isNaN(new Date(when).getTime())) return null;
  const contextKind = kind === 'health_appointment' ? 'appointment' : kind;
  return {
    reminderDateTime: when,
    title,
    promptTitle: promptTitle || title,
    notificationContext: buildReminderNotificationContext(contextKind, title, fields, appId),
    sourceChatId: str(chatId) || str(content.chat_id),
    thumbnailUrl: str(content.image_url) || str(content.cover_url) || str(content.thumbnail_url),
  };
}

/** Future trigger instants (ISO) for a start time, at least a minute ahead. */
export function getReminderTriggerDateTimes(
  kind: SavedReminderKind,
  dateTime: string,
  nowMs: number = Date.now(),
): string[] {
  const target = new Date(dateTime).getTime();
  if (Number.isNaN(target)) return [];
  return SAVED_ITEM_REMINDER_OFFSETS_MINUTES[kind]
    .map((offset) => target - offset * 60 * 1000)
    .filter((trigger) => trigger > nowMs + 60 * 1000)
    .map((trigger) => new Date(trigger).toISOString());
}

async function postReminder(
  embedId: string, appId: string, plan: SavedReminderPlan,
  context: ReminderNotificationContext, triggerDatetime: string,
): Promise<void> {
  const response = await fetch(`${getApiUrl()}/v1/apps/reminder/skills/set-reminder`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({
      prompt: `Reminder: ${plan.promptTitle}`,
      trigger_type: 'specific',
      trigger_datetime: triggerDatetime,
      timezone: get(userProfile).timezone || Intl.DateTimeFormat().resolvedOptions().timeZone,
      target_type: 'embed',
      target_embed_id: embedId,
      target_embed_app_id: appId,
      target_embed_title: plan.title,
      notification_context: context,
      ...(plan.sourceChatId ? { chat_id: plan.sourceChatId } : {}),
      response_type: 'simple',
    }),
  });
  if (!response.ok) throw new Error(`Reminder scheduling failed with status ${response.status}`);
  const result = await response.json();
  const data = result.data || result;
  if (data.success === false) throw new Error(data.error || 'Reminder scheduling failed');
}

/** A schedule answered by the Rust `reminderSavedSchedule` op. */
interface RustReminderSchedule {
  title: string;
  promptTitle: string;
  sourceChatId?: string;
  thumbnailUrl?: string;
  context: Array<[string, unknown]>;
  triggers: string[];
  request: WorkRequest;
}

/**
 * The `reminderSavedSchedule` input: the page's own facts the Worker cannot
 * make (browser `Date` parses of every candidate date string, the locale slot
 * label and the Intl-validated zone) next to the saved item itself.
 */
export function savedReminderScheduleInput(
  embedId: string, kind: SavedReminderKind | null, appId: string,
  content: Record<string, unknown>, chatId: string | undefined, nowMs: number,
): Record<string, unknown> {
  const dates: Record<string, number | null> = {};
  const add = (value: unknown) => {
    if (typeof value !== 'string') return;
    const ms = new Date(value).getTime();
    dates[value] = Number.isNaN(ms) ? null : ms;
  };
  for (const key of REMINDER_DATE_KEYS) add(content[key]);
  if (Array.isArray(content.legs)) add((content.legs[0] as Record<string, unknown> | null | undefined)?.departure);
  const slot = kind === 'health_appointment' ? str(content.slot_datetime) : undefined;
  return {
    embedId, kind, appId, content, chatId, nowMs, dates,
    slotLabel: slot ? formatAppointmentSlot(slot) : undefined,
    timezone: reminderTimeZone(content),
  };
}

async function scheduleWithRust(
  work: NonNullable<ReturnType<typeof workClient>>, embedId: string, kind: SavedReminderKind | null,
  appId: string, content: Record<string, unknown>, chatId?: string,
): Promise<number> {
  const input = savedReminderScheduleInput(embedId, kind, appId, content, chatId, Date.now());
  const { schedule } = await workDecide<{ schedule: RustReminderSchedule | null }>(work, 'reminderSavedSchedule', input);
  if (!schedule) return 0;
  const image = await captureReminderThumbnail(schedule.thumbnailUrl);
  const base = Object.fromEntries(schedule.context) as unknown as ReminderNotificationContext;
  const context = image ? { ...base, image_base64: image } : base;
  let scheduled = 0;
  const errors: unknown[] = [];
  for (const trigger of schedule.triggers) {
    try {
      const body = await buildWorkBody(schedule.request.steps, {}, {}, {
        trigger_datetime: () => trigger,
        timezone: () => get(userProfile).timezone || Intl.DateTimeFormat().resolvedOptions().timeZone,
        notification_context: () => context,
      });
      const response = await fetch(`${getApiUrl()}${schedule.request.path}`, {
        method: schedule.request.method,
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(`Reminder scheduling failed with status ${response.status}`);
      const result = await response.json();
      const data = result.data || result;
      if (data.success === false) throw new Error(data.error || 'Reminder scheduling failed');
      scheduled += 1;
    } catch (error) {
      errors.push(error);
    }
  }
  if (errors.length > 0) console.warn('[savedEmbedReminders] Some reminders could not be scheduled:', errors);
  return scheduled;
}

/** Schedule the default reminders; returns how many were created. */
export async function scheduleSavedEmbedReminders(
  embedId: string, kind: SavedReminderKind | null, appId: string,
  content: Record<string, unknown>, chatId?: string,
): Promise<number> {
  const work = RUST_WORK ? workClient() : null;
  if (work) return scheduleWithRust(work, embedId, kind, appId, content, chatId);
  const plan = buildSavedReminderPlan(kind, appId, content, chatId);
  if (!plan || !kind || !embedId) return 0;
  const triggers = getReminderTriggerDateTimes(kind, plan.reminderDateTime);
  if (triggers.length === 0) return 0;

  const image = await captureReminderThumbnail(plan.thumbnailUrl);
  const context = image ? { ...plan.notificationContext, image_base64: image } : plan.notificationContext;
  let scheduled = 0;
  const errors: unknown[] = [];
  for (const trigger of triggers) {
    try {
      await postReminder(embedId, appId, plan, context, trigger);
      scheduled += 1;
    } catch (error) {
      errors.push(error);
    }
  }
  if (errors.length > 0) console.warn('[savedEmbedReminders] Some reminders could not be scheduled:', errors);
  return scheduled;
}
