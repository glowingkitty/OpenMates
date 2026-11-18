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
export interface PublishedAppMemory {
  id: string; title: string; description: string; when_to_use: string; body: string;
  revision: string; source: 'app'; app_id: string; project_id?: null;
}

export interface AppMetadata {
  /** Read-only app-provided Memories, selected automatically when relevant. */
  memories?: PublishedAppMemory[];
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
  providers?: string[]; // List of provider names used by this app's skills
  provider_display_order?: string[]; // Optional: Custom order for provider icons in Apps preview
  internal?: boolean; // Internal implementation apps are omitted from settings metadata
  category?: string; // App category: "work" or "personal"
  last_updated?: string; // ISO date string of when the app was last updated (for "New apps" categorization)
  /** Runtime health status, set by appSkillsStore based on /v1/health.
   *  undefined or 'healthy' = normal. 'degraded'/'unhealthy'/'unknown' = shown greyed out with badge. */
  healthStatus?: 'healthy' | 'degraded' | 'unhealthy' | 'unknown';
}

/**
 * Skill metadata structure.
 *
 * **Backend Implementation**:
 * - Defined in: `backend/shared/python_schemas/app_metadata_schemas.py:AppSkillDefinition`
 * - Registered in: `backend/apps/base_app.py:_register_skill_routes()`
 * - Note: Implemented skills are enabled by default unless `default_enabled: false` is set.
 */
export interface SkillMetadata {
  id: string;
  name_translation_key: string; // Translation key for skill name
  description_translation_key: string; // Translation key for skill description
  pricing?: SkillPricing;
  cache_pricing?: { enabled: boolean; write_billing?: 'included_in_input' | 'separate'; status?: string; source_url?: string; reviewed_on?: string; effective_from?: string; expires_on?: string; eligible_hosts?: string[] };
  providers?: string[]; // List of provider names used by this skill
  /** Icon filename for this skill (e.g. "search.svg") — used in Apps skill cards */
  icon_image?: string;
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
    cache_read?: { per_credit_unit: number };
    cache_write?: { per_credit_unit: number };
    cache_write_1h?: { per_credit_unit: number };
  };
  /** `provider/model` whose token price the skill charges; its current (temporary) rates win for display. */
  tokens_model?: string;
  per_unit?: {
    credits: number;
    unit_name?: string;
  };
  per_minute?: number;
  per_second?: number;
  fixed?: number;
}

/**
 * Focus mode metadata structure (placeholder for future implementation).
 *
 * **Backend Implementation**:
 * - Defined in: `backend/shared/python_schemas/app_metadata_schemas.py:AppFocusDefinition`
 * - Note: Implemented focus modes are enabled by default unless `default_enabled: false` is set.
 */
export interface FocusPhaseDefinition {
  id: string;
  title: string;
  instructions: string;
  requirements: Array<{ id: string; text: string; type?: "semantic" | "user_confirmation" }>;
}

export interface FocusModeMetadata {
  phases_version?: 1;
  phases?: FocusPhaseDefinition[];
  id: string;
  name_translation_key: string; // Translation key for focus mode name
  description_translation_key: string; // Translation key for focus mode description
  /** Translation key for bullet-point process summary (from app.yml process field) */
  process_translation_key?: string;
  /** Authored canonical process bullets used only when localized text is absent. */
  process?: string[];
  /** Literal system prompt used when this focus mode is activated (from app.yml systemprompt) */
  system_prompt?: string;
  /** Translation key for system prompt when literal is not set (from app.yml systemprompt_translation_key) */
  system_prompt_translation_key?: string;
  /** Icon filename for this focus mode (e.g. "career_insights.svg") — used in the active focus pill above the message input */
  icon_image?: string;
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
