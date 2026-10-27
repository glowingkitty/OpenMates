import { authStore } from '../../stores/authStore';
import { webSocketService } from '../../services/websocketService';

/**
 * Deterministic props for the isolated MessageInput preview.
 * The default state mirrors the minimized unauthenticated composer.
 * Focus interactions reveal the expanded action row during component tests.
 * No callbacks in this fixture send messages or invoke backend actions.
 */
export default {
	showActionButtons: false
};

export const variants = {
  recording: { showActionButtons: false },
  recordingInline: { showActionButtons: false, inlineCompact: true },
  ghostSuggestion: {
    showActionButtons: false,
    ghostSuggestion: 'Could you compare the two approaches for me?',
    ghostSuggestionKey: 'fixture-turn',
  },
  inlineCompact: {
    showActionButtons: false,
    inlineCompact: true,
  },
  projectSpecialist: {
    showActionButtons: false,
    activeFocusId: 'code-debugging',
    activeFocusAppId: 'code',
    activeProjectFocusName: 'OpenMates',
    activeSpecialistFocusName: 'Debugging',
    onFocusPillDeepLink: () => {},
    onFocusPillDeactivate: () => {},
  },
  longProjectSpecialist: {
    showActionButtons: false,
    activeFocusId: 'project-focus:11111111-1111-4111-8111-111111111111:22222222-2222-4222-8222-222222222222',
    activeProjectFocusName: 'A very long Project title for a narrow phone screen',
    activeSpecialistFocusName: 'Investigating a complicated application failure',
    onFocusPillDeepLink: () => {},
    onFocusPillDeactivate: () => {},
  },
};

// A synthetic account is scoped to these provider-free microphone previews.
export const ready = (() => {
  if (typeof window === 'undefined') return;
  const variant = new URLSearchParams(window.location.search).get('variant');
  if (variant !== 'recording' && variant !== 'recordingInline') return;
  const connect = webSocketService.connect;
  webSocketService.connect = () => Promise.resolve();
  window.addEventListener('pagehide', () => { webSocketService.connect = connect; }, { once: true });
  authStore.set({ isAuthenticated: true, isInitialized: true });
})();
