import { writable } from 'svelte/store';
import type { DraftEditorState } from './draftTypes'; // Updated to DraftEditorState

export const initialDraftEditorState: DraftEditorState = {
	currentChatId: null, // This will store the chat_id for the draft being edited
	currentUserDraftVersion: 0, // Version of the current user's draft for the currentChatId
	hasUnsavedChanges: false,
	newlyCreatedChatIdToSelect: null,
};

export const draftEditorUIState = writable<DraftEditorState>(initialDraftEditorState); // Renamed for clarity