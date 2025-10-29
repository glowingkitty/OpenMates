import { writable, derived } from 'svelte/store';
import type { DemoChat } from './types';

export const demoChatStore = writable<DemoChat[]>([]);
export const activeDemoChatStore = writable<DemoChat | null>(null);
export const isDemoMode = derived(
	activeDemoChatStore,
	$activeDemo => $activeDemo !== null
);
