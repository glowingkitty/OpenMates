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
import type {
  GenericMentionType,
  ProjectMentionAccessMode,
} from "../components/enter_message/extensions/GenericMentionNode";

export interface PendingGenericMention {
  syntax: string;
  type: GenericMentionType;
  displayName: string;
  projectId?: string;
  projectSourceId?: string;
  projectPath?: string;
  projectAccessMode?: ProjectMentionAccessMode;
}

export type PendingMention = string | PendingGenericMention;

/**
 * Pending mention text (e.g. "@mate:software_development") or null when idle.
 * MessageInput consumes and clears this on the next render after it is set.
 */
export const pendingMentionStore = writable<PendingMention | null>(null);
