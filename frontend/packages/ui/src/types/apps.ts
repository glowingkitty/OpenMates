// frontend/packages/ui/src/types/apps.ts
// 
// TypeScript interfaces for app and skill metadata.
// These types match the backend schemas from backend/shared/python_schemas/app_metadata_schemas.py
// and the API response format from backend/core/api/app/routes/apps.py

/**
 * App metadata structure returned from the API.
 * 
 * **Backend Implementation**: 
 * - API endpoint: `backend/core/api/app/routes/apps.py:get_apps_metadata()`
 * - Schema source: `backend/shared/python_schemas/app_metadata_schemas.py`
 * - Discovery: `backend/core/api/main.py:discover_apps()`
 */
export interface AppMetadata {
    id: string;
    name?: string; // Optional: use name_translation_key for i18n
    name_translation_key?: string; // Translation key for app name (e.g., "app_translations.web.text")
    description?: string; // Optional: use description_translation_key for i18n
    description_translation_key?: string; // Translation key for app description (e.g., "app_translations.web.description.text")
    icon_image?: string;
    icon_colorgradient?: {
        start: string;
        end: string;
    };
    skills: SkillMetadata[];
    focus_modes: FocusModeMetadata[]; // Placeholder for future implementation
    settings_and_memories: MemoryFieldMetadata[]; // Maps to 'settings_and_memories' in app.yml
    providers?: string[]; // List of provider names used by this app's skills
    category?: string; // App category: "work" or "personal"
    last_updated?: string; // ISO date string of when the app was last updated (for "New apps" categorization)
}

/**
 * Skill metadata structure.
 * 
 * **Backend Implementation**: 
 * - Defined in: `backend/shared/python_schemas/app_metadata_schemas.py:AppSkillDefinition`
 * - Registered in: `backend/apps/base_app.py:_register_skill_routes()`
 * - Note: Only production-stage skills are included. Development skills are only available on development servers, not production servers.
 */
export interface SkillMetadata {
    id: string;
    name_translation_key: string; // Translation key for skill name
    description_translation_key: string; // Translation key for skill description
    pricing?: SkillPricing;
    providers?: string[]; // List of provider names used by this skill
}

/**
 * Skill pricing structure.
 * 
 * **Backend Implementation**: 
 * - Defined in: `backend/shared/python_schemas/app_metadata_schemas.py:AppPricing`
 * - Used in: `backend/apps/base_skill.py:SkillPricing`
 */
export interface SkillPricing {
    tokens?: {
        input?: { per_credit_unit: number };
        output?: { per_credit_unit: number };
    };
    per_unit?: {
        credits: number;
        unit_name?: string;
    };
    per_minute?: number;
    fixed?: number;
}

/**
 * Focus mode metadata structure (placeholder for future implementation).
 * 
 * **Backend Implementation**: 
 * - Defined in: `backend/shared/python_schemas/app_metadata_schemas.py:AppFocusDefinition`
 * - Note: Only production-stage focus modes are included. Development focus modes are only available on development servers, not production servers.
 */
export interface FocusModeMetadata {
    id: string;
    name_translation_key: string; // Translation key for focus mode name
    description_translation_key: string; // Translation key for focus mode description
}

/**
 * Settings and memories field metadata structure.
 * 
 * **Backend Implementation**: 
 * - Defined in: `backend/shared/python_schemas/app_metadata_schemas.py:AppMemoryFieldDefinition`
 * - Source: `settings_and_memories` field in app.yml files
 */
export interface MemoryFieldMetadata {
    id: string;
    name_translation_key: string; // Translation key for memory field name
    description_translation_key: string; // Translation key for memory field description
    type: string;
    schema_definition?: {
        type?: string;
        properties?: Record<string, {
            type?: string;
            description?: string;
            enum?: string[];
            default?: unknown;
            minimum?: number;
            maximum?: number;
        }>;
        required?: string[];
    }; // Optional JSON schema for form field generation
}

/**
 * API response structure for apps metadata endpoint.
 * 
 * **Backend Implementation**: 
 * - Endpoint: `backend/core/api/app/routes/apps.py:get_apps_metadata()`
 */
export interface AppsMetadataResponse {
    apps: Record<string, AppMetadata>;
}

