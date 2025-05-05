import { writable } from 'svelte/store';
import type { DraftState } from './draftTypes';

export const initialDraftState: DraftState = {
    currentChatId: null,
    currentTempDraftId: null,
    currentVersion: 0,
    hasUnsavedChanges: false,
};

export const draftState = writable<DraftState>(initialDraftState);