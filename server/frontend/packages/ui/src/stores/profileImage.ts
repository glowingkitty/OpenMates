import { writable } from 'svelte/store';

export const processedImageUrl = writable<string | null>(null);
