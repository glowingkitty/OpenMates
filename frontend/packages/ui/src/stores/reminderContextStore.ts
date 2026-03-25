/**
 * reminderContextStore — Lightweight store to pass chat context from ActiveChat
 * to SettingsReminders when the user clicks the reminder bell button.
 *
 * Set before opening the reminder settings deep link, read by SettingsReminders
 * to show which chat the reminder relates to and support "This chat" target.
 */

import { writable } from 'svelte/store';

export interface ReminderContext {
    chatId: string;
    chatTitle: string;
}

export const reminderContext = writable<ReminderContext | null>(null);
