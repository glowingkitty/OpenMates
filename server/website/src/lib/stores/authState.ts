import { writable } from 'svelte/store';

interface User {
    email: string;
}

// Create a store for authentication state
export const isAuthenticated = writable(false);
export const currentUser = writable<User | null>(null); 