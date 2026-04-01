/**
 * reminderContextStore — Passes chat context from ActiveChat to SettingsReminders
 * when the user clicks the reminder bell button.
 *
 * Stores the chat ID so SettingsReminders can load the full chat object from
 * IndexedDB (for rendering the chat preview with icon, gradient, and title).
 * The store value is set before opening the reminder deep link and cleared
 * when the settings page unmounts.
 */

import { writable } from 'svelte/store';

export interface ReminderContext {
	/** Chat ID from which the reminder was initiated */
	chatId: string;
}

export const reminderContext = writable<ReminderContext | null>(null);
