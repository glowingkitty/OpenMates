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
 * Two-layer PII mapping architecture:
 * 1. Message-level mappings (from ActiveChat.svelte):
 *    - Cumulative PIIMapping[] from all user messages in the current chat
 *    - These cover PII found in message text (typed/pasted by the user)
 *    - Set via setEmbedPIIState()
 *
 * 2. Embed-level mappings (from individual embed preview/fullscreen components):
 *    - PIIMappings stored separately in EmbedStore under `embed_pii:{embed_id}`
 *    - Cover PII found in code files / pasted code that was redacted at embed creation
 *    - Registered via addEmbedPIIMappings() when an embed is rendered
 *    - Cleared on chat switch via resetEmbedPIIState()
 *
 * Both layers are merged when resolving final mappings for display. This allows
 * embed components to show/hide PII originals for both sources with a single toggle.
 *
 * Sharing safety:
 * - Message-level mappings are encrypted with the chat key (owner-only decryption)
 * - Embed-level mappings are encrypted with the master key (separate from embed key)
 * - Share links provide the embed key but NOT the master key, so non-owners
 *   can never access either mapping layer — they always see placeholders
 *
 * Usage:
 * - ActiveChat.svelte: writes message-level mappings via setEmbedPIIState()
 * - Embed preview components: call addEmbedPIIMappings() to register embed-level mappings
 * - All consumers: subscribe to embedPIIStore to get the merged state
 */

import { writable, derived, get } from "svelte/store";
import type { PIIMapping } from "../types/chat";

/**
 * The current PII masking state for the active chat.
 * - mappings: Merged PIIMapping array from message-level and embed-level sources.
 *   These map placeholder strings (e.g. "[EMAIL_1]") to original values.
 * - revealed: Whether the original values should be shown (true) or kept as
 *   placeholders (false, the default).
 */
export interface EmbedPIIState {
  mappings: PIIMapping[];
  revealed: boolean;
}

/**
 * Internal state split into message-level and embed-level mappings.
 * Both are merged to produce the final public embedPIIStore value.
 */
interface InternalPIIState {
  /** Message-level PII mappings (from ActiveChat.svelte, cumulative across all user messages) */
  messageMappings: PIIMapping[];
  /**
   * Embed-level PII mappings (loaded from EmbedStore's embed_pii:{embed_id} entries).
   * Keyed by embed_id for deduplication — prevents the same embed's mappings from
   * being registered multiple times if the component re-mounts.
   */
  embedMappingsByEmbedId: Record<string, PIIMapping[]>;
  /** Whether PII originals are currently visible */
  revealed: boolean;
}

/** Internal writable store — only written by this module's exported functions */
const _internalStore = writable<InternalPIIState>({
  messageMappings: [],
  embedMappingsByEmbedId: {},
  revealed: false,
});

/**
 * Public read-only store — derived from internal state.
 * Merges message-level and embed-level mappings into a single array.
 * Components should subscribe to this store for the final merged PII state.
 */
export const embedPIIStore = derived(_internalStore, ($s): EmbedPIIState => {
  // Collect all embed-level mappings from all registered embeds
  const allEmbedMappings: PIIMapping[] = [];
  for (const maps of Object.values($s.embedMappingsByEmbedId)) {
    allEmbedMappings.push(...maps);
  }

  // Merge message-level and embed-level mappings.
  // Message-level mappings come first (they were registered earlier, keep ordering stable).
  const merged = [...$s.messageMappings, ...allEmbedMappings];

  return {
    mappings: merged,
    revealed: $s.revealed,
  };
});

/**
 * Update the message-level PII state and the reveal toggle.
 * Called by ActiveChat.svelte when the current chat changes or when the user
 * toggles PII visibility.
 *
 * This also resets embed-level mappings since we're switching to a new chat context
 * (embed-level mappings are lazy-loaded per-component, so they'll be re-registered
 * as embeds become visible in the new chat).
 *
 * @param mappings - Cumulative PIIMapping array from all user messages in the current chat
 * @param revealed - Whether PII originals are currently visible
 */
export function setEmbedPIIState(
  mappings: PIIMapping[],
  revealed: boolean,
): void {
  _internalStore.update((s) => ({
    ...s,
    messageMappings: mappings,
    // Clear embed-level mappings on chat switch — they'll be re-registered
    // as embed components mount and load their embed_pii data
    embedMappingsByEmbedId: {},
    revealed,
  }));
}

/**
 * Update only the reveal state (PII visibility toggle) without affecting mappings.
 * Called when the user toggles PII visibility in the active chat.
 *
 * @param revealed - Whether PII originals should be shown
 */
export function setEmbedPIIRevealed(revealed: boolean): void {
  _internalStore.update((s) => ({ ...s, revealed }));
}

/**
 * Register embed-level PII mappings for a specific embed.
 * Called by embed preview/fullscreen components when they load their embed data
 * and find that the embed has associated PII mappings (stored under embed_pii:{embed_id}).
 *
 * Calling this multiple times for the same embed_id is safe — the previous mappings
 * for that embed are replaced (idempotent via the keyed record).
 *
 * @param embedId - The embed's unique ID
 * @param mappings - PIIMapping array loaded from EmbedStore's embed_pii:{embed_id} entry
 */
export function addEmbedPIIMappings(
  embedId: string,
  mappings: PIIMapping[],
): void {
  if (!mappings || mappings.length === 0) return;

  _internalStore.update((s) => ({
    ...s,
    embedMappingsByEmbedId: {
      ...s.embedMappingsByEmbedId,
      [embedId]: mappings,
    },
  }));
}

/**
 * Remove embed-level PII mappings for a specific embed.
 * Called when an embed component unmounts, to keep the store lean.
 *
 * @param embedId - The embed's unique ID
 */
export function removeEmbedPIIMappings(embedId: string): void {
  _internalStore.update((s) => {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { [embedId]: _removed, ...rest } = s.embedMappingsByEmbedId;
    return { ...s, embedMappingsByEmbedId: rest };
  });
}

/**
 * Get the current embed PII state synchronously (without subscribing).
 * Useful for imperative code like GroupRenderer that runs outside Svelte's
 * reactive system.
 */
export function getEmbedPIIState(): EmbedPIIState {
  return get(embedPIIStore);
}

/**
 * Reset the embed PII state (called on logout or chat switch when no PII exists).
 * Clears both message-level and embed-level mappings.
 */
export function resetEmbedPIIState(): void {
  _internalStore.set({
    messageMappings: [],
    embedMappingsByEmbedId: {},
    revealed: false,
  });
}
