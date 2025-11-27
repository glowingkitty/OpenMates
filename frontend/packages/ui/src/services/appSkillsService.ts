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
// to browse the app store even when offline. This supports the offline-first
// architecture of the PWA.

import { appsMetadata } from '../data/appsMetadata';
import type { AppMetadata, SkillMetadata } from '../types/apps';

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

/**
 * Gets skills for a specific app.
 * 
 * Data Source: 
 * - Static data: frontend/packages/ui/src/data/appsMetadata.ts
 * - Skill definitions: backend/shared/python_schemas/app_metadata_schemas.py:AppSkillDefinition
 * 
 * **Offline-First**: This is synchronous and works offline since data is
 * included in the build bundle.
 * 
 * @param appId - The ID of the app
 * @param apps - Optional map of app metadata (defaults to all apps from static data)
 * @returns Array of skills for the app, or empty array if app not found
 */
export function getAppSkills(
    appId: string,
    apps?: Record<string, AppMetadata>
): SkillMetadata[] {
    const appsToSearch = apps || appsMetadata;
    const app = appsToSearch[appId];
    return app?.skills || [];
}

/**
 * Gets metadata for a specific skill.
 * 
 * Data Source: 
 * - Static data: frontend/packages/ui/src/data/appsMetadata.ts
 * 
 * **Offline-First**: This is synchronous and works offline since data is
 * included in the build bundle.
 * 
 * @param appId - The ID of the app
 * @param skillId - The ID of the skill
 * @param apps - Optional map of app metadata (defaults to all apps from static data)
 * @returns Skill metadata, or undefined if not found
 */
export function getSkillMetadata(
    appId: string,
    skillId: string,
    apps?: Record<string, AppMetadata>
): SkillMetadata | undefined {
    const appsToSearch = apps || appsMetadata;
    const app = appsToSearch[appId];
    if (!app) {
        return undefined;
    }
    
    return app.skills.find(skill => skill.id === skillId);
}

/**
 * Gets metadata for a specific app.
 * 
 * Data Source: 
 * - Static data: frontend/packages/ui/src/data/appsMetadata.ts
 * 
 * **Offline-First**: This is synchronous and works offline since data is
 * included in the build bundle.
 * 
 * @param appId - The ID of the app
 * @returns App metadata, or undefined if not found (synchronous, no API call)
 */
export function getAppMetadata(appId: string): AppMetadata | undefined {
    return appsMetadata[appId];
}

