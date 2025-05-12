// frontend/packages/ui/src/stores/authDerivedStores.ts
/**
 * @fileoverview Defines derived Svelte stores based on the core authentication state
 * and user profile information. These stores provide convenient reactive access
 * to computed values like the user's profile image URL.
 */

import { derived, get } from 'svelte/store';
import { authStore } from './authState'; // Import the core auth state store
import { userProfile } from './userProfile'; // Import the user profile store

// Define the default placeholder image path
const defaultPlaceholderImage = '@openmates/ui/static/images/placeholders/userprofileimage.jpeg';

/**
 * Derived store for the user's profile image URL.
 * Reactively returns the user's profile_image_url if authenticated and available,
 * otherwise falls back to a default placeholder image.
 */
export const profileImage = derived(
  [authStore, userProfile], // Depends on both auth state and user profile
  ([$authStore, $userProfile]) => {
    if ($authStore.isAuthenticated && $userProfile.profile_image_url) {
      return $userProfile.profile_image_url;
    }
    // Return default placeholder if not authenticated or profile image URL is missing
    return defaultPlaceholderImage;
  }
);

// Example of another potential derived store (if needed later):
// export const isAdmin = derived(
//   userProfile,
//   $userProfile => $userProfile.is_admin || false
// );