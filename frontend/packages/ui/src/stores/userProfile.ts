import { writable } from 'svelte/store';
import { userDB } from '../services/userDB';

export interface UserProfile {
  username: string;
  profileImageUrl: string | null;
  credits: number;
  isAdmin: boolean;
  last_opened: string;
  tfaAppName: string | null; // Add tfaAppName
}

const defaultProfile: UserProfile = {
  username: '',
  profileImageUrl: null,
  credits: 0,
  isAdmin: false,
  last_opened: '',
  tfaAppName: null // Add default value
};

export const userProfile = writable<UserProfile>(defaultProfile);

// Load user profile data from IndexedDB on startup
export async function loadUserProfileFromDB(): Promise<void> {
  try {
    const profile = await userDB.getUserProfile();
    
    // Get additional user data
    const credits = await userDB.getUserCredits();
    
    // Get isAdmin status - using a try/catch in case this field doesn't exist yet
    let isAdmin = false;
    try {
      const transaction = userDB.db?.transaction([userDB.STORE_NAME], 'readonly');
      if (transaction) {
        const store = transaction.objectStore(userDB.STORE_NAME);
        const request = store.get('isAdmin');
        isAdmin = await new Promise((resolve) => {
          request.onsuccess = () => resolve(!!request.result);
          request.onerror = () => resolve(false);
        });
      }
    } catch (error) {
      console.warn('Could not load isAdmin status:', error);
    }

    // Get tfaAppName status - using a try/catch
    let tfaAppName: string | null = null;
    try {
      const transaction = userDB.db?.transaction([userDB.STORE_NAME], 'readonly');
      if (transaction) {
        const store = transaction.objectStore(userDB.STORE_NAME);
        const request = store.get('tfaAppName');
        tfaAppName = await new Promise((resolve) => {
          request.onsuccess = () => resolve(request.result || null); // Return null if not found
          request.onerror = () => resolve(null); // Return null on error
        });
      }
    } catch (error) {
      console.warn('Could not load tfaAppName status:', error);
    }
    
    if (profile) {
      userProfile.update(currentProfile => ({
        ...currentProfile,
        ...profile,
        credits,
        isAdmin,
        tfaAppName // Add tfaAppName to the update
      }));
    }
  } catch (error) {
    console.error('Failed to load user profile from database:', error);
  }
}

// Helper function to update just the username
export function updateUsername(username: string): void {
  userProfile.update(profile => ({
    ...profile,
    username
  }));
  
  // Also persist to database
  userDB.updateUserData({ username });
}

// Helper function to update just the profile image
export function updateProfileImage(imageUrl: string | null): void {
  userProfile.update(profile => ({
    ...profile,
    profileImageUrl: imageUrl
  }));
  
  // Also persist to database
  userDB.updateUserData({ profileImageUrl: imageUrl });
}

// Helper function to update just the credits
export function updateCredits(credits: number): void {
  userProfile.update(profile => ({
    ...profile,
    credits
  }));
  
  // Also persist to database
  userDB.updateUserData({ credits });
}

// This becomes the single point of update for user data
export function updateProfile(profile: Partial<UserProfile>): void {
  // Update store
  userProfile.update(currentProfile => ({
    ...currentProfile,
    ...profile
  }));
  
  // Persist to IndexedDB
  userDB.updateUserData(profile);
}

// Add getter for components that need user data
export function getUserProfile(): UserProfile {
  let profile: UserProfile;
  userProfile.subscribe(value => profile = value)();
  return profile;
}
