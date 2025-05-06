import { writable } from 'svelte/store';
import type { DraftState } from './draftTypes';

export const initialDraftState: DraftState = {
	currentChatId: null, // This will store the client-generated UUID
	user_id: null, // This will store the 10-char user hash suffix from the server
	currentTempDraftId: null, // This is deprecated
	currentVersion: 0,
	hasUnsavedChanges: false,
	newlyCreatedChatIdToSelect: null, // Added for explicit new chat selection
};

export const draftState = writable<DraftState>(initialDraftState);