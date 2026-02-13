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
  name_translation_key?: string; // Translation key for app name (e.g., "app_translations.web")
  description?: string; // Optional: use description_translation_key for i18n
  description_translation_key?: string; // Translation key for app description (e.g., "app_translations.web.description")
  icon_image?: string;
  icon_colorgradient?: {
    start: string;
    end: string;
  };
  skills: SkillMetadata[];
  focus_modes: FocusModeMetadata[]; // Placeholder for future implementation
  settings_and_memories: MemoryFieldMetadata[]; // Maps to 'settings_and_memories' in app.yml
  providers?: string[]; // List of provider names used by this app's skills
  provider_display_order?: string[]; // Optional: Custom order for provider icons in App Store preview
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
/**
 * Schema property definition for settings/memories fields.
 * Supports auto_generated flag to mark fields that should be auto-populated
 * by the client (e.g., timestamps) rather than shown in forms.
 *
 * **Display Fields**:
 * - is_title: If true, this field's value is used as the entry title in list views
 * - is_subtitle: If true, this field's value is used as the entry subtitle in list views
 */
export interface SchemaPropertyDefinition {
  type?: string;
  description?: string;
  enum?: string[];
  default?: unknown;
  minimum?: number;
  maximum?: number;
  auto_generated?: boolean; // If true, field is auto-populated by client, not shown in form
  is_title?: boolean; // If true, this field's value is displayed as the entry title in list views
  is_subtitle?: boolean; // If true, this field's value is displayed as the entry subtitle in list views
}

export interface MemoryFieldMetadata {
  id: string;
  name_translation_key: string; // Translation key for memory field name
  description_translation_key: string; // Translation key for memory field description
  type: string;
  schema_definition?: {
    type?: string;
    properties?: Record<string, SchemaPropertyDefinition>;
    required?: string[];
  }; // Optional JSON schema for form field generation
  example_translation_keys?: string[]; // Translation keys for example entries shown to non-authenticated users (resolved via $text())
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

/**
 * Suggested settings/memory entry from post-processing.
 *
 * Generated by the AI during post-processing Phase 2 when the conversation
 * reveals user preferences worth remembering. The client displays these
 * as suggestion cards with "Reject" and "Add" options.
 *
 * **Backend Implementation**:
 * - Model: `backend/apps/ai/processing/postprocessor.py:SuggestedSettingsMemoryEntry`
 * - Generated by: `backend/apps/ai/processing/postprocessor.py:handle_memory_generation()`
 *
 * **Key Design Decisions**:
 * - `item_value` only contains fields the AI is certain about (no guessing)
 * - `suggested_title` is used for client-side deduplication against existing entries
 * - Server never sees which suggestions were rejected (zero-knowledge via hashes)
 */
export interface SuggestedSettingsMemoryEntry {
  app_id: string; // App ID (e.g., 'code', 'travel')
  item_type: string; // Category ID within the app (e.g., 'preferred_tech', 'trips')
  suggested_title: string; // Short title for deduplication (e.g., 'Python', 'Japan Trip')
  item_value: Record<string, unknown>; // Entry data matching category schema - only certain fields
}
