import { chatDB } from './services/db';
import { userDB } from './services/userDB';
import { loadUserProfileFromDB } from './stores/userProfile';
import { authStore } from './stores/authStore';

/**
 * Initialize all application services
 */
export async function initializeApp() {
  console.debug("Initializing application...");
  
  try {
    // Initialize databases
    await chatDB.init();
    await userDB.init();
    
    // First load user profile from IndexedDB for immediate display
    await loadUserProfileFromDB();
    
    // Check authentication - this already handles updating profile data from server
    const isAuthenticated = await authStore.initialize();
    
    console.debug("Application initialization complete");
  } catch (error) {
    console.error("Error initializing application:", error);
  }
}
