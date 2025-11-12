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

import { appsMetadata } from '../data/appsMetadata';
import type { AppMetadata } from '../types/apps';

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
     */
    getState(): AppSkillsState {
        return this.state;
    }

    /**
     * Get apps metadata.
     * 
     * Data Source: Static data included in build (no API calls).
     * Original source: backend/apps/{app_id}/app.yml files
     * 
     * **Offline-First**: Data is available immediately and works offline.
     * 
     * @returns Record mapping app_id to AppMetadata
     */
    get apps(): Record<string, AppMetadata> {
        return this.state.apps;
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

