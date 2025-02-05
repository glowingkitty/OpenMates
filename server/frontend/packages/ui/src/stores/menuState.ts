import { writable } from 'svelte/store';

// Create a store to track if the menu is open
export const isMenuOpen = writable(true); 