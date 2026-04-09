/**
 * Demo Mode Store
 *
 * Hides developer/debug-only UI affordances so the app can be cleanly
 * recorded or screenshotted for demos and marketing material.
 *
 * When enabled:
 *  - Hides the "Report Issue" and "Start Debugging" buttons in chat + embed top bars
 *  - Hides the admin-only "Server" section and "Logs" entry in the settings menu
 *
 * When disabled everything returns to normal. The "New Chat" and
 * "Share" buttons are NEVER affected by demo mode.
 *
 * Toggled via the console: `window.demo_mode.on()` / `window.demo_mode.off()`.
 * State persists in localStorage so it survives reloads during a demo session.
 */

import { writable } from 'svelte/store';
import { browser } from '$app/environment';

function createDemoModeStore() {
    const STORAGE_KEY = 'demo_mode_enabled';
    const { subscribe, set: setStore } = writable<boolean>(false);

    if (browser) {
        const stored = localStorage.getItem(STORAGE_KEY);
        if (stored === 'true') {
            setStore(true);
        }
    }

    const setMethod = (value: boolean) => {
        if (browser) {
            localStorage.setItem(STORAGE_KEY, String(value));
        }
        setStore(value);
    };

    return {
        subscribe,
        set: setMethod,
        /** Read the current value synchronously (one-shot). */
        get: (): boolean => {
            let v = false;
            subscribe((x) => (v = x))();
            return v;
        },
    };
}

export const demoMode = createDemoModeStore();
