// frontend/packages/ui/src/stores/pendingRememberMessageStore.ts
//
// Carries an explicit "remember this forgotten message" draft insertion request
// from rendered chat history or context menus into the active MessageInput.
// MessageInput consumes and clears the value, mirroring pendingMentionStore.
// The payload is already formatted markdown text and is never auto-sent.

import { writable } from 'svelte/store';

export const pendingRememberMessageStore = writable<string | null>(null);
