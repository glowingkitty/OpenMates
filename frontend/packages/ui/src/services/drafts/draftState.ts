import { writable } from 'svelte/store';
import type { DraftState } from './draftTypes';

export const initialDraftState: DraftState = {
	currentChatId: null, // This will store the client-generated UUID
	draft_v: 0,
	hasUnsavedChanges: false,
	newlyCreatedChatIdToSelect: null, // Added for explicit new chat selection
};

export const draftState = writable<DraftState>(initialDraftState);