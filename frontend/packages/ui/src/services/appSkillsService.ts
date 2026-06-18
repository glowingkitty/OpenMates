// frontend/packages/ui/src/services/appSkillsService.ts
//
// Service for accessing app metadata and skills from static data.
// Provides helper functions to work with app metadata included in the build.
//
// **Data Source**: 
// - Static data: `frontend/packages/ui/src/data/appsMetadata.ts`
// - Generated at build time from: `backend/apps/*/app.yml`
//
// **Offline-First PWA**: App metadata is included in the build, allowing users
// to browse Apps even when offline. This supports the offline-first
// architecture of the PWA.

import { appsMetadata } from '../data/appsMetadata';
import type { AppMetadata } from '../types/apps';

/**
 * Gets all available apps and their metadata from static data.
 * 
 * Data Source: 
 * - Static data: frontend/packages/ui/src/data/appsMetadata.ts
 * - Generated at build time from: backend/apps/app.yml files
 * 
 * **Offline-First**: This is synchronous and works offline since data is
 * included in the build bundle.
 * 
 * @returns Record mapping app_id to AppMetadata (synchronous, no API call)
 */
export function getAvailableApps(): Record<string, AppMetadata> {
    return appsMetadata;
}
