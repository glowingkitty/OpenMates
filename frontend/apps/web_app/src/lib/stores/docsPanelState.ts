/**
 * Docs Panel State Store
 *
 * Simple sidebar open/close state for the docs section.
 * Separate from the chat panelState to avoid cross-page conflicts.
 *
 * Architecture: docs/architecture/docs-web-app.md
 */
import { writable } from 'svelte/store';
import { browser } from '$app/environment';

const MOBILE_BREAKPOINT = 730;
const DEFAULT_OPEN_BREAKPOINT = 1440;

function createDocsPanelState() {
	const isSidebarOpen = writable(true);

	return {
		subscribe: isSidebarOpen.subscribe,
		get isSidebarOpen() {
			return isSidebarOpen;
		},
		toggle: () => isSidebarOpen.update((v) => !v),
		open: () => isSidebarOpen.set(true),
		close: () => isSidebarOpen.set(false),
		/** Initialize based on viewport width — call in onMount */
		init: () => {
			if (browser) {
				if (window.innerWidth <= DEFAULT_OPEN_BREAKPOINT) {
					isSidebarOpen.set(false);
				} else {
					isSidebarOpen.set(true);
				}
			}
		},
		/** Check if viewport is mobile-sized */
		isMobile: () => {
			if (!browser) return false;
			return window.innerWidth <= MOBILE_BREAKPOINT;
		}
	};
}

const docsPanelState = createDocsPanelState();
