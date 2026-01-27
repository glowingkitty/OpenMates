import { writable } from 'svelte/store';

export const messageHighlightStore = writable<string | null>(null);
