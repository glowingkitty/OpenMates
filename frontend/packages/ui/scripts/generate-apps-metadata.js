// frontend/packages/ui/scripts/generate-apps-metadata.js
//
// Build script to generate appsMetadata.ts from backend app.yml files.
// This script reads all app.yml files from backend/apps/ and generates
// a TypeScript file with app metadata for the frontend.
//
// **Usage**: Run this script during the build process to include app metadata
// in the frontend bundle. This allows offline browsing of the App Store.

import { readFileSync, readdirSync, statSync, writeFileSync } from 'fs';
import { join, dirname, resolve } from 'path';
import { fileURLToPath } from 'url';
import yaml from 'yaml';

// Get the directory of this script
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Paths
const BACKEND_APPS_DIR = resolve(__dirname, '../../../../backend/apps');
const OUTPUT_FILE = resolve(__dirname, '../src/data/appsMetadata.ts');

// Check if we should include development items
// Default to including development items unless explicitly set to production
const INCLUDE_DEVELOPMENT = process.env.NODE_ENV !== 'production' || process.env.INCLUDE_DEV_APPS === 'true';

/**
 * Recursively find all app.yml files in the backend/apps directory.
 * @returns Array of { appId, filePath } objects
 */
function findAppYamlFiles() {
    const apps = [];
    
    try {
        const entries = readdirSync(BACKEND_APPS_DIR, { withFileTypes: true });
        
        for (const entry of entries) {
            if (entry.isDirectory()) {
                const appId = entry.name;
                const appYmlPath = join(BACKEND_APPS_DIR, appId, 'app.yml');
                
                try {
                    if (statSync(appYmlPath).isFile()) {
                        apps.push({ appId, filePath: appYmlPath });
                    }
                } catch (err) {
                    // app.yml doesn't exist for this app, skip it
                    console.warn(`[generate-apps-metadata] No app.yml found for app: ${appId}`);
                }
            }
        }
    } catch (err) {
        console.error(`[generate-apps-metadata] Error reading backend/apps directory:`, err);
        throw err;
    }
    
    return apps;
}

/**
 * Auto-prepend prefix to translation key if it doesn't already have it.
 * This allows simplified keys in app.yml (e.g., "web.text" instead of "apps.web.text").
 * 
 * @param {string} key - The translation key (may or may not have prefix)
 * @param {string} prefix - The prefix to add (e.g., "apps.", "app_skills.")
 * @returns {string} Translation key with prefix
 */
function normalizeTranslationKey(key, prefix) {
    if (!key || typeof key !== 'string') {
        return key;
    }
    
    const trimmedKey = key.trim();
    
    // If key already starts with the prefix, return as-is
    if (trimmedKey.startsWith(prefix)) {
        return trimmedKey;
    }
    
    // Otherwise, prepend the prefix
    return prefix + trimmedKey;
}

/**
 * Parse app.yml file and convert to frontend AppMetadata format.
 * Only includes production-stage skills.
 * 
 * @param {string} appId - The app ID (directory name)
 * @param {string} filePath - Path to the app.yml file
 * @returns {Object|null} App metadata in frontend format, or null if invalid
 */
function parseAppYaml(appId, filePath) {
    try {
        const content = readFileSync(filePath, 'utf-8');
        const appData = yaml.parse(content);
        
        // Handle empty or null YAML (e.g., files with only comments)
        if (!appData || typeof appData !== 'object') {
            console.warn(`[generate-apps-metadata] ${appId}: YAML file is empty or contains only comments, skipping`);
            return null;
        }
        
        // Check if app has required fields (at least name/name_translation_key or description/description_translation_key)
        const hasName = appData.name && typeof appData.name === 'string' && appData.name.trim();
        const hasNameTranslationKey = appData.name_translation_key && typeof appData.name_translation_key === 'string' && appData.name_translation_key.trim();
        const hasDescription = appData.description && typeof appData.description === 'string' && appData.description.trim();
        const hasDescriptionTranslationKey = appData.description_translation_key && typeof appData.description_translation_key === 'string' && appData.description_translation_key.trim();
        
        if (!hasName && !hasNameTranslationKey && !hasDescription && !hasDescriptionTranslationKey) {
            console.warn(`[generate-apps-metadata] ${appId}: Missing required fields (name/name_translation_key and description/description_translation_key), skipping`);
            return null;
        }
        
        // Note: We do NOT check app-level stage. Apps are included if ANY of their
        // skills, settings_and_memories, or focuses have a stage matching the environment.
        // This allows apps to have mixed-stage content and still appear in the App Store
        // if they have at least one item matching the current environment.
        
        // Extract app metadata
        // Auto-prepend "apps." prefix to app-level translation keys if not already present
        const appMetadata = {
            id: appId,
            name: hasName ? (appData.name || '').trim() : undefined,
            name_translation_key: hasNameTranslationKey 
                ? normalizeTranslationKey((appData.name_translation_key || '').trim(), 'apps.') 
                : undefined,
            description: hasDescription ? (appData.description || '').trim() : undefined,
            description_translation_key: hasDescriptionTranslationKey 
                ? normalizeTranslationKey((appData.description_translation_key || '').trim(), 'apps.') 
                : undefined,
            icon_image: appData.icon_image ? (appData.icon_image || '').trim() : undefined,
            icon_colorgradient: appData.icon_colorgradient ? {
                start: (appData.icon_colorgradient.start || '').trim(),
                end: (appData.icon_colorgradient.end || '').trim()
            } : undefined,
            skills: [],
            focus_modes: [],
            memory_fields: [],
            providers: [], // Will be populated from skills
            category: appData.category ? (appData.category || '').trim() : undefined,
            last_updated: appData.last_updated ? (appData.last_updated || '').trim() : undefined
        };
        
        // Collect all unique providers from skills
        const providersSet = new Set();
        
        // Process skills - include production-stage skills, and development if INCLUDE_DEVELOPMENT is true
        if (Array.isArray(appData.skills)) {
            for (const skill of appData.skills) {
                const stage = (skill.stage || 'development').trim().toLowerCase();
                // Only include production-stage skills, or development if INCLUDE_DEVELOPMENT is true
                if (stage !== 'production' && (!INCLUDE_DEVELOPMENT || stage !== 'development')) {
                    continue;
                }
                
                // Auto-prepend "app_skills." prefix to skill translation keys if not already present
                const skillMetadata = {
                    id: (skill.id || '').trim(),
                    name_translation_key: normalizeTranslationKey(
                        (skill.name_translation_key || '').trim(), 
                        'app_skills.'
                    ),
                    description_translation_key: normalizeTranslationKey(
                        (skill.description_translation_key || '').trim(), 
                        'app_skills.'
                    )
                };
                
                // Extract providers from skill if present
                if (Array.isArray(skill.providers)) {
                    const skillProviders = skill.providers
                        .map(p => (p || '').trim())
                        .filter(p => p.length > 0);
                    skillMetadata.providers = skillProviders;
                    // Add to app-level providers set
                    skillProviders.forEach(provider => providersSet.add(provider));
                }
                
                // Process pricing if present
                if (skill.pricing) {
                    const pricing = {};
                    
                    if (skill.pricing.tokens) {
                        pricing.tokens = skill.pricing.tokens;
                    }
                    if (skill.pricing.per_unit) {
                        pricing.per_unit = skill.pricing.per_unit;
                    }
                    if (skill.pricing.per_minute !== undefined) {
                        pricing.per_minute = skill.pricing.per_minute;
                    }
                    if (skill.pricing.fixed !== undefined) {
                        pricing.fixed = skill.pricing.fixed;
                    }
                    
                    if (Object.keys(pricing).length > 0) {
                        skillMetadata.pricing = pricing;
                    }
                }
                
                // Only add skill if it has required fields
                if (skillMetadata.id && skillMetadata.name_translation_key && skillMetadata.description_translation_key) {
                    appMetadata.skills.push(skillMetadata);
                }
            }
        }
        
        // Convert providers set to sorted array
        appMetadata.providers = Array.from(providersSet).sort();
        
        // Process focus modes - include production-stage focus modes, and development if INCLUDE_DEVELOPMENT is true
        const focusModes = appData.focuses || appData.focus_modes || [];
        if (Array.isArray(focusModes)) {
            for (const focus of focusModes) {
                const stage = (focus.stage || 'development').trim().toLowerCase();
                // Only include production-stage focus modes, or development if INCLUDE_DEVELOPMENT is true
                if (stage !== 'production' && (!INCLUDE_DEVELOPMENT || stage !== 'development')) {
                    continue;
                }
                
                // Auto-prepend "app_focus_modes." prefix to focus mode translation keys if not already present
                const focusMetadata = {
                    id: (focus.id || '').trim(),
                    name_translation_key: normalizeTranslationKey(
                        (focus.name_translation_key || '').trim(), 
                        'app_focus_modes.'
                    ),
                    description_translation_key: normalizeTranslationKey(
                        (focus.description_translation_key || '').trim(), 
                        'app_focus_modes.'
                    )
                };
                
                if (focusMetadata.id && focusMetadata.name_translation_key && focusMetadata.description_translation_key) {
                    appMetadata.focus_modes.push(focusMetadata);
                }
            }
        }
        
        // Process settings_and_memories - include production-stage items, and development if INCLUDE_DEVELOPMENT is true
        // Note: settings_and_memories is the field name in app.yml, which maps to memory_fields in the metadata
        const settingsAndMemories = appData.settings_and_memories || [];
        if (Array.isArray(settingsAndMemories)) {
            for (const item of settingsAndMemories) {
                // Stage field is required - no default
                const stage = item.stage ? (item.stage || '').trim().toLowerCase() : null;
                if (!stage) {
                    continue;
                }
                // Only include production-stage settings_and_memories, or development if INCLUDE_DEVELOPMENT is true
                if (stage !== 'production' && (!INCLUDE_DEVELOPMENT || stage !== 'development')) {
                    continue;
                }
                
                // Auto-prepend "app_settings_memories." prefix to settings/memory translation keys if not already present
                const memoryMetadata = {
                    id: (item.id || '').trim(),
                    name_translation_key: normalizeTranslationKey(
                        (item.name_translation_key || '').trim(), 
                        'app_settings_memories.'
                    ),
                    description_translation_key: normalizeTranslationKey(
                        (item.description_translation_key || '').trim(), 
                        'app_settings_memories.'
                    ),
                    type: (item.type || 'single').trim()
                };
                
                if (memoryMetadata.id && memoryMetadata.name_translation_key && memoryMetadata.description_translation_key) {
                    appMetadata.memory_fields.push(memoryMetadata);
                }
            }
        }
        
        // Also process legacy memory_fields for backward compatibility
        const memoryFields = appData.memory_fields || appData.memory || [];
        if (Array.isArray(memoryFields)) {
            for (const memory of memoryFields) {
                // Stage field is required - no default
                const stage = memory.stage ? (memory.stage || '').trim().toLowerCase() : null;
                if (!stage) {
                    continue;
                }
                // Only include production-stage memory fields, or development if INCLUDE_DEVELOPMENT is true
                if (stage !== 'production' && (!INCLUDE_DEVELOPMENT || stage !== 'development')) {
                    continue;
                }
                
                // Auto-prepend "app_settings_memories." prefix to legacy memory field translation keys if not already present
                const memoryMetadata = {
                    id: (memory.id || '').trim(),
                    name_translation_key: normalizeTranslationKey(
                        (memory.name_translation_key || '').trim(), 
                        'app_settings_memories.'
                    ),
                    description_translation_key: normalizeTranslationKey(
                        (memory.description_translation_key || '').trim(), 
                        'app_settings_memories.'
                    ),
                    type: (memory.type || 'single').trim()
                };
                
                if (memoryMetadata.id && memoryMetadata.name_translation_key && memoryMetadata.description_translation_key) {
                    appMetadata.memory_fields.push(memoryMetadata);
                }
            }
        }
        
        // Only include apps that have at least one skill, focus mode, or settings_and_memories
        // with a stage matching the current environment (production or development).
        // Apps are included if ANY of their items match the environment stage, regardless
        // of app-level stage field (which we don't check).
        const hasContent = 
            appMetadata.skills.length > 0 || 
            appMetadata.focus_modes.length > 0 || 
            appMetadata.memory_fields.length > 0;
        
        if (!hasContent) {
            const stageType = INCLUDE_DEVELOPMENT ? 'production or development' : 'production';
            console.warn(`[generate-apps-metadata] ${appId}: No ${stageType} skills, focus modes, or settings_and_memories found. Excluding from App Store.`);
            return null;
        }
        
        return appMetadata;
    } catch (err) {
        // Handle YAML parsing errors more gracefully
        if (err.name === 'YAMLParseError' || err.name === 'YAMLSyntaxError') {
            console.error(`[generate-apps-metadata] ${appId}: YAML syntax error - ${err.message}`);
            if (err.linePos && err.linePos.length > 0) {
                const pos = err.linePos[0];
                console.error(`[generate-apps-metadata] ${appId}: Error at line ${pos.line}, column ${pos.col}`);
            }
        } else {
            console.error(`[generate-apps-metadata] ${appId}: Error parsing app.yml - ${err.message}`);
        }
        return null;
    }
}

/**
 * Generate TypeScript code for appsMetadata.ts
 * @param {Object} appsMetadata - Object mapping app IDs to app metadata
 * @returns {string} TypeScript code
 */
function generateTypeScript(appsMetadata) {
    const apps = Object.entries(appsMetadata)
        .map(([appId, app]) => {
            // Format app metadata as TypeScript object
            const lines = [`    "${appId}": {`];
            lines.push(`        id: "${app.id}",`);
            if (app.name !== undefined) {
                lines.push(`        name: ${JSON.stringify(app.name)},`);
            }
            if (app.name_translation_key !== undefined) {
                lines.push(`        name_translation_key: ${JSON.stringify(app.name_translation_key)},`);
            }
            if (app.description !== undefined) {
                lines.push(`        description: ${JSON.stringify(app.description)},`);
            }
            if (app.description_translation_key !== undefined) {
                lines.push(`        description_translation_key: ${JSON.stringify(app.description_translation_key)},`);
            }
            
            if (app.icon_image) {
                lines.push(`        icon_image: ${JSON.stringify(app.icon_image)},`);
            }
            
            if (app.icon_colorgradient) {
                lines.push(`        icon_colorgradient: {`);
                lines.push(`            start: ${JSON.stringify(app.icon_colorgradient.start)},`);
                lines.push(`            end: ${JSON.stringify(app.icon_colorgradient.end)}`);
                lines.push(`        },`);
            }
            
            // Providers array (if present)
            if (app.providers && app.providers.length > 0) {
                lines.push(`        providers: [`);
                for (const provider of app.providers) {
                    lines.push(`            ${JSON.stringify(provider)},`);
                }
                lines.push(`        ],`);
            }
            
            // Category (if present)
            if (app.category) {
                lines.push(`        category: ${JSON.stringify(app.category)},`);
            }
            
            // last_updated (if present)
            if (app.last_updated) {
                lines.push(`        last_updated: ${JSON.stringify(app.last_updated)},`);
            }
            
            // Skills array
            lines.push(`        skills: [`);
            for (const skill of app.skills) {
                lines.push(`            {`);
                lines.push(`                id: ${JSON.stringify(skill.id)},`);
                lines.push(`                name_translation_key: ${JSON.stringify(skill.name_translation_key)},`);
                lines.push(`                description_translation_key: ${JSON.stringify(skill.description_translation_key)},`);
                if (skill.pricing) {
                    lines.push(`                pricing: ${JSON.stringify(skill.pricing)},`);
                }
                if (skill.providers && skill.providers.length > 0) {
                    lines.push(`                providers: ${JSON.stringify(skill.providers)},`);
                }
                lines.push(`            },`);
            }
            lines.push(`        ],`);
            
            // Focus modes array
            lines.push(`        focus_modes: [`);
            for (const focus of app.focus_modes) {
                lines.push(`            {`);
                lines.push(`                id: ${JSON.stringify(focus.id)},`);
                lines.push(`                name_translation_key: ${JSON.stringify(focus.name_translation_key)},`);
                lines.push(`                description_translation_key: ${JSON.stringify(focus.description_translation_key)}`);
                lines.push(`            },`);
            }
            lines.push(`        ],`);
            
            // Memory fields array
            lines.push(`        memory_fields: [`);
            for (const memory of app.memory_fields) {
                lines.push(`            {`);
                lines.push(`                id: ${JSON.stringify(memory.id)},`);
                lines.push(`                name_translation_key: ${JSON.stringify(memory.name_translation_key)},`);
                lines.push(`                description_translation_key: ${JSON.stringify(memory.description_translation_key)},`);
                lines.push(`                type: ${JSON.stringify(memory.type)}`);
                lines.push(`            },`);
            }
            lines.push(`        ]`);
            
            lines.push(`    },`);
            return lines.join('\n');
        })
        .join('\n\n');
    
    return `// frontend/packages/ui/src/data/appsMetadata.ts
//
// ⚠️  WARNING: THIS FILE IS AUTO-GENERATED - DO NOT EDIT MANUALLY ⚠️
//
// This file is automatically generated from backend app.yml files during the build process.
// Any manual edits will be overwritten the next time the build runs.
//
// To modify app metadata, edit the source files:
// - App definitions: backend/apps/{app_id}/app.yml
// - Schema: backend/shared/python_schemas/app_metadata_schemas.py
//
// Generation script: frontend/packages/ui/scripts/generate-apps-metadata.js
// This script runs automatically via the 'prebuild' hook in package.json
//
// **Build Process**: 
// This file is generated during the build process by running:
//   npm run generate-apps-metadata
//   (or automatically via: npm run build)
//
// **Note**: Only production-stage skills are included. Development skills
// are only available on development servers, not production servers.
//
// **Usage**: Import and use directly - no API calls needed
// \`\`\`typescript
// import { appsMetadata } from '@repo/ui/data/appsMetadata';
// \`\`\`

import type { AppMetadata } from '../types/apps';

/**
 * Static apps metadata included in the build.
 * 
 * This data is generated at build time from backend app.yml files and included
 * in the web app bundle, allowing offline browsing of available apps, skills, and pricing.
 * 
 * **Generated**: ${new Date().toISOString()}
 * **Apps included**: ${Object.keys(appsMetadata).length}
 */
export const appsMetadata: Record<string, AppMetadata> = {
${apps}
};
`;
}

/**
 * Main function to generate appsMetadata.ts
 */
function main() {
    console.log('[generate-apps-metadata] Starting app metadata generation...');
    console.log(`[generate-apps-metadata] Reading apps from: ${BACKEND_APPS_DIR}`);
    
    // Find all app.yml files
    const appFiles = findAppYamlFiles();
    console.log(`[generate-apps-metadata] Found ${appFiles.length} app(s)`);
    
    // Parse each app.yml file
    const appsMetadata = {};
    for (const { appId, filePath } of appFiles) {
        console.log(`[generate-apps-metadata] Processing: ${appId}`);
        const appMetadata = parseAppYaml(appId, filePath);
        
        if (appMetadata) {
            appsMetadata[appId] = appMetadata;
            const skillsCount = appMetadata.skills.length;
            const focusCount = appMetadata.focus_modes.length;
            const memoryCount = appMetadata.memory_fields.length;
            console.log(`[generate-apps-metadata]   ✓ ${appId}: ${skillsCount} skill(s), ${focusCount} focus mode(s), ${memoryCount} settings/memory field(s)`);
        } else {
            console.warn(`[generate-apps-metadata]   ✗ ${appId}: Failed to parse or excluded (no production content)`);
        }
    }
    
    // Generate TypeScript code
    const tsCode = generateTypeScript(appsMetadata);
    
    // Write to file
    writeFileSync(OUTPUT_FILE, tsCode, 'utf-8');
    console.log(`[generate-apps-metadata] Generated: ${OUTPUT_FILE}`);
    console.log(`[generate-apps-metadata] ✓ Successfully generated metadata for ${Object.keys(appsMetadata).length} app(s)`);
}

// Run the script
main();
