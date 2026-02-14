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

import { appsMetadata } from '../data/appsMetadata';
import type { AppMetadata } from '../types/apps';
import { appHealthStore, isAppHealthy } from './appHealthStore';
import { get } from 'svelte/store';

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

