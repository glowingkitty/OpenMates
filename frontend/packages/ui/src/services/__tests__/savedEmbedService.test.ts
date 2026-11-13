/**
 * Save / Saved state of result embeds: encrypted flag on the embed itself,
 * no memory entry, listing and upcoming selection.
 * The embed store, decoder and revision commit are isolated; the real
 * service logic (flag toggling, selection, kind mapping) runs.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

const mocks = vi.hoisted(() => ({
  get: vi.fn(), byApp: vi.fn(), decode: vi.fn(), commit: vi.fn(), error: vi.fn(), success: vi.fn(),
}));
vi.mock('../../config/api', () => ({ getApiUrl: () => 'http://api.test', getApiEndpoint: (p: string) => p }));
vi.mock('../../stores/userProfile', async () => {
  const { writable } = await import('svelte/store');
  return { userProfile: writable({ timezone: 'Europe/Berlin' }) };
});
vi.mock('../../utils/reminderNotificationContext', async (orig) => ({
  ...(await orig<typeof import('../../utils/reminderNotificationContext')>()),
  captureReminderThumbnail: vi.fn(async () => undefined),
}));
vi.mock('../embedStore', () => ({ embedStore: { get: mocks.get, getEmbedsByAppId: mocks.byApp } }));
vi.mock('../embedResolver', () => ({ decodeToonContent: mocks.decode }));
vi.mock('../embedDiffStore', () => ({ commitEmbedContentRevision: mocks.commit }));
vi.mock('../../stores/notificationStore', () => ({ notificationStore: { error: mocks.error, success: mocks.success } }));

import {
  listSavedEmbeds, loadEmbedSaved, savedEmbedIds, selectUpcomingSavedEmbeds, setEmbedSaved,
  toggleEmbedSaved, type SavedEmbed,
} from '../savedEmbedService';
import {
  SAVED_ITEM_REMINDER_OFFSETS_MINUTES, buildSavedReminderPlan, getReminderTriggerDateTimes,
} from '../savedEmbedReminders';

const NOW = Date.parse('2026-11-07T10:00:00Z');
const contents: Record<string, Record<string, unknown>> = {};

function seed(id: string, content: Record<string, unknown>) {
  contents[id] = content;
}

beforeEach(() => {
  vi.clearAllMocks();
  for (const key of Object.keys(contents)) delete contents[key];
  savedEmbedIds.set(new Set());
  mocks.get.mockImplementation(async (ref: string) => {
    const id = ref.replace('embed:', '');
    return contents[id] ? { embed_id: id, content: JSON.stringify(contents[id]),
      app_id: id.startsWith('stay') ? 'travel' : id.startsWith('conn') ? 'travel' : 'events',
      skill_id: id.startsWith('conn') ? 'connection' : id.startsWith('stay') ? 'stay' : 'event', version_number: 3 } : null;
  });
  mocks.decode.mockImplementation(async (raw: string) => JSON.parse(raw));
  mocks.commit.mockResolvedValue({ version_number: 4, content_hash: 'h' });
  mocks.byApp.mockImplementation(async (appId: string) =>
    Object.keys(contents).map(embed_id => ({ embed_id })).filter(({ embed_id }) =>
      (appId === 'events' && embed_id.startsWith('ev')) || (appId === 'travel' && (embed_id.startsWith('stay') || embed_id.startsWith('conn')))));
});

describe('saved embed flag', () => {
  // contract-test: direct surface=gui.web assertions=app-memories.saved-items.not-memories
  it('sets the saved flag through an embed revision and creates no memory entry', async () => {
    seed('ev1', { title: 'Barcamp', date_start: '2026-11-08T10:00:00Z' });
    await setEmbedSaved('ev1', true);
    expect(mocks.commit).toHaveBeenCalledTimes(1);
    const [embedId, newContent, options] = mocks.commit.mock.calls[0];
    expect(embedId).toBe('ev1');
    const saved = JSON.parse(newContent);
    expect(saved).toMatchObject({ title: 'Barcamp', saved: true });
    expect(typeof saved.saved_at).toBe('number');
    expect(options.currentVersion).toBe(3);
    expect(options.buildRestoredContent(newContent, 4)).toMatchObject({ saved: true, version_number: 4 });
    expect(get(savedEmbedIds).has('ev1')).toBe(true);
  });

  // contract-test: direct surface=gui.web assertions=app-memories.saved-items.not-memories
  it('clears the flag again and is a no-op when the state already matches', async () => {
    seed('ev1', { title: 'Barcamp', saved: true, saved_at: 5 });
    await setEmbedSaved('ev1', true);
    expect(mocks.commit).not.toHaveBeenCalled();
    await setEmbedSaved('ev1', false);
    const cleared = JSON.parse(mocks.commit.mock.calls[0][1]);
    expect(cleared).not.toHaveProperty('saved');
    expect(cleared).not.toHaveProperty('saved_at');
    expect(get(savedEmbedIds).has('ev1')).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.saved-items.not-memories
  it('loads persisted state and reports failures instead of silently flipping', async () => {
    seed('ev1', { title: 'Barcamp', saved: true });
    expect(await loadEmbedSaved('ev1')).toBe(true);
    expect(await toggleEmbedSaved('ev1')).toBe(false);
    mocks.commit.mockRejectedValueOnce(new Error('Embed is not writable on this device'));
    seed('ev2', { title: 'Other' });
    expect(await toggleEmbedSaved('ev2')).toBe(false);
    expect(mocks.error).toHaveBeenCalledWith('Embed is not writable on this device');
    await expect(setEmbedSaved('missing', true)).rejects.toThrow('not available');
  });
});

describe('saved embed listing and upcoming selection', () => {
  // contract-test: direct surface=gui.web assertions=app-memories.saved-items.not-memories
  it('lists every saved embed with kind and dates', async () => {
    seed('ev1', { title: 'Tomorrow event', date_start: '2026-11-08T10:00:00Z', saved: true, saved_at: 10 });
    seed('ev2', { title: 'Not saved', date_start: '2026-11-08T10:00:00Z' });
    seed('conn1', { route_display: 'Berlin to Paris', departure: '2026-11-09T08:00:00Z', saved: true, saved_at: 20 });
    seed('stay1', { name: 'Hotel', check_in: '2026-10-01', saved: true, saved_at: 5 });
    const items = await listSavedEmbeds();
    expect(items.map(i => i.embedId)).toEqual(['conn1', 'ev1', 'stay1']);
    expect(items[0]).toMatchObject({ kind: 'travel_connection', title: 'Berlin to Paris' });
    expect([...get(savedEmbedIds)].sort()).toEqual(['conn1', 'ev1', 'stay1']);
  });

  // contract-test: direct surface=gui.web assertions=app-memories.saved-items.not-memories
  it('selects only future-starting events, connections and stays, soonest first', () => {
    const item = (embedId: string, kind: SavedEmbed['kind'], itemValue: Record<string, unknown>): SavedEmbed =>
      ({ embedId, appId: 'x', kind, title: embedId, savedAt: 0, itemValue });
    const upcoming = selectUpcomingSavedEmbeds([
      item('later', 'travel_connection', { departure: '2026-11-20T08:00:00Z' }),
      item('tomorrow', 'event', { date_start: '2026-11-08T10:00:00Z' }),
      item('past', 'event', { date_start: '2026-11-01T10:00:00Z' }),
      item('undated', 'travel_stay', {}),
      item('listing', 'home_listing', { available_from: '2026-12-01' }),
    ], NOW);
    expect(upcoming.map(i => i.embedId)).toEqual(['tomorrow', 'later']);
  });
});


// contract-test: supporting surface=gui.web assertions=app-memories.saved-items.not-memories
describe('reminder on save', () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ data: { success: true } }) });
    vi.stubGlobal('fetch', fetchMock);
  });

  it('schedules default-offset reminders for a saved item with a future date and time', async () => {
    const start = new Date(Date.now() + 30 * 24 * 3600 * 1000).toISOString();
    seed('ev1', { title: 'Barcamp', date_start: start, venue_name: 'Hall', chat_id: 'chat-1' });
    await setEmbedSaved('ev1', true);
    expect(fetchMock).toHaveBeenCalledTimes(SAVED_ITEM_REMINDER_OFFSETS_MINUTES.event.length);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://api.test/v1/apps/reminder/skills/set-reminder');
    const body = JSON.parse(init.body);
    expect(body).toMatchObject({
      prompt: 'Reminder: Barcamp', trigger_type: 'specific', target_type: 'embed',
      target_embed_id: 'ev1', target_embed_app_id: 'events', timezone: 'Europe/Berlin', chat_id: 'chat-1',
    });
    expect(body.notification_context).toMatchObject({ version: 1, kind: 'event', title: 'Barcamp', location: 'Hall' });
    expect(mocks.success).toHaveBeenCalledWith('Saved and created 3 reminders.');
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.saved-items.not-memories
  it('schedules nothing for undated, past or unsaving actions', async () => {
    seed('ev1', { title: 'No date' });
    await setEmbedSaved('ev1', true);
    seed('ev2', { title: 'Past', date_start: '2020-01-01T10:00:00Z' });
    await setEmbedSaved('ev2', true);
    seed('ev3', { title: 'Saved', date_start: new Date(Date.now() + 9e9).toISOString(), saved: true });
    await setEmbedSaved('ev3', false);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(mocks.success).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.saved-items.not-memories
  it('keeps saving when the reminder API fails', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 500 });
    seed('ev1', { title: 'Barcamp', date_start: new Date(Date.now() + 9e9).toISOString() });
    await expect(setEmbedSaved('ev1', true)).resolves.toBe(true);
    expect(mocks.commit).toHaveBeenCalledTimes(1);
    expect(mocks.success).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.saved-items.not-memories
  it('extracts dates per kind and filters offsets already in the past', () => {
    const now = Date.parse('2026-11-07T10:00:00Z');
    expect(buildSavedReminderPlan('travel_connection', 'travel', { route_display: 'A to B',
      legs: [{ departure: '2026-12-01T08:00:00Z' }] })?.reminderDateTime).toBe('2026-12-01T08:00:00Z');
    expect(buildSavedReminderPlan('travel_stay', 'travel', { name: 'Hotel', check_in: '2026-12-01' })?.title).toBe('Hotel');
    expect(buildSavedReminderPlan('home_listing', 'home', { title: 'Flat', available_from: '2026-12-01' })?.reminderDateTime).toBe('2026-12-01');
    const health = buildSavedReminderPlan('health_appointment', 'health', { name: 'Dr X', slot_datetime: '2026-12-01T09:30:00Z' });
    expect(health?.promptTitle).toContain('Dr X at ');
    expect(health?.notificationContext.kind).toBe('appointment');
    expect(buildSavedReminderPlan('event', 'events', { title: 'x', date_start: 'garbage' })).toBeNull();
    expect(buildSavedReminderPlan('home_listing', 'home', { title: 'Flat' })).toBeNull();
    // Event 2h away: only the 60 min offset remains.
    expect(getReminderTriggerDateTimes('event', '2026-11-07T12:00:00Z', now)).toEqual(['2026-11-07T11:00:00.000Z']);
  });
});
