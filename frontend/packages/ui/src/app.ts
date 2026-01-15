import { chatDB } from './services/db';
import { userDB } from './services/userDB';
import { loadUserProfileFromDB } from './stores/userProfile';
import { authStore } from './stores/authStore';
import { logCollector } from './services/logCollector'; 
import { initDebugUtils } from './services/debugUtils';
import { initPermissionDialogListener } from './stores/appSettingsMemoriesPermissionStore';

/**
 * Initialize all application services
 * @param {Object} options - Configuration options
 * @param {boolean} options.skipAuthInitialization - If true, skip auth initialization (default: false)
 */
export async function initializeApp(options = { skipAuthInitialization: false }) {
  console.debug("Initializing application...");

  try {
    // Initialize console log collector for issue reporting (non-blocking)
    console.debug("Console log collector initialized for issue debugging");
    
    // Initialize debug utilities for browser console access
    // These allow inspecting IndexedDB data via window.debugChat(), etc.
    initDebugUtils();

    // Initialize databases
    await chatDB.init();
    await userDB.init();

    // First load user profile from IndexedDB for immediate display
    await loadUserProfileFromDB();

    // Initialize app settings/memories permission dialog listener
    // This listens for "showAppSettingsMemoriesPermissionDialog" events from the WebSocket handler
    initPermissionDialogListener();

    // Check authentication only if not skipped
    if (!options.skipAuthInitialization) {
      console.debug("Performing auth initialization in initializeApp");
      await authStore.initialize();
    } else {
      console.debug("Skipping auth initialization in initializeApp");
    }

    console.debug("Application initialization complete");
  } catch (error) {
    console.error("Error initializing application:", error);
  }
}
