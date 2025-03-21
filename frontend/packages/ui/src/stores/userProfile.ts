import { writable } from 'svelte/store';
import { userDB } from '../services/userDB';

export interface UserProfile {
  username: string;
  profileImageUrl: string | null;
  credits?: number;
}

const defaultProfile: UserProfile = {
  username: '',
  profileImageUrl: null,
  credits: 0
};

export const userProfile = writable<UserProfile>(defaultProfile);

// Load user profile data from IndexedDB on startup
export async function loadUserProfileFromDB(): Promise<void> {
  try {
    const profile = await userDB.getUserProfile();
    if (profile) {
      // Get credits as well
      const credits = await userDB.getUserCredits();
      
      userProfile.update(currentProfile => ({
        ...currentProfile,
        ...profile,
        credits
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
}

// Helper function to update just the profile image
export function updateProfileImage(imageUrl: string | null): void {
  userProfile.update(profile => ({
    ...profile,
    profileImageUrl: imageUrl
  }));
}

// Helper function to update just the credits
export function updateCredits(credits: number): void {
  userProfile.update(profile => ({
    ...profile,
    credits
  }));
}

// Helper to update the entire profile
export function updateProfile(profile: Partial<UserProfile>): void {
  userProfile.update(currentProfile => ({
    ...currentProfile,
    ...profile
  }));
}
