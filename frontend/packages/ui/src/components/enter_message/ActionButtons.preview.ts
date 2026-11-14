/** Isolated Send states: authenticated model restore, and the only signed-out states (Send, loading, Sign up / Log in). */
export default {
    showSendButton: true,
    isAuthenticated: true,
    modelSelectionReady: true,
};

export const variants = {
    emptyDraft: { showSendButton: false, isAuthenticated: true },
    restoringModel: { showSendButton: true, isAuthenticated: true, modelSelectionReady: false },
    queuedEdit: { showSendButton: true, isAuthenticated: true, modelSelectionReady: false, queuedEditActive: true },
    guestSend: { showSendButton: true, isAuthenticated: false, allowAnonymousTextSend: true },
    guestSendInFlight: { showSendButton: true, isAuthenticated: false, allowAnonymousTextSend: true, sendInProgress: true },
    guestLoading: { showSendButton: true, isAuthenticated: false, guestStatusLoading: true },
    guestSignup: { showSendButton: true, isAuthenticated: false, unauthenticatedCtaLabel: 'Sign up' },
    guestLogin: { showSendButton: true, isAuthenticated: false, unauthenticatedCtaLabel: 'Log in' },
};
