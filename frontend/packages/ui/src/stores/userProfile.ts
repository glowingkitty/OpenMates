import { writable } from 'svelte/store';
import { userDB } from '../services/userDB';

export interface UserProfile {
  username: string;
  profileImageUrl: string | null;
  credits: number;
  isAdmin: boolean;
  last_opened: string;
  tfaAppName: string | null;
  tfa_enabled: boolean; // Added field for 2FA status
  // Use boolean flags received from backend
  consent_privacy_and_apps_default_settings?: boolean; 
  consent_mates_default_settings?: boolean;
}

const defaultProfile: UserProfile = {
  username: '',
  profileImageUrl: null,
  credits: 0,
  isAdmin: false,
  last_opened: '',
  tfaAppName: null,
  tfa_enabled: false, // Added default value
  // Add default values for boolean flags
  consent_privacy_and_apps_default_settings: false,
  consent_mates_default_settings: false
};

export const userProfile = writable<UserProfile>(defaultProfile);

// Load user profile data from IndexedDB on startup
export async function loadUserProfileFromDB(): Promise<void> {
  try {
    // userDB.getUserProfile() now returns all necessary fields including consents, credits, isAdmin, etc.
    const profileFromDB = await userDB.getUserProfile(); 
    
    if (profileFromDB) {
      // Update the store with the comprehensive profile data from DB
      userProfile.update(currentProfile => ({
        ...currentProfile, // Keep any existing non-persistent state if needed
        ...profileFromDB // Overwrite with fresh data from DB (includes consents)
      }));
      console.debug("[UserProfileStore] Profile loaded from DB:", profileFromDB);
    } else {
      console.debug("[UserProfileStore] No profile found in DB, using default.");
      // Optionally reset to default if no profile found, or keep current state
      // userProfile.set(defaultProfile); 
    }
  } catch (error) {
    console.error('Failed to load user profile from database:', error);
    // Consider resetting to default or handling the error appropriately
    // userProfile.set(defaultProfile);
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
