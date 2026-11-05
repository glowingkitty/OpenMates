/** Account-free real privacy preferences, persisted only in preview browser storage. */
import { authStore } from "../../../stores/authState";
import { personalDataStore } from "../../../stores/personalDataStore";
authStore.set({ isInitialized: true, isAuthenticated: false });
export const ready = personalDataStore.ensureEnhancementReady();
export default {};
