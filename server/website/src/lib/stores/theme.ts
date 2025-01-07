// Import Svelte's store functionality
import { writable } from 'svelte/store';

// Create the theme store
export const theme = writable('light');

// Theme toggle function
export function toggleTheme() {
    theme.update(currentTheme => {
        const newTheme = currentTheme === 'light' ? 'dark' : 'light';
        // Set user preference to indicate manual override
        localStorage.setItem('theme_preference', 'manual');
        localStorage.setItem('theme', newTheme);
        document.documentElement.setAttribute('data-theme', newTheme);
        return newTheme;
    });
}

// Function to update theme based on system preference
export function updateThemeFromSystem(e: MediaQueryListEvent | MediaQueryList | null) {
    const newTheme = e?.matches ? 'dark' : 'light';
    theme.set(newTheme);
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
}

// Function to initialize theme
export function initializeTheme() {
    const userPreference = localStorage.getItem('theme_preference');
    
    if (userPreference === 'manual') {
        // Use saved theme if user manually set it
        const savedTheme = localStorage.getItem('theme') || 'light';
        theme.set(savedTheme);
        document.documentElement.setAttribute('data-theme', savedTheme);
    } else {
        // Use system preference and set up listener
        const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
        updateThemeFromSystem(mediaQuery);
        
        // Remove any existing listener to avoid duplicates
        mediaQuery.removeEventListener('change', updateThemeFromSystem);
        // Add listener for system theme changes
        mediaQuery.addEventListener('change', updateThemeFromSystem);
    }
}