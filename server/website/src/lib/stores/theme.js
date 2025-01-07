// Import Svelte's store functionality
import { writable } from 'svelte/store';

// Helper to safely access localStorage
const getInitialTheme = () => {
    if (typeof window !== 'undefined') {
        return localStorage.getItem('theme') || 'light';
    }
    return 'light';
};

// Create the theme store
export const theme = writable(getInitialTheme());

// Theme toggle function
export function toggleTheme() {
    theme.update(currentTheme => {
        const newTheme = currentTheme === 'light' ? 'dark' : 'light';
        if (typeof window !== 'undefined') {
            localStorage.setItem('theme', newTheme);
            document.documentElement.setAttribute('data-theme', newTheme);
        }
        return newTheme;
    });
}

// Initialize theme on page load
if (typeof window !== 'undefined') {
    theme.subscribe(value => {
        document.documentElement.setAttribute('data-theme', value);
    });
}