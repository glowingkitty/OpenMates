// frontend/packages/ui/src/stores/appSkillsStore.ts
//
// Store for managing app skills metadata state.
// Compatible with Svelte 5 components using $state().
//
// Data Source:
// - Static data: frontend/packages/ui/src/data/appsMetadata.ts
// - Generated at build time from: backend/apps/{app_id}/app.yml
// - Types: frontend/packages/ui/src/types/apps.ts
//
// **Offline-First PWA**: App metadata is included in the build, allowing users
// to browse the app store even when offline. This supports the offline-first
// architecture of the PWA.
//
// **Health Filtering**: Apps with skills are filtered based on health status from /v1/health endpoint.
// Only apps with status="healthy" are shown in the app store. Apps without skills
// (only settings/memories and/or focus modes) bypass health filtering since they
// don't have Docker containers and therefore no health status to check.
//
// **User-Specific Skill Filtering**: Skills that require per-user authorization (e.g. mail/search
// with ProtonMail, which is single-account) are filtered via /v1/apps/metadata (authenticated).
// The backend returns only the skills the current user is allowed to use. The frontend uses this
// to hide restricted skills AND their provider icons from unauthorized users.

import { appsMetadata } from '../data/appsMetadata';
import type { AppMetadata } from '../types/apps';
import { appHealthStore, isAppHealthy } from './appHealthStore';
import { get, writable } from 'svelte/store';

// --- User-Specific Skill Availability Store ---

interface UserAvailableSkillsState {
    /** Map of app_id -> available skill IDs for the current user. null = not yet fetched. */
    skillsByApp: Record<string, string[]> | null;
    initialized: boolean;
    loading: boolean;
}

const initialUserSkillsState: UserAvailableSkillsState = {
    skillsByApp: null,
    initialized: false,
    loading: false,
};

export const userAvailableSkillsStore = writable<UserAvailableSkillsState>(initialUserSkillsState);

/**
 * Fetch /v1/apps/metadata (authenticated) to learn which skills the current user
 * is allowed to see. Stores the result in userAvailableSkillsStore.
 *
 * Called from SettingsAppStore.svelte on mount. Safe to call multiple times — no-op
 * if already initialized.
 */
export async function initializeUserAvailableSkills(force: boolean = false): Promise<void> {
    const current = get(userAvailableSkillsStore);
    if (current.initialized && !force) return;
    if (current.loading) return;

    userAvailableSkillsStore.update(s => ({ ...s, loading: true }));

    try {
        const { getApiEndpoint, apiEndpoints } = await import('../config/api');
        const response = await fetch(getApiEndpoint(apiEndpoints.apps.metadata));

        if (!response.ok) {
            console.warn(`[AppSkillsStore] /v1/apps/metadata returned ${response.status}, skipping user skill filtering`);
            userAvailableSkillsStore.set({ skillsByApp: null, initialized: true, loading: false });
            return;
        }

        const data = await response.json();
        const skillsByApp: Record<string, string[]> = {};
        for (const [appId, appData] of Object.entries(data.apps || {})) {
            skillsByApp[appId] = ((appData as { skills?: { id: string }[] }).skills ?? []).map(s => s.id);
        }

        console.debug('[AppSkillsStore] User-available skills fetched:', skillsByApp);
        userAvailableSkillsStore.set({ skillsByApp, initialized: true, loading: false });
    } catch (e) {
        // Fail open: don't filter if the request fails
        console.warn('[AppSkillsStore] Failed to fetch user-available skills, skipping filtering:', e);
        userAvailableSkillsStore.set({ skillsByApp: null, initialized: true, loading: false });
    }
}

/**
 * Resets user skill availability state (e.g. on logout).
 */
export function resetUserAvailableSkills(): void {
    userAvailableSkillsStore.set(initialUserSkillsState);
}

/**
 * App skills store state interface.
 */
interface AppSkillsState {
    apps: Record<string, AppMetadata>;
}

/**
 * App skills store for managing app metadata state.
 * 
 * This store manages the state of available apps and their skills.
 * Data is loaded from static metadata included in the build (no API calls).
 * Components should use $state() to create reactive references to this store.
 * 
 * **Offline-First**: Data is available immediately and works offline since
 * it's included in the build bundle.
 * 
 * **Usage in components (Svelte 5)**:
 * ```svelte
 * <script>
 *   import { appSkillsStore } from '@repo/ui/stores/appSkillsStore';
 *   
 *   // Create reactive state reference
 *   let storeState = $state(appSkillsStore.getState());
 *   
 *   // Access state reactively - data is already loaded
 *   $effect(() => {
 *     console.log('Apps:', storeState.apps);
 *   });
 * </script>
 * ```
 * 
 * Data Source:
 * - Static data: frontend/packages/ui/src/data/appsMetadata.ts
 * - Generated at build time from: backend/apps/{app_id}/app.yml
 */
class AppSkillsStore {
    private state: AppSkillsState = {
        apps: appsMetadata // Load from static data included in build
    };

    /**
     * Get the current state object.
     * Components should use this with $state() for reactivity.
     *
     * **Health Filtering**: Apps are filtered based on health status.
     * Only apps with status="healthy" in the health endpoint are included.
     *
     * **User Skill Filtering**: Skills not available to the current user (per /v1/apps/metadata)
     * are removed, and app-level providers are recomputed from the remaining skills so that
     * provider icons for restricted skills are not shown to unauthorized users.
     */
    getState(): AppSkillsState {
        // Filter apps based on health status
        // Only include apps that are healthy (or if health status is not available yet, include all)
        const healthState = get(appHealthStore);
        const isHealthy = get(isAppHealthy);

        // CRITICAL: Only filter if health data was SUCCESSFULLY fetched
        // If the request failed (e.g., CORS error) or is still in progress, return all apps
        // This ensures apps don't disappear if the health endpoint is unreachable
        if (!healthState.dataAvailable) {
            return this.state;
        }

        // Filter apps based on health status
        const filteredApps: Record<string, AppMetadata> = {};
        for (const [appId, appMetadata] of Object.entries(this.state.apps)) {
            // Apps without skills don't need a Docker container and therefore have no
            // health status in the /v1/health endpoint. These apps only provide
            // settings/memories and/or focus modes, which don't require a running service.
            // Always include them in the app store.
            const hasSkills = appMetadata.skills && appMetadata.skills.length > 0;
            if (!hasSkills) {
                filteredApps[appId] = appMetadata;
                continue;
            }

            // For apps with skills, only include them if their API is healthy
            if (isHealthy(appId)) {
                filteredApps[appId] = appMetadata;
            } else {
                console.debug(`[AppSkillsStore] Filtering out app '${appId}' - not healthy`);
            }
        }

        // Apply user-specific skill filtering using data from /v1/apps/metadata.
        // Only filters when we have a successful response (skillsByApp !== null).
        // Fails open: if the request failed or hasn't completed, skip this step.
        const userSkillsState = get(userAvailableSkillsStore);
        if (userSkillsState.initialized && userSkillsState.skillsByApp !== null) {
            const userFilteredApps: Record<string, AppMetadata> = {};
            for (const [appId, appMetadata] of Object.entries(filteredApps)) {
                const availableSkillIds = userSkillsState.skillsByApp[appId];
                if (availableSkillIds === undefined) {
                    // App not returned by backend (e.g. container not running) — include as-is
                    userFilteredApps[appId] = appMetadata;
                    continue;
                }

                const availableSet = new Set(availableSkillIds);
                const filteredSkills = appMetadata.skills.filter(s => availableSet.has(s.id));

                // Recompute providers from the filtered skills so that provider icons for
                // restricted skills (e.g. ProtonMail for mail/search) are not shown to
                // users who don't have access. Static app-level providers are ignored here
                // because they may include providers from skills the user can't access.
                const providerSet = new Set<string>();
                for (const skill of filteredSkills) {
                    skill.providers?.forEach(p => providerSet.add(p));
                }

                userFilteredApps[appId] = {
                    ...appMetadata,
                    skills: filteredSkills,
                    providers: Array.from(providerSet),
                };
            }
            return { apps: userFilteredApps };
        }

        return {
            apps: filteredApps
        };
    }

    /**
     * Get apps metadata.
     * 
     * Data Source: Static data included in build (no API calls).
     * Original source: backend/apps/{app_id}/app.yml files
     * 
     * **Health Filtering**: Apps with skills are filtered based on health status from /v1/health endpoint.
     * Only apps with status="healthy" are returned. Apps without skills (only settings/memories
     * and/or focus modes) bypass health filtering since they don't need a Docker container.
     * 
     * **Offline-First**: Data is available immediately and works offline.
     * 
     * @returns Record mapping app_id to AppMetadata (filtered by health status for apps with skills)
     */
    get apps(): Record<string, AppMetadata> {
        return this.getState().apps;
    }

    /**
     * Get a specific app's metadata.
     * 
     * **Offline-First**: Data is available immediately and works offline.
     * 
     * @param appId - The ID of the app
     * @returns App metadata, or undefined if not found
     */
    getApp(appId: string): AppMetadata | undefined {
        return this.state.apps[appId];
    }
}

// Export singleton instance
export const appSkillsStore = new AppSkillsStore();

