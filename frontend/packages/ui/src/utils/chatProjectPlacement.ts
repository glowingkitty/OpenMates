// Chat-to-project placement facts and plans exchanged with the chatState unit
// (packages/openmates-rust/src/web_chat_state/placement.rs decides).
// Fact and plan types of chat-to-project organisation; the chatState unit
// (packages/openmates-rust/src/web_chat_state/placement.rs) decides.
import type { ChatProjectLocation, SidebarProject } from './chatProjectNavigation';

export interface OrganizableFacts {
  incognito: boolean; sharedByOthers: boolean; demo: boolean; legal: boolean; public: boolean; teamId: string | null;
}
export interface OrganizableInput { chats: OrganizableFacts[]; teamId: string | null }

export type PlacementStep =
  | { kind: 'move'; itemId: string; chatId: string }
  | { kind: 'add'; chatId: string }
  | { kind: 'remove'; sourceId: string; chatId: string };
export interface PlacementInput {
  chatIds: string[]; location: ChatProjectLocation; mode: 'add' | 'move'; index: SidebarProject[];
}
export type PlacementPlan = { error: 'project_unavailable' | 'folder_unavailable' } | { steps: PlacementStep[] };
