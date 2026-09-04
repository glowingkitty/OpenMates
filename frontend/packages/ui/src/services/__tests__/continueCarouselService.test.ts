// frontend/packages/ui/src/services/__tests__/continueCarouselService.test.ts
//
// Unit coverage for the welcome carousel priority classifier. These tests keep
// the reminder/date promotion rules independent from the Svelte component so the
// sidebar's chronological sort can remain unchanged while the welcome carousel
// promotes only near-term reminders and saved dated embeds.
//

import { describe, expect, it } from 'vitest';
import {
  buildReminderPriority,
  getReminderByTargetChatId,
  getReminderByTargetEmbedId,
  getSavedEmbedContinueCandidates,
  sortContinuePriorityItems,
  type ActiveReminderForContinue,
} from '../continueCarouselService';

const NOW_MS = new Date(2026, 4, 13, 9, 0, 0).getTime();
const NOW_SECONDS = Math.floor(NOW_MS / 1000);

function reminder(overrides: Partial<ActiveReminderForContinue>): ActiveReminderForContinue {
  return {
    reminder_id: overrides.reminder_id || 'reminder-1',
    trigger_at: overrides.trigger_at ?? NOW_SECONDS,
    target_type: overrides.target_type || 'existing_chat',
    target_chat_id: overrides.target_chat_id ?? 'chat-1',
    target_embed_id: overrides.target_embed_id ?? null,
    status: overrides.status || 'pending',
  };
}

describe('continueCarouselService', () => {
  // contract-test: direct surface=gui.web assertions=continue-carousel.chat.reminder-gated
  it('classifies recent due and upcoming reminders', () => {
    expect(buildReminderPriority(reminder({ trigger_at: NOW_SECONDS - 30 * 60 }), NOW_MS)?.reason).toBe('reminder_due');
    expect(buildReminderPriority(reminder({ trigger_at: NOW_SECONDS + 2 * 60 * 60 }), NOW_MS)?.reason).toBe('reminder_soon');
    expect(buildReminderPriority(reminder({ trigger_at: NOW_SECONDS + 26 * 60 * 60 }), NOW_MS)).toBeNull();
    expect(buildReminderPriority(reminder({ trigger_at: NOW_SECONDS - 13 * 60 * 60, status: 'fired' }), NOW_MS)).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=continue-carousel.chat.reminder-gated
  it('indexes the best chat and embed reminder by target id', () => {
    const reminders = [
      reminder({ reminder_id: 'later', trigger_at: NOW_SECONDS + 4 * 60 * 60, target_chat_id: 'chat-a' }),
      reminder({ reminder_id: 'soon', trigger_at: NOW_SECONDS + 30 * 60, target_chat_id: 'chat-a' }),
      reminder({ reminder_id: 'embed', target_type: 'embed', target_chat_id: null, target_embed_id: 'embed-a', trigger_at: NOW_SECONDS - 20 * 60 }),
    ];

    expect(getReminderByTargetChatId(reminders, NOW_MS).get('chat-a')?.reminder.reminder_id).toBe('soon');
    expect(getReminderByTargetEmbedId(reminders, NOW_MS).get('embed-a')?.reminder.reminder_id).toBe('embed');
  });

  // contract-test: direct surface=gui.web assertions=continue-carousel.saved-item.start-time-gated
  it('gates dated saved embeds by item start instead of linked reminder time', () => {
    const entriesByApp = new Map([
      ['events', {
        saved_events: [
          {
            id: 'future-entry',
            item_key: 'future',
            settings_group: 'saved_events',
            item_value: {
              embed_id: 'future-embed',
              title: 'Tonight event',
              date_start: new Date(NOW_MS + 3 * 60 * 60 * 1000).toISOString(),
            },
          },
          {
            id: 'ongoing-entry',
            item_key: 'ongoing',
            settings_group: 'saved_events',
            item_value: {
              embed_id: 'ongoing-embed',
              title: 'Conference',
              date_start: new Date(NOW_MS - 2 * 24 * 60 * 60 * 1000).toISOString(),
              date_end: new Date(NOW_MS + 5 * 60 * 60 * 1000).toISOString(),
            },
          },
          {
            id: 'old-entry',
            item_key: 'old',
            settings_group: 'saved_events',
            item_value: {
              embed_id: 'old-embed',
              title: 'Old event',
              date_start: new Date(NOW_MS - 13 * 60 * 60 * 1000).toISOString(),
            },
          },
        ],
      }],
      ['health', {
        appointments: [
          {
            id: 'far-appointment-entry',
            item_key: 'far-appointment',
            settings_group: 'appointments',
            item_value: {
              embed_id: 'far-appointment-embed',
              title: 'Friday appointment',
              appointment_time: new Date(NOW_MS + 46 * 60 * 60 * 1000).toISOString(),
            },
          },
          {
            id: 'near-appointment-entry',
            item_key: 'near-appointment',
            settings_group: 'appointments',
            item_value: {
              embed_id: 'near-appointment-embed',
              title: 'Thursday appointment',
              appointment_time: new Date(NOW_MS + 23 * 60 * 60 * 1000).toISOString(),
            },
          },
          {
            id: 'legacy-far-appointment-entry',
            item_key: 'legacy-far-appointment',
            settings_group: 'appointments',
            item_value: {
              embed_id: 'legacy-far-appointment-embed',
              title: 'Legacy Friday appointment',
              date: '2026-05-14',
            },
          },
        ],
      }],
      ['home', {
        saved_listings: [
          {
            id: 'undated-listing-entry',
            item_key: 'undated-listing',
            settings_group: 'saved_listings',
            item_value: {
              embed_id: 'undated-listing-embed',
              title: 'Saved listing',
            },
          },
        ],
      }],
    ]);

    const reminders = [
      reminder({ target_type: 'embed', target_chat_id: null, target_embed_id: 'future-embed', trigger_at: NOW_SECONDS + 15 * 60 }),
      reminder({ target_type: 'embed', target_chat_id: null, target_embed_id: 'far-appointment-embed', trigger_at: NOW_SECONDS + 22 * 60 * 60 }),
      reminder({ target_type: 'embed', target_chat_id: null, target_embed_id: 'near-appointment-embed', trigger_at: NOW_SECONDS + 2 * 60 * 60 }),
      reminder({ target_type: 'embed', target_chat_id: null, target_embed_id: 'legacy-far-appointment-embed', trigger_at: NOW_SECONDS + 22 * 60 * 60 }),
      reminder({ target_type: 'embed', target_chat_id: null, target_embed_id: 'undated-listing-embed', trigger_at: NOW_SECONDS + 60 * 60 }),
    ];
    const remindersByEmbedId = getReminderByTargetEmbedId(reminders, NOW_MS);

    const candidates = getSavedEmbedContinueCandidates(
      { entriesByApp },
      remindersByEmbedId,
      NOW_MS,
    );

    expect(candidates.map((candidate) => candidate.embedId)).toEqual([
      'undated-listing-embed',
      'ongoing-embed',
      'future-embed',
      'near-appointment-embed',
    ]);
    expect(candidates.find((candidate) => candidate.embedId === 'far-appointment-embed')).toBeUndefined();
    expect(candidates.find((candidate) => candidate.embedId === 'legacy-far-appointment-embed')).toBeUndefined();
    expect(candidates.find((candidate) => candidate.embedId === 'undated-listing-embed')?.priority.reason).toBe('reminder_soon');
    expect(candidates.find((candidate) => candidate.embedId === 'future-embed')?.priority.label).toBe('Event in 3h');
    expect(candidates.find((candidate) => candidate.embedId === 'near-appointment-embed')?.priority.label).toBe('Appointment in 23h');
  });

  // contract-test: direct surface=gui.web assertions=continue-carousel.saved-item.start-time-gated
  it('keeps date-only appointment labels at calendar-day precision', () => {
    const entriesByApp = new Map([
      ['health', {
        appointments: [
          {
            id: 'legacy-today-appointment-entry',
            item_key: 'legacy-today-appointment',
            settings_group: 'appointments',
            item_value: {
              embed_id: 'legacy-today-appointment-embed',
              title: 'Legacy Wednesday appointment',
              date: '2026-05-13',
            },
          },
        ],
      }],
    ]);

    const candidates = getSavedEmbedContinueCandidates({ entriesByApp }, new Map(), NOW_MS);

    expect(candidates).toHaveLength(1);
    expect(candidates[0].priority.label).toBe('Appointment today');
  });

  // contract-test: supporting surface=gui.web assertions=continue-carousel.saved-item.start-time-gated,continue-carousel.chat.reminder-gated
  it('sorts reminder priorities before saved-date priorities', () => {
    const sorted = sortContinuePriorityItems([
      { id: 'upcoming-date', priority: { reason: 'upcoming_saved_item' as const, label: 'Event in 1h', timestamp: NOW_MS + 60 * 60 * 1000 } },
      { id: 'reminder', priority: { reason: 'reminder_soon' as const, label: 'Reminder in 3h', timestamp: NOW_MS + 3 * 60 * 60 * 1000 } },
      { id: 'due', priority: { reason: 'reminder_due' as const, label: 'Reminder 5m ago', timestamp: NOW_MS - 5 * 60 * 1000 } },
    ], NOW_MS);

    expect(sorted.map((item) => item.id)).toEqual(['due', 'reminder', 'upcoming-date']);
  });
});
