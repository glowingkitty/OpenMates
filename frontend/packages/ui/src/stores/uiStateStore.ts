import { readable } from 'svelte/store';
// Use standard browser check for library compatibility
const browser = typeof window !== 'undefined';

// Import MOBILE_BREAKPOINT from the correct location
import { MOBILE_BREAKPOINT } from '../styles/constants';

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

    window.addEventListener('resize', handleResize);
    console.debug('[uiStateStore] Initialized isMobileView:', checkMobile());

    // Cleanup listener on unsubscribe
    return () => {
        window.removeEventListener('resize', handleResize);
        console.debug('[uiStateStore] Cleaned up resize listener.');
    };
});

// --- Potentially add other global UI states here in the future ---
// e.g., theme, density, etc.