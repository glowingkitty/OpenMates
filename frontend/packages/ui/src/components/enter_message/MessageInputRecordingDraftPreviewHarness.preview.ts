import { authStore } from '../../stores/authStore';
import { webSocketService } from '../../services/websocketService';

/** A real draft image and viewer, with provider-free microphone capture. */
export default {};
export const variants = { imageOnly: { includeNotes: false } };

export const ready = (() => {
  if (typeof window === 'undefined' ||
      !window.location.pathname.endsWith('/MessageInputRecordingDraftPreviewHarness')) return;
  const connect = webSocketService.connect;
  webSocketService.connect = () => Promise.resolve();
  window.addEventListener('pagehide', () => { webSocketService.connect = connect; }, { once: true });
  authStore.set({ isAuthenticated: true, isInitialized: true });
})();
