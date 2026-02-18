/**
 * frontend/packages/ui/src/stores/embedPIIStore.ts
 *
 * Reactive store that holds the PII masking state for the currently active chat,
 * specifically for use by embed preview and fullscreen components.
 *
 * Why this store exists:
 * - Embed preview components (DocsEmbedPreview, CodeEmbedPreview, SheetEmbedPreview)
 *   are mounted imperatively via mount() in GroupRenderer.ts. They cannot receive
 *   reactive Svelte props from a parent component at mount time — they need a way
 *   to reactively subscribe to PII state changes.
 * - This store is updated by ActiveChat.svelte whenever the current chat's PII
 *   mappings or reveal state changes, making it available to all embed components.
 *
 * Usage:
 * - ActiveChat.svelte: writes to this store via setEmbedPIIState() when chat changes
 *   or when the user toggles PII visibility.
 * - Embed preview/fullscreen components: read from this store to apply PII masking.
 */

import { writable, derived, get } from "svelte/store";
import type { PIIMapping } from "../types/chat";

/**
 * The current PII masking state for the active chat.
 * - mappings: Cumulative PIIMapping array from all user messages in the current chat.
 *   These map placeholder strings (e.g. "[EMAIL_1]") to original values.
 * - revealed: Whether the original values should be shown (true) or kept as
 *   placeholders (false, the default).
 */
export interface EmbedPIIState {
  mappings: PIIMapping[];
  revealed: boolean;
}

/** Internal writable store — only written by ActiveChat.svelte */
const _embedPIIStore = writable<EmbedPIIState>({
  mappings: [],
  revealed: false,
});

/** Public read-only subscription (derived for external consumers) */
export const embedPIIStore = derived(_embedPIIStore, ($s) => $s);

/**
 * Update the embed PII state.
 * Called by ActiveChat.svelte when the current chat changes or when the user
 * toggles PII visibility.
 *
 * @param mappings - Cumulative PIIMapping array from all user messages
 * @param revealed - Whether PII originals are currently visible
 */
export function setEmbedPIIState(
  mappings: PIIMapping[],
  revealed: boolean,
): void {
  _embedPIIStore.set({ mappings, revealed });
}

/**
 * Get the current embed PII state synchronously (without subscribing).
 * Useful for imperative code like GroupRenderer that runs outside Svelte's
 * reactive system.
 */
export function getEmbedPIIState(): EmbedPIIState {
  return get(_embedPIIStore);
}

/**
 * Reset the embed PII state (called on logout or chat switch when no PII exists).
 */
export function resetEmbedPIIState(): void {
  _embedPIIStore.set({ mappings: [], revealed: false });
}
