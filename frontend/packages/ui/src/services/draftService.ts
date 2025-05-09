// Re-export constants
export * from './drafts/draftConstants';

// Re-export types
export * from './drafts/draftTypes';

// Re-export state and initial state
export { draftEditorUIState, initialDraftEditorState } from './drafts/draftState';

// Re-export core service functions
export {
	initializeDraftService,
	cleanupDraftService,
	setCurrentChatContext,
	clearEditorAndResetDraftState,
	getEditorInstance
} from './drafts/draftCore';

// Re-export save/trigger/flush functions
export { triggerSaveDraft, flushSaveDraft, saveDraftDebounced } from './drafts/draftSave';

// Note: WebSocket handlers (register/unregister) are typically internal
// and called by initialize/cleanup, so they might not need to be exported directly
// unless used elsewhere. For now, keeping them internal to draftCore.