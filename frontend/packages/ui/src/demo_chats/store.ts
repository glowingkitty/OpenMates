import { writable, derived } from 'svelte/store';
import type { DemoChat } from './types';

const demoChatStore = writable<DemoChat[]>([]);
export const activeDemoChatStore = writable<DemoChat | null>(null);
const isDemoMode = derived(
	activeDemoChatStore,
	$activeDemo => $activeDemo !== null
);
