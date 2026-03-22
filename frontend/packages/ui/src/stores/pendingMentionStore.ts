// frontend/packages/ui/src/stores/pendingMentionStore.ts
/**
 * @file pendingMentionStore.ts
 * @description Store for passing a pending @-mention from the settings panel
 * to the message input. When the user clicks "Chat with this mate" on a mate
 * detail page, the mate mention (@mate:{mateId}) is stored here and the
 * settings panel is closed. MessageInput picks it up, inserts the mention text,
 * and clears the store.
 *
 * Architecture:
 * - MateDetails.svelte: sets pendingMentionStore to "@mate:{mateId}" and calls
 *   panelState.closeSettings()
 * - MessageInput.svelte: watches this store in a $effect; when a value is set it
 *   inserts the text into the TipTap editor and clears the store.
 */
import { writable } from "svelte/store";

/**
 * Pending mention text (e.g. "@mate:software_development") or null when idle.
 * MessageInput consumes and clears this on the next render after it is set.
 */
export const pendingMentionStore = writable<string | null>(null);
