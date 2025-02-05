import { writable } from 'svelte/store';

// Start as false to show login form by default
export const isCheckingAuth = writable(false); 