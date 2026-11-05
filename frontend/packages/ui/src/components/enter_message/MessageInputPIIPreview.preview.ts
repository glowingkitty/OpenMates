import { authStore } from '../../stores/authState';
import { personalDataStore } from '../../stores/personalDataStore';
import { webPIIDetectorState } from './services/webPIIDetectionService';

// Match an initialized signed-out app while preserving real browser preferences.
const coldStart = typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('variant') === 'coldStart';
authStore.set({ isInitialized: !coldStart, isAuthenticated: false });
export const ready = personalDataStore.ensureEnhancementReady();
if (typeof window !== 'undefined') {
  const fixture = window as typeof window & { __piiDetectorDiagnostics?: unknown[] };
  fixture.__piiDetectorDiagnostics = [];
  webPIIDetectorState.subscribe(state => {
    fixture.__piiDetectorDiagnostics!.push({
      status: state.status, failureCode: state.failureCode, fallbackReason: state.fallbackReason,
    });
    if (fixture.__piiDetectorDiagnostics!.length > 100) fixture.__piiDetectorDiagnostics!.shift();
  });
}
export default {};
export const variants = { coldStart: { coldStart: true } };
