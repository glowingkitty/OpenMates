import { authStore } from '../../stores/authState';
import { personalDataStore } from '../../stores/personalDataStore';
import { webPIIDetectorState } from './services/webPIIDetectionService';

// Match an initialized signed-out app while preserving real browser preferences.
authStore.set({ isInitialized: true, isAuthenticated: false });
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
