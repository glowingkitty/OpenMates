import { writable, get } from 'svelte/store';
import { userDB } from '../services/userDB';
import { authStore } from './authStore';
import { userProfile } from './userProfile';

export const signupStore = writable({
  email: '',
  username: '',
  password: '',
  inviteCode: '',
  language: '',
  darkmode: false,
  stayLoggedIn: false,
  encryptedMasterKey: '',
  salt: ''
});

export function clearSignupData() {
  signupStore.set({
    email: '',
    username: '',
    password: '',
    inviteCode: '',
    language: '',
    darkmode: false,
    stayLoggedIn: false,
    encryptedMasterKey: '',
    salt: ''
  });
}

/**
 * Clears incomplete signup data from IndexedDB and userProfile store if user is not authenticated.
 * This is a security measure to prevent username from persisting if signup is interrupted.
 * Only clears username if the user is not authenticated (signup was not completed).
 */
export async function clearIncompleteSignupData(): Promise<void> {
  // Only clear username from IndexedDB if user is not authenticated
  // This ensures we don't clear data for users who completed signup
  const isAuthenticated = get(authStore).isAuthenticated;
  
  if (!isAuthenticated) {
    try {
      // Clear username from IndexedDB using updateUserData with empty string
      // This is safer than clearUserData() which would clear all user data
      await userDB.updateUserData({ username: '' });
      
      // Also clear username from userProfile store to ensure UI updates immediately
      // This prevents the username from showing in Settings component after clearing
      userProfile.update(profile => ({
        ...profile,
        username: ''
      }));
      
      console.debug('[SignupStore] Cleared incomplete signup username from IndexedDB and userProfile store');
    } catch (error) {
      console.error('[SignupStore] Error clearing incomplete signup data from IndexedDB:', error);
      // Don't throw - this is a cleanup operation and shouldn't break the flow
    }
  }
}
