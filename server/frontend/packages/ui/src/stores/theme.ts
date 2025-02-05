// Import Svelte's store functionality
import { writable } from 'svelte/store';
import { browser } from '$app/environment';

// Create the theme store
export const theme = writable('light');

// Helper to check system dark mode preference
function getSystemThemePreference() {
    if (browser) {
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    return 'light';
}

// Initialize theme based on stored preference or system setting
export function initializeTheme() {
    if (browser) {
        // Check for stored manual preference
        const storedPreference = localStorage.getItem('theme_preference');
        const storedTheme = localStorage.getItem('theme');

        if (storedPreference === 'manual' && storedTheme) {
            theme.set(storedTheme);
        } else {
            // Use system preference
            const systemTheme = getSystemThemePreference();
            theme.set(systemTheme);

            // Listen for system theme changes
            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
                if (localStorage.getItem('theme_preference') !== 'manual') {
                    theme.set(e.matches ? 'dark' : 'light');
                }
            });
        }
    }
}

// Toggle theme function
export function toggleTheme() {
    if (browser) {
        theme.update(currentTheme => {
            const newTheme = currentTheme === 'light' ? 'dark' : 'light';
            localStorage.setItem('theme', newTheme);
            localStorage.setItem('theme_preference', 'manual');
            return newTheme;
        });
    }
}