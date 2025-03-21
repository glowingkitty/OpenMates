import { chatDB } from './services/db';
import { userDB } from './services/userDB';
import { loadUserProfileFromDB } from './stores/userProfile';
import { authStore } from './stores/authStore';

/**
 * Initialize all application services
 * @param {Object} options - Configuration options
 * @param {boolean} options.skipAuthInitialization - If true, skip auth initialization (default: false)
 */
export async function initializeApp(options = { skipAuthInitialization: false }) {
  console.debug("Initializing application...");
  
  try {
    // Initialize databases
    await chatDB.init();
    await userDB.init();
    
    // First load user profile from IndexedDB for immediate display
    await loadUserProfileFromDB();
    
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
