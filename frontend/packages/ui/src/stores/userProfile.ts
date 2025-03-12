import { writable } from 'svelte/store';

export interface UserProfile {
  username: string;
  profileImageUrl: string | null;
}

const defaultProfile: UserProfile = {
  username: '',
  profileImageUrl: null
};

export const userProfile = writable<UserProfile>(defaultProfile);

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
