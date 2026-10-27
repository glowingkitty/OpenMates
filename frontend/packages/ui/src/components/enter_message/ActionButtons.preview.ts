/** Isolated Send states while a saved chat's model selection is restored. */
export default {
    showSendButton: true,
    isAuthenticated: true,
    modelSelectionReady: true,
};

export const variants = {
    emptyDraft: { showSendButton: false, isAuthenticated: true },
    restoringModel: { showSendButton: true, isAuthenticated: true, modelSelectionReady: false },
    queuedEdit: { showSendButton: true, isAuthenticated: true, modelSelectionReady: false, queuedEditActive: true },
};
