import { readable, writable } from "svelte/store"; // Import writable
// Use standard browser check for library compatibility
const browser = typeof window !== "undefined";

// Import MOBILE_BREAKPOINT from the correct location
import {
  MOBILE_BREAKPOINT,
  CHATS_DEFAULT_OPEN_BREAKPOINT,
} from "../styles/constants";

/**
 * A readable store that tracks whether the current viewport width
 * is considered 'mobile' (less than MOBILE_BREAKPOINT).
 * Updates automatically on window resize.
 */
export const isMobileView = readable<boolean>(false, (set) => {
  if (!browser) {
    // Default to false on the server, or handle as needed
    set(false);
    return;
  }

  // Initial check
  const checkMobile = () => window.innerWidth < MOBILE_BREAKPOINT;
  set(checkMobile());

  // Listener for resize
  const handleResize = () => {
    set(checkMobile());
  };

  window.addEventListener("resize", handleResize);

  // Cleanup listener on unsubscribe
  return () => {
    window.removeEventListener("resize", handleResize);
  };
});

/**
 * A readable store that tracks whether the viewport should auto-open
 * the chats panel by default.
 */
export const isChatsDefaultOpenViewport = readable<boolean>(false, (set) => {
  if (!browser) {
    set(false);
    return;
  }

  const checkViewport = () => window.innerWidth > CHATS_DEFAULT_OPEN_BREAKPOINT;
  set(checkViewport());

  const handleResize = () => {
    set(checkViewport());
  };

  window.addEventListener("resize", handleResize);

  return () => {
    window.removeEventListener("resize", handleResize);
  };
});

// New writable store for session expired warning
export const sessionExpiredWarning = writable<boolean>(false);

// Store to track if login interface is currently open/visible
// Used to hide header buttons (Sign In button and menu button) when login is shown
export const loginInterfaceOpen = writable<boolean>(false);

// --- Potentially add other global UI states here in the future ---
// e.g., theme, density, etc.
